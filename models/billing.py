"""SaaS 비즈니스 트랙 (Phase 2 → C-3, 2026-05-12) — shared 의 factory 사용.

ADK 의 기존 테이블명 (``billing_plans``, ``billing_subscriptions``,
``billing_usage_records``, ``billing_monthly_user_usage``) 을 그대로 유지하면서
ORM 클래스 정의는 ``shared_libraries.saas.billing_models.make_billing_models`` 로
일원화한다 (DRY). Alembic adk006_billing 의 스키마는 변경 없음 — 회귀 보존.
"""
from __future__ import annotations

from database import Base
from saas import make_billing_models

(
    BillingPlan,
    BillingSubscription,
    BillingUsageRecord,
    BillingMonthlyUserUsage,
) = make_billing_models(Base, table_prefix="")

__all__ = [
    "BillingPlan",
    "BillingSubscription",
    "BillingUsageRecord",
    "BillingMonthlyUserUsage",
]
