"""SaaS 비즈니스 트랙 (Phase 2 → C-3) — shared.BillingService 위임.

ADK 가 자기 ORM (``models.billing``) 으로 ``BillingService`` 인스턴스를 생성하고,
기존에 ADK 가 노출하던 함수형 API (``get_or_create_active_subscription`` 등) 는
이 인스턴스의 메서드를 호출하는 thin wrapper 로 유지한다 (api/billing.py 가
이전 import 를 그대로 쓸 수 있도록 — 회귀 없음).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.billing import (
    BillingMonthlyUserUsage,
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
)
from saas import BillingService
from saas.helpers import (
    DEFAULT_FREE_PLAN_CODE,
    current_year_month,
    parse_allowed_models,
    usage_snapshot_dict,
)

# ADK 도메인 BillingService 인스턴스 (shared 의 logic + ADK 의 ORM).
adk_billing = BillingService(
    plan_cls=BillingPlan,
    subscription_cls=BillingSubscription,
    usage_record_cls=BillingUsageRecord,
    monthly_usage_cls=BillingMonthlyUserUsage,
    default_free_code=DEFAULT_FREE_PLAN_CODE,
)


# ── 기존 함수형 API (api/billing.py 호환) ───────────────────────────


async def get_plan_by_code(db: AsyncSession, code: str):
    return await adk_billing.get_plan_by_code(db, code)


async def list_active_plans(db: AsyncSession) -> list[Any]:
    return await adk_billing.list_active_plans(db)


async def get_active_subscription(db: AsyncSession, user_id: str):
    return await adk_billing.get_active_subscription(db, user_id)


async def get_or_create_active_subscription(
    db: AsyncSession, user_id: str
) -> tuple[Any, Any]:
    return await adk_billing.get_or_create_active_subscription(db, user_id)


async def switch_subscription(
    db: AsyncSession, user_id: str, new_plan_code: str
) -> tuple[Any, Any, str | None]:
    return await adk_billing.switch_subscription(db, user_id, new_plan_code)


async def get_or_create_monthly_usage(
    db: AsyncSession, user_id: str, *, year_month: str | None = None
):
    return await adk_billing.get_or_create_monthly_usage(
        db, user_id, year_month=year_month
    )


__all__ = [
    "DEFAULT_FREE_PLAN_CODE",
    "adk_billing",
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
