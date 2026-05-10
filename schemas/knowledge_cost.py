"""Knowledge / Cost API 스키마."""
from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchHit(BaseModel):
    id:           str
    similarity:   float
    task_text:    str
    result_text:  str
    language:     str


class KnowledgeSearchResponse(BaseModel):
    hits: list[KnowledgeSearchHit]


class KnowledgeStatsResponse(BaseModel):
    indexed_rows:           int
    ontology_passed_rows:   int
    ontology_pass_rate_pct: float


class CostSummaryResponse(BaseModel):
    logged_calls:      int
    ontology_passed:   int
    ontology_rate_pct: float
    year_month:        str
    budget_usd:        float | None
    spent_usd:         float | None
    spent_pct:         float
    budget_alert:      str


class CostRecommendationRequest(BaseModel):
    task:       str = Field(min_length=5, max_length=4000)
    budget_usd: float | None = Field(default=None, ge=0)


class CostRecommendationResponse(BaseModel):
    complexity:           str
    selected_model:       str
    estimated_tokens:    int
    budget_usd:         float
    ontology_passed:     bool
    ontology_summary:    str


class CostBudgetRequest(BaseModel):
    budget_usd: float = Field(ge=0)


class CostBudgetResponse(BaseModel):
    year_month: str
    budget_usd: float
