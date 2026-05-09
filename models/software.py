"""SOFTWARE 도메인 ORM — 코드 작업·리뷰·수정 이력."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class TaskStatusEnum(str, enum.Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"


class CodeTask(Base):
    """
    사용자/에이전트가 요청한 코드 작업 단위.
    """
    __tablename__ = "software_code_tasks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), default="python")

    status: Mapped[TaskStatusEnum] = mapped_column(
        SAEnum(TaskStatusEnum), default=TaskStatusEnum.PENDING,
    )
    output_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    ontology_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    reviews: Mapped[list["TaskReview"]] = relationship(
        back_populates="task", cascade="all, delete-orphan",
    )
    fixes: Mapped[list["TaskFix"]] = relationship(
        back_populates="task", cascade="all, delete-orphan",
    )


class TaskReview(Base):
    """ReviewerAgent + OntologyValidator 단계 요약."""
    __tablename__ = "software_task_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("software_code_tasks.id", ondelete="CASCADE"),
    )
    passed: Mapped[bool] = mapped_column(default=False)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(120), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    task: Mapped["CodeTask"] = relationship(back_populates="reviews")


class TaskFix(Base):
    """Fixer 반복 시 생성된 패치 요약."""
    __tablename__ = "software_task_fixes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("software_code_tasks.id", ondelete="CASCADE"),
    )
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    patch_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    task: Mapped["CodeTask"] = relationship(back_populates="fixes")
