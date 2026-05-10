"""SVG Generator API 스키마."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SVGGenerateRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=8000)
    svg_type: str = Field(
        ...,
        description=(
            "flowchart | architecture | sequence | er_diagram | "
            "medical_report | business_process"
        ),
    )
    style: dict[str, Any] | None = Field(
        default=None,
        description="예: variant=microservice|decision, theme=dark",
    )
    cache: bool = Field(default=True, description="Redis 캐시 사용(7일 TTL)")


class SVGGenerateResponse(BaseModel):
    svg_content: str
    svg_type: str
    ontology_passed: bool
    cached: bool
    latency_ms: float
    summary: str | None = None


class SVGValidateRequest(BaseModel):
    svg_content: str = Field(..., min_length=1)
    svg_type: str | None = Field(
        default="flowchart",
        description="Ontology 검증 시 사용 (medical_report → no_pii 등)",
    )


class SVGValidateResponse(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class SVGTypesResponse(BaseModel):
    svg_types: list[str]
    templates: list[dict[str, str]]


ExportFormat = Literal["svg", "png", "react"]


class SVGExportRequest(BaseModel):
    svg_content: str = Field(..., min_length=1)
    format: ExportFormat = "svg"
    component_name: str = Field(default="GeneratedSvg", pattern=r"^[A-Za-z][A-Za-z0-9_]*$")


class SVGExportResponse(BaseModel):
    format: str
    content: str
    mime: str | None = None
    note: str | None = None
