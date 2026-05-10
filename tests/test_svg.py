"""Phase 2 W1 — SVG Generator · API · 캐시(선택) · Alembic 모델."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models.svg_generation import SvgGeneration
from services.svg_generator import (
    SVG_TYPES,
    TEMPLATE_FILES,
    SVGGeneratorService,
)
from llm.base import LLMResponse, LLMProvider, ModelRole


_MIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80" width="120" height="80">'
    '<rect fill="#e2e8f0" width="120" height="80" stroke="#64748b"/>'
    "</svg>"
)


@pytest.fixture
def mock_llm_svg() -> AsyncMock:
    return AsyncMock(
        return_value=LLMResponse(
            content=_MIN_SVG,
            model_used="test-local",
            provider=LLMProvider.LOCAL,
            role=ModelRole.FAST,
        ),
    )


class TestSVGGenerator:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("svg_type", list(SVG_TYPES))
    async def test_generate_types(self, svg_type: str, mock_llm_svg: AsyncMock) -> None:
        with patch("services.svg_generator.LLMClient.chat", mock_llm_svg):
            svc = SVGGeneratorService()
            out = await svc.generate(
                f"테스트 설명 — {svg_type} 용 다이어그램",
                svg_type,
                style=None,
                use_cache=False,
            )
        assert out.svg_type == svg_type
        assert "<svg" in out.svg_content.lower()
        assert out.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_structural_validate(self) -> None:
        svc = SVGGeneratorService()
        ok, errs = svc.structural_check(_MIN_SVG)
        assert ok is True
        assert errs == []

    @pytest.mark.asyncio
    async def test_ontology_validate_full(self) -> None:
        svc = SVGGeneratorService()
        vr = await svc.validate_full(_MIN_SVG, "flowchart")
        assert vr.passed is True


class TestSVGValidation:
    """무효/경계 SVG — 구조 검사 및 API validate."""

    @pytest.mark.asyncio
    async def test_structural_invalid_xml(self) -> None:
        svc = SVGGeneratorService()
        ok, errs = svc.structural_check("not xml at all")
        assert ok is False

    @pytest.mark.asyncio
    async def test_validate_endpoint_xss(self, client: AsyncClient) -> None:
        bad = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><script>x</script></svg>"
        r = await client.post(
            "/api/v1/svg/validate",
            json={"svg_content": bad, "svg_type": "flowchart"},
        )
        assert r.status_code == 200
        assert r.json().get("valid") is False


class TestSVGTemplateFiles:
    def test_twenty_template_files_exist(self) -> None:
        svc = SVGGeneratorService()
        assert len(TEMPLATE_FILES) == 20
        for name in TEMPLATE_FILES:
            p = svc._template_path("flowchart", None).parent / name
            assert p.is_file(), name


class TestSVGCache:
    @pytest.mark.asyncio
    async def test_cache_key_stable(self) -> None:
        k1 = SVGGeneratorService._cache_key("a", "flowchart", {"x": 1})
        k2 = SVGGeneratorService._cache_key("a", "flowchart", {"x": 1})
        assert k1 == k2


class TestSVGAPI:
    @pytest.mark.asyncio
    async def test_types_endpoint(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/svg/types")
        assert r.status_code == 200
        j = r.json()
        assert "svg_types" in j and len(j["svg_types"]) == len(SVG_TYPES)
        assert "templates" in j

    @pytest.mark.asyncio
    async def test_validate_endpoint(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/svg/validate",
            json={"svg_content": _MIN_SVG, "svg_type": "architecture"},
        )
        assert r.status_code == 200
        assert r.json().get("valid") is True

    @pytest.mark.asyncio
    async def test_export_react(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/svg/export",
            json={"svg_content": _MIN_SVG, "format": "react", "component_name": "Fig"},
        )
        assert r.status_code == 200
        assert "dangerouslySetInnerHTML" in r.json().get("content", "")

    @pytest.mark.asyncio
    async def test_generate_persists_row(
        self,
        client: AsyncClient,
        mock_llm_svg: AsyncMock,
    ) -> None:
        with patch("services.svg_generator.LLMClient.chat", mock_llm_svg):
            r = await client.post(
                "/api/v1/svg/generate",
                json={
                    "description": "간단한 3계층 API 서버 아키텍처를 보여주는 도식",
                    "svg_type": "architecture",
                    "style": {},
                    "cache": False,
                },
            )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("svg_content")
        assert j.get("ontology_passed") is True

        async with async_session_maker() as session:
            res = await session.execute(select(SvgGeneration).limit(5))
            rows = res.scalars().all()
        assert any("3계층" in row.description or "API" in row.description for row in rows)
