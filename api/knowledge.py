"""지식베이스 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from database import get_db
from schemas.knowledge_cost import (
    KnowledgeSearchHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeStatsResponse,
)
from services.knowledge_agent import KnowledgeAgent

router = APIRouter()
_agent = KnowledgeAgent()


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    summary="유사 작업 검색 (코사인 유사도)",
)
async def knowledge_search(
    body: KnowledgeSearchRequest,
    db:  AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("developer", "admin")),
) -> KnowledgeSearchResponse:
    hits = await _agent.find_similar(db, body.query, top_k=body.top_k)
    return KnowledgeSearchResponse(
        hits=[
            KnowledgeSearchHit(
                id=h["id"],
                similarity=h["similarity"],
                task_text=h["task_text"],
                result_text=h["result_text"],
                language=h["language"],
            )
            for h in hits
        ],
    )


@router.get(
    "/stats",
    response_model=KnowledgeStatsResponse,
    summary="지식 통계 (온톨로지 통과율)",
)
async def knowledge_stats(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("developer", "admin")),
) -> KnowledgeStatsResponse:
    s = await _agent.stats(db)
    return KnowledgeStatsResponse(**s)


@router.get(
    "/suggest",
    summary="재사용 제안 (0.95↑ 재사용 · 0.8~0.95 참고)",
)
async def knowledge_suggest(
    query: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("developer", "admin")),
) -> dict:
    return await _agent.get_reuse_suggestion(db, query)
