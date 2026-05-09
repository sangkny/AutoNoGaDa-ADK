"""Pydantic 스키마 — 코드 작업·파이프라인."""
from datetime import datetime

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
