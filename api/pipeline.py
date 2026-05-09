"""에이전트 파이프라인 — 생성 · 리뷰 · 수정 · 실행."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.software import (
    PipelineFixRequest,
    PipelineFixResponse,
    PipelineGenerateRequest,
    PipelineReviewRequest,
    PipelineReviewResponse,
    PipelineRunRequest,
    PipelineRunInlineRequest,
    PipelineRunResponse,
)
from services.pipeline_runner import PipelineRunner

router = APIRouter()
_runner = PipelineRunner()


# ── WEEK4 4-3-2: generate / review / fix ───────────────────────────

@router.post(
    "/generate",
    response_model=PipelineRunResponse,
    summary="코드 생성 (PIPELINE + SOFTWARE Ontology)",
)
async def pipeline_generate(
    req: PipelineGenerateRequest,
    db:  AsyncSession = Depends(get_db),
    auto_commit: bool = Query(
        False,
        description="True 이면 생성 코드를 generated/snippets 에 쓰고 git commit",
    ),
) -> PipelineRunResponse:
    try:
        out = await _runner.generate(
            db, req.task, req.language, auto_commit=auto_commit,
        )
        return PipelineRunResponse(**out)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e


@router.post(
    "/review",
    response_model=PipelineReviewResponse,
    summary="코드 리뷰 (ReviewerAgent HEAVY)",
)
async def pipeline_review(req: PipelineReviewRequest) -> PipelineReviewResponse:
    try:
        out = await _runner.review_code(req.code, req.language, req.context)
        return PipelineReviewResponse(**out)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e


@router.post(
    "/fix",
    response_model=PipelineFixResponse,
    summary="코드 자동 수정 (FixerAgent)",
)
async def pipeline_fix(req: PipelineFixRequest) -> PipelineFixResponse:
    try:
        out = await _runner.fix_code(req.code, req.error_message, req.context)
        return PipelineFixResponse(**out)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e


# ── 기존 실행 경로 ─────────────────────────────────────────────────

@router.post(
    "/run",
    response_model=PipelineRunResponse,
    summary="등록된 작업으로 PIPELINE 실행",
)
async def run_pipeline(
    req: PipelineRunRequest,
    db:  AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    task = await _runner.load_task(db, req.task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task_id 없음",
        )
    try:
        out = await _runner.run_task(db, task)
        return PipelineRunResponse(**out)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e


@router.post(
    "/run-inline",
    response_model=PipelineRunResponse,
    summary="설명만으로 PIPELINE 실행(데모)",
)
async def run_inline(
    req: PipelineRunInlineRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelineRunResponse:
    try:
        out = await _runner.run_inline(db, req.description, req.language)
        return PipelineRunResponse(**out)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e
