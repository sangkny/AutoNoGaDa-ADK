"""SVG Generator — 생성 · 검증 · 내보내기 (Phase 2 Week 1)."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.svg_generation import SvgGeneration
from schemas.svg import (
    SVGExportRequest,
    SVGExportResponse,
    SVGGenerateRequest,
    SVGGenerateResponse,
    SVGTypesResponse,
    SVGValidateRequest,
    SVGValidateResponse,
)
from services.svg_generator import SVG_TYPES, TEMPLATE_FILES, SVGGeneratorService

log = logging.getLogger("api.svg")

router = APIRouter()
_svc = SVGGeneratorService()


def _ontology_errors_to_dict(vr: Any) -> tuple[list[dict], list[dict]]:
    err_d: list[dict[str, Any]] = []
    warn_d: list[dict[str, Any]] = []
    for e in getattr(vr, "errors", []) or []:
        err_d.append(
            {
                "code": getattr(e, "code", ""),
                "message": getattr(e, "message", ""),
                "field": getattr(e, "field", "") or "",
            },
        )
    for w in getattr(vr, "warnings", []) or []:
        warn_d.append(
            {
                "code": getattr(w, "code", ""),
                "message": getattr(w, "message", ""),
                "field": getattr(w, "field", "") or "",
            },
        )
    return err_d, warn_d


@router.post(
    "/generate",
    response_model=SVGGenerateResponse,
    summary="LLM으로 SVG 생성 (Ontology SVG + Redis 캐시)",
)
async def svg_generate(
    req: SVGGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> SVGGenerateResponse:
    try:
        out = await _svc.generate(
            req.description,
            req.svg_type,
            req.style,
            use_cache=req.cache,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        log.exception("SVG 생성 실패")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)[:500],
        ) from e

    rec = SvgGeneration(
        id=str(uuid.uuid4()),
        description=req.description[:8000],
        svg_type=out.svg_type,
        svg_content=out.svg_content,
        cached=out.cached,
        latency_ms=out.latency_ms,
    )
    db.add(rec)
    await db.flush()

    return SVGGenerateResponse(
        svg_content=out.svg_content,
        svg_type=out.svg_type,
        ontology_passed=out.ontology_passed,
        cached=out.cached,
        latency_ms=round(out.latency_ms, 3),
        summary=out.ontology_summary,
    )


@router.post(
    "/validate",
    response_model=SVGValidateResponse,
    summary="SVG XML + OntologyValidator.for_svg() 검증",
)
async def svg_validate(req: SVGValidateRequest) -> SVGValidateResponse:
    if req.svg_type not in SVG_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"svg_type은 다음 중 하나여야 합니다: {list(SVG_TYPES)}",
        )
    vr = await _svc.validate_full(req.svg_content, req.svg_type)
    errs, warns = _ontology_errors_to_dict(vr)
    struct_ok, serrs = _svc.structural_check(req.svg_content)
    if not struct_ok:
        for m in serrs:
            errs.append({"code": "STRUCT", "message": m, "field": ""})
    valid = struct_ok and bool(vr.passed)
    return SVGValidateResponse(valid=valid, errors=errs, warnings=warns)


@router.get(
    "/types",
    response_model=SVGTypesResponse,
    summary="지원 svg_type 및 템플릿 파일 목록",
)
async def svg_types() -> SVGTypesResponse:
    tpl_meta = [{"name": n, "path": f"services/svg_templates/{n}"} for n in TEMPLATE_FILES]
    return SVGTypesResponse(svg_types=list(SVG_TYPES), templates=tpl_meta)


@router.post(
    "/export",
    response_model=SVGExportResponse,
    summary="svg | png(미구현) | react 컴포넌트 문자열",
)
async def svg_export(req: SVGExportRequest) -> SVGExportResponse:
    if req.format == "svg":
        return SVGExportResponse(
            format="svg",
            content=req.svg_content,
            mime="image/svg+xml",
        )
    if req.format == "png":
        return SVGExportResponse(
            format="png",
            content="",
            mime=None,
            note="PNG 변환은 서버에 cairosvg 미설치 — 클라이언트 렌더링 또는 SVG 다운로드 사용",
        )
    if req.format == "react":
        esc = json.dumps(req.svg_content)
        line = f"    <span dangerouslySetInnerHTML={{{{ __html: html }}}} />\n"
        tsx = (
            f"import React from 'react';\n\n"
            f"export function {req.component_name}(): JSX.Element {{\n"
            f"  const html = {esc};\n"
            f"  return (\n"
            f"{line}"
            f"  );\n"
            f"}}\n"
        )
        return SVGExportResponse(format="react", content=tsx, mime="text/typescript")
    raise HTTPException(status_code=400, detail="unknown format")
