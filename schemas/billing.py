"""SaaS 비즈니스 트랙 (Phase 2) — Pydantic 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlanOut(BaseModel):
    """Plan 카탈로그 응답."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    price_usd_per_month: float
    monthly_call_quota: int | None
    allowed_models: list[str]
    description: str | None = None
    is_active: bool = True


class PlanListResponse(BaseModel):
    plans: list[PlanOut]
    default_code: str = "free"


class SubscriptionOut(BaseModel):
    """현재 활성 구독 정보."""

    model_config = ConfigDict(from_attributes=True)

    plan_code: str
    plan_name: str
    monthly_call_quota: int | None
    allowed_models: list[str]
    started_at: datetime
    current_period_end: datetime | None = None


class UsageSnapshot(BaseModel):
    """월 단위 사용량 스냅샷."""

    year_month: str = Field(..., description="YYYY-MM")
    calls_used: int = 0
    calls_limit: int | None = None
    calls_remaining: int | None = None
    quota_pct: float = 0.0
    tokens_total: int = 0
    cost_usd: float = 0.0


class MeResponse(BaseModel):
    user_id: str
    role: str
    subscription: SubscriptionOut
    usage: UsageSnapshot


class SubscribeRequest(BaseModel):
    """admin 전용 — 사용자에게 plan 부여."""

    user_id: str = Field(..., min_length=1, max_length=128)
    plan_code: str = Field(..., pattern=r"^(free|dev|team|ent)$")


class SubscribeResponse(BaseModel):
    user_id: str
    plan_code: str
    previous_plan_code: str | None = None
    started_at: datetime


class UsageTimelinePoint(BaseModel):
    date: str
    calls: int
    tokens: int


class UsageTimelineResponse(BaseModel):
    user_id: str
    days: int
    points: list[UsageTimelinePoint]


class UsageHistoryEntry(BaseModel):
    year_month: str
    calls_count: int
    tokens_total: int
    cost_usd: float


class UsageHistoryResponse(BaseModel):
    user_id: str
    history: list[UsageHistoryEntry]


class PlanDistributionEntry(BaseModel):
    plan_code: str
    plan_name: str
    active_subscribers: int
    price_usd_per_month: float
    monthly_revenue_usd: float


class AdminStatsResponse(BaseModel):
    year_month: str
    total_active_subscribers: int
    total_monthly_revenue_usd: float
    total_calls_this_month: int
    total_tokens_this_month: int
    plan_distribution: list[PlanDistributionEntry]
