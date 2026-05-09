"""Pydantic 스키마 — 코드 작업·파이프라인."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    language: str = Field(default="python", max_length=32)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: str
    title: str
    description: str
    language: str
    status: str
    output_code: str | None = None
    ontology_passed: bool | None = None
    created_at: datetime


class PipelineRunRequest(BaseModel):
    """기존 작업 기준 파이프라인 실행."""

    task_id: str = Field(description="software_code_tasks.id")


class PipelineRunInlineRequest(BaseModel):
    """작업 없이 설명만으로 파이프라인 실행(데모)."""

    description: str
    language: str = Field(default="python")


class PipelineRunResponse(BaseModel):
    task_id: str
    status: str
    output_code: str | None = None
    ontology_passed: bool | None = None
    iterations: int = 0
    summary: str = ""
    quality_report: dict[str, Any] | None = None
    git: dict[str, Any] | None = Field(
        default=None,
        description="auto_commit 시 커밋 메타·PR 초안 (Week 5)",
    )


class PipelineGenerateRequest(BaseModel):
    """POST /pipeline/generate (WEEK4_PROMPTS 4-3-2)."""

    task: str = Field(description="생성할 함수/코드에 대한 자연어 설명")
    language: str = Field(default="python", max_length=32)


class PipelineReviewRequest(BaseModel):
    code: str = Field(min_length=1, description="리뷰할 소스 코드")
    language: str = Field(default="python")
    context: str | None = Field(default=None, description="추가 리뷰 맥락")


class PipelineReviewResponse(BaseModel):
    passed: bool
    feedback: str = ""
    llm_review: str = ""
    ontology_passed: bool | None = None
    ontology_summary: str = ""


class PipelineFixRequest(BaseModel):
    code: str = Field(min_length=1)
    error_message: str = Field(min_length=1, description="오류 메시지 또는 수정 지시")
    context: str | None = Field(default=None)


class PipelineFixResponse(BaseModel):
    fixed_code: str | None = None
    error: str | None = None


class ArchitectureDecideRequest(BaseModel):
    """POST /architecture/decide — DEBATE 로 아키텍처 선택."""

    requirement: str = Field(
        min_length=3,
        max_length=12_000,
        description="트레이드오프·요구 설명",
    )


class ArchitectureDecideResponse(BaseModel):
    decision_id: str
    orchestrator_task_id: str
    orchestrator_passed: bool
    recommendation: str
    rationale: str = ""
    strategy: str = "debate"
    domain: str = "software"
    debate_note: str = ""
    error: str | None = None
    lore_preview: list[dict[str, Any]] = Field(default_factory=list)
