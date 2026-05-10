"""SVG 생성 이력 (Phase 2 Week 1)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class SvgGeneration(Base):
    __tablename__ = "svg_generations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    svg_type: Mapped[str] = mapped_column(String(64), nullable=False)
    svg_content: Mapped[str] = mapped_column(Text, nullable=False)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
