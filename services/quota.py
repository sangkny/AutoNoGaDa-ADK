"""SaaS 비즈니스 트랙 (Phase 2) — Quota Enforcement.

설계 결정 (B-3, 2026-05-12):
    - 호출 *전* 한도 *확인* 만 한다 (count 증가 X). 호출 *후* 기록은 B-4 의
      `pipeline_runner` 후처리 후크가 담당한다.
    - 이유: race condition 은 대부분 사용자 한도가 풍부해 무시 가능하고,
      실패 호출까지 차감하면 사용자가 손해. 정확한 사용량 후기록이 우선.
    - 무제한 plan (Ent) 은 ``X-RateLimit-Limit: -1``, ``-Remaining: -1``.
    - ``X-RateLimit-Reset`` 은 다음 달 1일 00:00 UTC 의 Unix timestamp.

엔드포인트는 `enforce_quota("generate")` deps 를 의존성으로 받아 `QuotaContext`
를 반환받는다. 라우트는 이 context 를 ``pipeline_runner`` 에 전달해 후처리에서
사용 기록 (`record_usage`) 을 남긴다.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable

from fastapi import Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

import uuid

from auth.dependencies import current_user_strict
from database import get_db
from models import BillingPlan, BillingSubscription, BillingUsageRecord
from services.billing import (
    current_year_month,
    get_or_create_active_subscription,
    get_or_create_monthly_usage,
)

log = logging.getLogger("services.quota")


# ── 데이터 ──────────────────────────────────────────────────────────


@dataclass
class QuotaContext:
    """라우트 핸들러가 받는 quota 컨텍스트.

    `pipeline_runner` 가 호출 종료 시 ``record_usage()`` 헬퍼로 사용 기록을
    남긴다. ``plan_code`` 는 호출 시점의 plan 을 스냅샷.
    """

    user_id: str
    role: str
    action: str
    plan_code: str
    monthly_call_quota: int | None
    allowed_models: str
    calls_used_before: int


def _next_month_reset_ts(now: datetime | None = None) -> int:
    """다음 달 1일 00:00 UTC 의 Unix timestamp."""
    n = now or datetime.now(timezone.utc)
    year = n.year + (1 if n.month == 12 else 0)
    month = 1 if n.month == 12 else n.month + 1
    reset = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    return int(reset.timestamp())


def quota_headers(quota: int | None, used: int, *, reset_ts: int | None = None) -> dict[str, str]:
    """표준 ``X-RateLimit-*`` 헤더 dict."""
    if quota is None:
        limit_s = "-1"
        remaining_s = "-1"
    else:
        limit_s = str(int(quota))
        remaining_s = str(max(0, int(quota) - int(used)))
    return {
        "X-RateLimit-Limit": limit_s,
        "X-RateLimit-Remaining": remaining_s,
        "X-RateLimit-Reset": str(reset_ts or _next_month_reset_ts()),
    }


# ── Enforcement ─────────────────────────────────────────────────────


async def _load_active_plan(
    db: AsyncSession, user_id: str
) -> tuple[BillingSubscription, BillingPlan]:
    """활성 구독 + Plan (없으면 Free 자동 생성)."""
    return await get_or_create_active_subscription(db, user_id)


def enforce_quota(action: str) -> Callable[..., Awaitable[QuotaContext]]:
    """FastAPI dependency factory.

    사용 예::

        @router.post("/generate")
        async def generate(
            req: PipelineGenerateRequest,
            quota: QuotaContext = Depends(enforce_quota("generate")),
            db: AsyncSession = Depends(get_db),
        ):
            ...
    """

    async def _dep(
        response: Response,
        db: AsyncSession = Depends(get_db),
        user: dict = Depends(current_user_strict),
    ) -> QuotaContext:
        user_id = user["user_id"]
        sub, plan = await _load_active_plan(db, user_id)
        monthly = await get_or_create_monthly_usage(db, user_id)
        used = int(monthly.calls_count or 0)
        quota = plan.monthly_call_quota
        reset_ts = _next_month_reset_ts()
        headers = quota_headers(quota, used, reset_ts=reset_ts)

        if quota is not None and used >= int(quota):
            log.info(
                "quota_exceeded user_id=%s action=%s plan=%s used=%d limit=%d",
                user_id, action, plan.code, used, int(quota),
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "message": (
                        f"월 호출 한도 초과 (plan={plan.code}, used={used}/{int(quota)}). "
                        f"plan 업그레이드 또는 다음 달까지 대기."
                    ),
                    "plan_code": plan.code,
                    "calls_used": used,
                    "calls_limit": int(quota),
                    "year_month": current_year_month(),
                    "upgrade_hint": "POST /api/v1/billing/subscribe (admin) 또는 customer portal (백로그)",
                },
                headers=headers,
            )

        # 정상 — 응답 헤더로 잔여 한도 전달 (호출 *전* 값. 후처리에서 정확히
        # 갱신되지만 클라이언트는 다음 호출에서 새 값 수신)
        for hk, hv in headers.items():
            response.headers[hk] = hv
        return QuotaContext(
            user_id=user_id,
            role=user.get("role", ""),
            action=action,
            plan_code=plan.code,
            monthly_call_quota=quota,
            allowed_models=plan.allowed_models or "FAST",
            calls_used_before=used,
        )

    return _dep


async def record_call(
    db: AsyncSession,
    quota: QuotaContext,
    *,
    success: bool,
    model_used: str | None = None,
    tokens_estimated: int = 0,
    latency_ms: int | None = None,
) -> None:
    """호출 종료 후 사용량을 기록 (B-4).

    ``BillingUsageRecord`` 에 호출 단위 row 를 추가하고, ``BillingMonthlyUserUsage``
    에 calls_count / tokens_total 을 upsert. 예외는 모두 잡아 로그만 (라우트가
    이미 응답을 반환한 시점일 수 있어 errror 가 클라이언트에 전달되면 안 됨).

    호출 *전* `enforce_quota` 가 count 를 증가시키지 *않*았으므로 여기서
    +1 하는 게 정확. 실패 호출도 사용량으로 칠지 여부는 ``success`` 로
    구분만 하고 모두 기록 (분석용); ``calls_count`` 는 성공 시에만 증가
    (사용자가 자기 한도를 실패로 소진하지 않도록).
    """
    try:
        rec = BillingUsageRecord(
            id=str(uuid.uuid4()),
            user_id=quota.user_id,
            action=quota.action,
            plan_code=quota.plan_code,
            tokens_estimated=int(tokens_estimated or 0),
            model_used=model_used,
            success=bool(success),
            latency_ms=int(latency_ms) if latency_ms is not None else None,
        )
        db.add(rec)

        if success:
            monthly = await get_or_create_monthly_usage(db, quota.user_id)
            monthly.calls_count = int(monthly.calls_count or 0) + 1
            monthly.tokens_total = int(monthly.tokens_total or 0) + int(
                tokens_estimated or 0
            )
        await db.flush()
    except Exception:
        log.exception(
            "record_call 실패 user_id=%s action=%s — 사용량 기록 누락",
            quota.user_id,
            quota.action,
        )


__all__ = [
    "QuotaContext",
    "enforce_quota",
    "quota_headers",
    "record_call",
]
