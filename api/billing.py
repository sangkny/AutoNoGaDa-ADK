"""SaaS 비즈니스 트랙 (Phase 2) — Billing 라우트.

엔드포인트:
    - ``GET  /api/v1/billing/plans``      — 카탈로그 (공개)
    - ``GET  /api/v1/billing/me``         — 본인 구독 + 당월 사용량 (인증)
    - ``POST /api/v1/billing/subscribe``  — admin 만 — user 의 plan 강제 전환
    - ``GET  /api/v1/billing/usage``      — 본인의 월별 사용 이력 (인증)
    - ``GET  /api/v1/billing/usage/timeline`` — 본인의 일별 시계열 (인증, B-5)

결제 게이트웨이 (Stripe Checkout + webhook) 는 B-7 백로그. 현재는 admin 이
직접 `POST /billing/subscribe` 로 plan 을 부여한다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import current_user_strict, require_role
from database import get_db
from models import (
    BillingMonthlyUserUsage,
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
)
from schemas.billing import (
    AdminStatsResponse,
    MeResponse,
    PlanDistributionEntry,
    PlanListResponse,
    PlanOut,
    SubscribeRequest,
    SubscribeResponse,
    SubscriptionOut,
    UsageHistoryEntry,
    UsageHistoryResponse,
    UsageSnapshot,
    UsageTimelinePoint,
    UsageTimelineResponse,
)
from services.billing import (
    DEFAULT_FREE_PLAN_CODE,
    current_year_month,
    get_or_create_active_subscription,
    get_or_create_monthly_usage,
    list_active_plans,
    parse_allowed_models,
    switch_subscription,
    usage_snapshot_dict,
)

router = APIRouter()


@router.get(
    "/plans",
    response_model=PlanListResponse,
    summary="Plan 카탈로그 (공개)",
)
async def list_plans(db: AsyncSession = Depends(get_db)) -> PlanListResponse:
    rows = await list_active_plans(db)
    plans = [
        PlanOut(
            code=p.code,
            name=p.name,
            price_usd_per_month=float(p.price_usd_per_month),
            monthly_call_quota=p.monthly_call_quota,
            allowed_models=parse_allowed_models(p.allowed_models),
            description=p.description,
            is_active=bool(p.is_active),
        )
        for p in rows
    ]
    return PlanListResponse(plans=plans, default_code=DEFAULT_FREE_PLAN_CODE)


@router.get(
    "/me",
    response_model=MeResponse,
    summary="본인 구독 + 당월 사용량",
)
async def get_me(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> MeResponse:
    user_id = user["user_id"]
    sub, plan = await get_or_create_active_subscription(db, user_id)
    monthly = await get_or_create_monthly_usage(db, user_id)
    return MeResponse(
        user_id=user_id,
        role=user.get("role", ""),
        subscription=SubscriptionOut(
            plan_code=plan.code,
            plan_name=plan.name,
            monthly_call_quota=plan.monthly_call_quota,
            allowed_models=parse_allowed_models(plan.allowed_models),
            started_at=sub.started_at,
            current_period_end=sub.current_period_end,
        ),
        usage=UsageSnapshot(**usage_snapshot_dict(monthly, plan)),
    )


@router.post(
    "/subscribe",
    response_model=SubscribeResponse,
    summary="admin — 사용자에게 plan 부여 (수동, 결제 게이트웨이는 B-7 백로그)",
)
async def admin_subscribe(
    body: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> SubscribeResponse:
    try:
        sub, plan, previous = await switch_subscription(
            db, body.user_id, body.plan_code
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return SubscribeResponse(
        user_id=body.user_id,
        plan_code=plan.code,
        previous_plan_code=previous,
        started_at=sub.started_at,
    )


@router.get(
    "/usage",
    response_model=UsageHistoryResponse,
    summary="본인의 월별 사용 이력",
)
async def get_usage_history(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
    months: int = Query(6, ge=1, le=36),
) -> UsageHistoryResponse:
    user_id = user["user_id"]
    rows = await db.execute(
        select(BillingMonthlyUserUsage)
        .where(BillingMonthlyUserUsage.user_id == user_id)
        .order_by(BillingMonthlyUserUsage.year_month.desc())
        .limit(int(months))
    )
    history = [
        UsageHistoryEntry(
            year_month=r.year_month,
            calls_count=int(r.calls_count or 0),
            tokens_total=int(r.tokens_total or 0),
            cost_usd=float(r.cost_usd or 0),
        )
        for r in rows.scalars().all()
    ]
    return UsageHistoryResponse(user_id=user_id, history=history)


@router.get(
    "/usage/timeline",
    response_model=UsageTimelineResponse,
    summary="본인의 일별 호출 시계열",
)
async def get_usage_timeline(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
    days: int = Query(30, ge=1, le=365),
) -> UsageTimelineResponse:
    user_id = user["user_id"]
    since = datetime.now(timezone.utc) - timedelta(days=int(days))
    rows = await db.execute(
        select(
            func.date_trunc("day", BillingUsageRecord.created_at).label("d"),
            func.count().label("calls"),
            func.coalesce(func.sum(BillingUsageRecord.tokens_estimated), 0).label(
                "tokens"
            ),
        )
        .where(BillingUsageRecord.user_id == user_id)
        .where(BillingUsageRecord.created_at >= since)
        .group_by("d")
        .order_by("d")
    )
    points: list[UsageTimelinePoint] = []
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "tokens": 0})
    for d, calls, tokens in rows.all():
        if d is None:
            continue
        key = d.date().isoformat()
        by_day[key]["calls"] = int(calls or 0)
        by_day[key]["tokens"] = int(tokens or 0)
    for key in sorted(by_day.keys()):
        points.append(
            UsageTimelinePoint(
                date=key, calls=by_day[key]["calls"], tokens=by_day[key]["tokens"]
            )
        )
    return UsageTimelineResponse(user_id=user_id, days=int(days), points=points)


@router.get(
    "/admin/stats",
    response_model=AdminStatsResponse,
    summary="admin — 전체 활성 가입자·매출·당월 사용량 통계",
)
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> AdminStatsResponse:
    ym = current_year_month()

    plan_rows = await db.execute(
        select(
            BillingPlan.code,
            BillingPlan.name,
            BillingPlan.price_usd_per_month,
            func.count(BillingSubscription.id),
        )
        .select_from(BillingPlan)
        .join(
            BillingSubscription,
            (BillingSubscription.plan_id == BillingPlan.id)
            & (BillingSubscription.status == "active"),
            isouter=True,
        )
        .group_by(
            BillingPlan.code, BillingPlan.name, BillingPlan.price_usd_per_month
        )
        .order_by(BillingPlan.price_usd_per_month)
    )

    distribution: list[PlanDistributionEntry] = []
    total_subs = 0
    total_revenue = 0.0
    for code, name, price, subs in plan_rows.all():
        n = int(subs or 0)
        p = float(price or 0)
        revenue = p * n
        total_subs += n
        total_revenue += revenue
        distribution.append(
            PlanDistributionEntry(
                plan_code=code,
                plan_name=name,
                active_subscribers=n,
                price_usd_per_month=p,
                monthly_revenue_usd=round(revenue, 2),
            )
        )

    usage_agg = await db.execute(
        select(
            func.coalesce(func.sum(BillingMonthlyUserUsage.calls_count), 0),
            func.coalesce(func.sum(BillingMonthlyUserUsage.tokens_total), 0),
        ).where(BillingMonthlyUserUsage.year_month == ym)
    )
    calls_total, tokens_total = usage_agg.one()

    return AdminStatsResponse(
        year_month=ym,
        total_active_subscribers=total_subs,
        total_monthly_revenue_usd=round(total_revenue, 2),
        total_calls_this_month=int(calls_total or 0),
        total_tokens_this_month=int(tokens_total or 0),
        plan_distribution=distribution,
    )
