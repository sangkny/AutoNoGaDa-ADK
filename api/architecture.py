"""아키텍처 결정 — Orchestrator DEBATE (FAST ↔ HEAVY)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from schemas.software import ArchitectureDecideRequest, ArchitectureDecideResponse
from services.architecture_decider import ArchitectureDecider

router = APIRouter()
_decider = ArchitectureDecider()


@router.post(
    "/decide",
    response_model=ArchitectureDecideResponse,
    summary="아키텍처 결정 (DEBATE 전략 + Lore 저장)",
)
async def architecture_decide(
    req: ArchitectureDecideRequest,
    db:  AsyncSession = Depends(get_db),
) -> ArchitectureDecideResponse:
    try:
        payload = await _decider.decide(db, req.requirement)
        return ArchitectureDecideResponse(**payload)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e
