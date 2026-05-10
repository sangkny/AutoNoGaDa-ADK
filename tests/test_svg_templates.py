"""Phase 2 W2 — 물리 템플릿 20개가 OntologyValidator.for_svg()에 통과하는지 검증."""
from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from ontology.validator import OntologyValidator

from services.svg_generator import TEMPLATE_FILES, SVGGeneratorService


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "services" / "svg_templates"


def _svg_type_and_flags(filename: str) -> tuple[str, dict[str, bool]]:
    if filename.startswith("medical_"):
        return "medical_report", {"no_pii": True}
    if filename.startswith("business_"):
        return "business_process", {}
    if filename.startswith("sequence_"):
        return "sequence", {}
    if filename.startswith("er_diagram_"):
        return "er_diagram", {}
    if filename.startswith("architecture_"):
        return "architecture", {}
    if filename.startswith("flowchart_"):
        return "flowchart", {}
    return "flowchart", {}


class TestSVGTemplatesOntology:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("filename", list(TEMPLATE_FILES))
    async def test_template_file_passes_for_svg(self, filename: str) -> None:
        path = _templates_dir() / filename
        assert path.is_file(), f"missing {filename}"
        body = path.read_text(encoding="utf-8")
        assert "<svg" in body.lower() and "viewbox=" in body.lower().replace(" ", "")
        assert "<script" not in body.lower()

        svg_type, flags = _svg_type_and_flags(filename)
        payload: dict = {"svg_content": body, "svg_type": svg_type, **flags}
        r = await OntologyValidator.for_svg().validate(payload)
        assert r.passed, f"{filename}: {[e.code + ':' + e.message for e in r.errors]}"

    def test_template_count_matches_disk(self) -> None:
        assert len(TEMPLATE_FILES) == 20
        for name in TEMPLATE_FILES:
            assert (_templates_dir() / name).is_file()


class TestSVGTemplatesAPI:
    @pytest.mark.asyncio
    async def test_types_lists_twenty_templates(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/svg/types")
        assert r.status_code == 200
        tpls = r.json().get("templates") or []
        assert len(tpls) == 20
        names = {t.get("name") for t in tpls if isinstance(t, dict)}
        assert names == set(TEMPLATE_FILES)
