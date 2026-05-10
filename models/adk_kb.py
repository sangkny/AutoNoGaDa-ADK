"""Phase 2 — 지식베이스·비용 추적 테이블."""
from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


EMBED_DIM = 768


class AdkCodeExecution(Base):
    """파이프라인 실행 이력 — 임베딩 + 온톨로지 결과."""

    __tablename__ = "adk_code_executions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("software_code_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="python")
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ontology_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class AdkFailurePattern(Base):
    """실패 패턴 집계."""

    __tablename__ = "adk_failure_patterns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    signature: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sample_task: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class ModelUsageLog(Base):
    """모델·복잡도 라우팅 감사 로그."""

    __tablename__ = "adk_model_usage_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    complexity: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_model: Mapped[str] = mapped_column(String(128), nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_cost_usd: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    ontology_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class MonthlyBudget(Base):
    """월별 예산(단일 활성 행 또는 year_month별)."""

    __tablename__ = "adk_monthly_budget"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    year_month: Mapped[str] = mapped_column(String(7), nullable=False, unique=True, index=True)
    budget_usd: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    spent_usd: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
