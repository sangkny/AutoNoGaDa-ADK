"""SaaS 비즈니스 트랙 (Phase 2) — Billing 서비스 헬퍼.

`api/billing.py` 와 `services/quota.py` 가 공유하는 도메인 헬퍼:
    - ``DEFAULT_FREE_PLAN_CODE``                — 미가입자가 자동 할당될 plan
    - ``get_plan_by_code``                      — 카탈로그 조회 (lru_cache 가능, 우선 단순 select)
    - ``get_or_create_active_subscription``     — user_id 의 활성 구독 조회 (없으면 free 자동)
    - ``switch_subscription``                   — plan 전환 (감사 추적: 이전 row cancelled)
    - ``current_year_month`` / ``ensure_monthly_usage_row``
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    BillingMonthlyUserUsage,
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
)

DEFAULT_FREE_PLAN_CODE = "free"


def current_year_month(now: datetime | None = None) -> str:
    """``YYYY-MM`` 문자열 — 청구·집계 키."""
    d = (now or datetime.now(timezone.utc)).date()
    return d.strftime("%Y-%m")


async def get_plan_by_code(db: AsyncSession, code: str) -> BillingPlan | None:
    """Plan 코드로 카탈로그 조회 (활성 / 비활성 모두 반환)."""
    return await db.scalar(select(BillingPlan).where(BillingPlan.code == code))


async def list_active_plans(db: AsyncSession) -> list[BillingPlan]:
    """공개 카탈로그 — ``is_active=True`` 만 노출."""
    rows = await db.execute(
        select(BillingPlan)
        .where(BillingPlan.is_active.is_(True))
        .order_by(BillingPlan.price_usd_per_month)
    )
    return list(rows.scalars().all())


async def get_active_subscription(
    db: AsyncSession, user_id: str
) -> BillingSubscription | None:
    """활성 구독 1건 조회 (없으면 None)."""
    return await db.scalar(
        select(BillingSubscription)
        .where(BillingSubscription.user_id == user_id)
        .where(BillingSubscription.status == "active")
        .order_by(BillingSubscription.started_at.desc())
        .limit(1)
    )


async def get_or_create_active_subscription(
    db: AsyncSession, user_id: str
) -> tuple[BillingSubscription, BillingPlan]:
    """활성 구독 없음 → Free Plan 자동 구독.

    SaaS 의 통상 패턴 — 미가입자도 즉시 호출 가능 (Free 한도 내). admin 이
    명시적으로 다른 plan 으로 전환할 때까지 Free 유지.
    """
    sub = await get_active_subscription(db, user_id)
    if sub is not None:
        plan = await db.scalar(
            select(BillingPlan).where(BillingPlan.id == sub.plan_id)
        )
        if plan is not None:
            return sub, plan

    free = await get_plan_by_code(db, DEFAULT_FREE_PLAN_CODE)
    if free is None:
        raise RuntimeError(
            f"기본 plan '{DEFAULT_FREE_PLAN_CODE}' 가 시드되지 않음 — alembic adk006 적용 필요"
        )
    sub = BillingSubscription(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_id=free.id,
        status="active",
    )
    db.add(sub)
    await db.flush()
    return sub, free


async def switch_subscription(
    db: AsyncSession, user_id: str, new_plan_code: str
) -> tuple[BillingSubscription, BillingPlan, str | None]:
    """plan 전환 — 기존 row 를 ``cancelled`` 로 마킹하고 새 row 활성화.

    반환: (신규 active 구독, 신규 plan, 이전 plan_code | None)
    """
    new_plan = await get_plan_by_code(db, new_plan_code)
    if new_plan is None or not new_plan.is_active:
        raise ValueError(f"unknown or inactive plan: {new_plan_code}")

    previous_code: str | None = None
    existing = await get_active_subscription(db, user_id)
    if existing is not None:
        prev_plan = await db.scalar(
            select(BillingPlan).where(BillingPlan.id == existing.plan_id)
        )
        previous_code = prev_plan.code if prev_plan else None
        if previous_code == new_plan_code:
            # 동일 plan 재구독 — 변경 없음
            return existing, new_plan, previous_code
        existing.status = "cancelled"
        existing.cancelled_at = datetime.now(timezone.utc)
        await db.flush()

    sub = BillingSubscription(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_id=new_plan.id,
        status="active",
    )
    db.add(sub)
    await db.flush()
    return sub, new_plan, previous_code


async def get_or_create_monthly_usage(
    db: AsyncSession, user_id: str, *, year_month: str | None = None
) -> BillingMonthlyUserUsage:
    """월별 집계 row 보장 — 없으면 0 으로 생성."""
    ym = year_month or current_year_month()
    row = await db.scalar(
        select(BillingMonthlyUserUsage)
        .where(BillingMonthlyUserUsage.user_id == user_id)
        .where(BillingMonthlyUserUsage.year_month == ym)
    )
    if row is not None:
        return row
    row = BillingMonthlyUserUsage(
        id=str(uuid.uuid4()),
        user_id=user_id,
        year_month=ym,
        calls_count=0,
        tokens_total=0,
        cost_usd=0,
    )
    db.add(row)
    await db.flush()
    return row


def parse_allowed_models(allowed_models: str) -> list[str]:
    """``"FAST,HEAVY"`` → ``["FAST", "HEAVY"]``."""
    return [tok.strip() for tok in (allowed_models or "").split(",") if tok.strip()]


def usage_snapshot_dict(
    monthly: BillingMonthlyUserUsage, plan: BillingPlan
) -> dict[str, Any]:
    """`UsageSnapshot` Pydantic 스키마용 dict 변환."""
    quota = plan.monthly_call_quota
    used = int(monthly.calls_count or 0)
    if quota is None:
        remaining: int | None = None
        pct = 0.0
    else:
        remaining = max(0, int(quota) - used)
        pct = (used / int(quota) * 100.0) if int(quota) > 0 else 0.0
    return {
        "year_month": monthly.year_month,
        "calls_used": used,
        "calls_limit": int(quota) if quota is not None else None,
        "calls_remaining": remaining,
        "quota_pct": round(float(pct), 2),
        "tokens_total": int(monthly.tokens_total or 0),
        "cost_usd": float(monthly.cost_usd or 0),
    }


__all__ = [
    "DEFAULT_FREE_PLAN_CODE",
    "current_year_month",
    "get_plan_by_code",
    "list_active_plans",
    "get_active_subscription",
    "get_or_create_active_subscription",
    "switch_subscription",
    "get_or_create_monthly_usage",
    "parse_allowed_models",
    "usage_snapshot_dict",
]
