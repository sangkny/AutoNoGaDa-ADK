"""비용 라우팅 요약·추천."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from database import get_db
from schemas.knowledge_cost import (
    CostBudgetRequest,
    CostBudgetResponse,
    CostRecommendationRequest,
    CostRecommendationResponse,
    CostSummaryResponse,
)
from services.cost_optimizer import CostOptimizerService

router = APIRouter()
_svc = CostOptimizerService()


@router.get(
    "/summary",
    response_model=CostSummaryResponse,
    summary="모델 사용 로그·예산 요약",
)
async def cost_summary(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("developer", "admin")),
) -> CostSummaryResponse:
    s = await _svc.summary(db)
    return CostSummaryResponse(**s)


@router.post(
    "/recommendation",
    response_model=CostRecommendationResponse,
    summary="복잡도별 모델 선택 + for_cost() 검증",
)
async def cost_recommend(
    body: CostRecommendationRequest,
    _: dict = Depends(require_role("developer", "admin")),
) -> CostRecommendationResponse:
    sel = await _svc.select_model(body.task, budget_usd=body.budget_usd)
    return CostRecommendationResponse(
        complexity=sel.complexity,
        selected_model=sel.selected_model,
        estimated_tokens=sel.estimated_tokens,
        budget_usd=sel.budget_usd,
        ontology_passed=sel.ontology_passed,
        ontology_summary=sel.ontology_summary,
    )


@router.post(
    "/budget",
    response_model=CostBudgetResponse,
    summary="당월 예산 설정",
)
async def cost_set_budget(
    body: CostBudgetRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
) -> CostBudgetResponse:
    out = await _svc.set_monthly_budget(db, body.budget_usd)
    return CostBudgetResponse(**out)
