"""에이전트 파이프라인 실행."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.software import (
    PipelineRunRequest,
    PipelineRunInlineRequest,
    PipelineRunResponse,
)
from services.pipeline_runner import PipelineRunner

router = APIRouter()
_runner = PipelineRunner()


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
