"""에이전트 파이프라인 — 생성 · 리뷰 · 수정 · 실행."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import require_role
from database import get_db
from schemas.software import (
    PipelineFixRequest,
    PipelineFixResponse,
    PipelineGenerateRequest,
    PipelineLanguagesResponse,
    PipelineReviewRequest,
    PipelineReviewResponse,
    PipelineRunRequest,
    PipelineRunInlineRequest,
    PipelineRunResponse,
    PipelineValidateRequest,
    PipelineValidateResponse,
)
from services.pipeline_runner import PipelineRunner
from services.polyglot_executor import (
    PolyglotExecutor,
    SUPPORTED_LANGUAGES,
    list_supported_languages,
    normalize_language,
)

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
    _: dict = Depends(require_role("developer", "admin")),
) -> PipelineRunResponse:
    try:
        out = await _runner.generate(
            db,
            req.task,
            req.language,
            auto_commit=auto_commit,
            framework=req.framework,
        )
        return PipelineRunResponse(**out)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e


@router.get(
    "/languages",
    response_model=PipelineLanguagesResponse,
    summary="지원 언어·프레임워크·예시",
)
async def pipeline_languages() -> PipelineLanguagesResponse:
    d = list_supported_languages()
    return PipelineLanguagesResponse(**d)


@router.post(
    "/validate",
    response_model=PipelineValidateResponse,
    summary="폴리glot 문법 검증 + POLYGLOT Ontology(선택)",
)
async def pipeline_validate(req: PipelineValidateRequest) -> PipelineValidateResponse:
    from config import get_settings

    settings = get_settings()
    pe = PolyglotExecutor(settings.code_sandbox_url or None)
    norm = normalize_language(req.language)
    if norm not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported language: {req.language}",
        )
    syn = await pe.validate_syntax(req.code, norm)
    ont_pass: bool | None = None
    ont_sum = ""
    if req.ontology:
        ov = await pe.validate_polyglot_ontology(req.code, norm)
        ont_pass = bool(ov.passed)
        ont_sum = ov.summary
    valid = syn.valid and (ont_pass is not False)
    if req.ontology and ont_pass is False:
        valid = False
    return PipelineValidateResponse(
        valid=valid,
        syntax_errors=syn.syntax_errors,
        style_warnings=syn.style_warnings,
        ontology_passed=ont_pass,
        ontology_summary=ont_sum,
    )


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
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
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
        out = await _runner.run_inline(
            db,
            req.description,
            req.language,
            framework=req.framework,
        )
        return PipelineRunResponse(**out)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e
