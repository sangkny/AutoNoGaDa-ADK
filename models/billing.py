"""SaaS 비즈니스 트랙 (Phase 2) — Subscription Plan / Quota / Usage ORM.

한장요약 §"AutoNoGaDa ADK 가격 모델" 의 Dev $29 / Team $99 / Ent $499+ 3-tier
를 자체적으로 관리한다. 결제 게이트웨이 (Stripe 등) 는 백로그 (B-7) — 현재는
admin API 가 ``POST /api/v1/billing/subscribe`` 로 직접 Plan 을 부여한다.

4개 테이블:
    - ``billing_plans``                — Plan 카탈로그 (시드 4종: free/dev/team/ent)
    - ``billing_subscriptions``        — user_id → plan 연결 (1:1, 활성 단일)
    - ``billing_usage_records``        — 호출 단위 사용 기록 (감사·분석)
    - ``billing_monthly_user_usage``   — 월별 사용자별 집계 (성능 위)

User 모델은 별도 테이블 없이 JWT ``sub`` (e.g. ``user@example.com``) 를 직접
``user_id`` 로 사용한다. 추후 user 테이블이 신설되면 FK 로 승격.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class BillingPlan(Base):
    """SaaS Plan 카탈로그.

    ``monthly_call_quota`` 가 ``None`` 이면 무제한 (Ent). ``allowed_models`` 는
    CSV 형태 (``"FAST"``, ``"FAST,HEAVY"``, ``"FAST,HEAVY,CONSENSUS"``) — 모델
    선택 시 `CostOptimizerService` 의 출력과 교차 검증한다.
    """

    __tablename__ = "billing_plans"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    price_usd_per_month: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    monthly_call_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowed_models: Mapped[str] = mapped_column(String(128), nullable=False, default="FAST")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BillingSubscription(Base):
    """user_id → Plan 연결 (활성 단일).

    Plan 전환 시 기존 ``status`` 를 ``cancelled`` 로 마킹하고 새 row 를 ``active``
    로 insert (감사 추적 보존). 한 사용자에 ``active`` 는 단 1 row 만 유지된다
    (`UNIQUE(user_id, status='active')` 는 partial index 가 필요해 application
    레벨에서 강제).
    """

    __tablename__ = "billing_subscriptions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("billing_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BillingUsageRecord(Base):
    """호출 단위 사용 기록 (감사·분석용).

    ``action`` 은 ``generate`` / ``review`` / ``fix`` / ``run`` / ``architecture``
    등 라우트 별 식별자. ``plan_code`` 는 호출 시점의 plan 을 스냅샷으로 저장
    (사후 plan 변경에도 청구 정합성 유지).
    """

    __tablename__ = "billing_usage_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False)

    tokens_estimated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class BillingMonthlyUserUsage(Base):
    """월별 사용자별 집계 (성능 위 — 매 호출마다 UsageRecord COUNT 회피).

    ``year_month`` 는 ``YYYY-MM`` 문자열. 매 호출마다 upsert 로 ``calls_count``
    증가. 일별 시계열이 필요하면 ``BillingUsageRecord`` 의 ``created_at`` 으로
    그룹화한다 (분석 라우트 ``GET /billing/usage/timeline``).
    """

    __tablename__ = "billing_monthly_user_usage"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    year_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    calls_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(18, 8), default=0, nullable=False)

    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "year_month", name="uq_billing_monthly_user_year_month"),
    )
