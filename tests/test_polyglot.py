"""Phase 2 W4 — PolyglotExecutor·파이프라인 언어 확장."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from services.polyglot_executor import (
    PolyglotExecutor,
    SUPPORTED_LANGUAGES,
    extract_fenced_code,
    infer_function_name,
    normalize_language,
)


def test_normalize_language() -> None:
    assert normalize_language("ts") == "typescript"
    assert normalize_language("RS") == "rust"
    assert normalize_language("Python3") == "python"


def test_extract_fenced_typescript() -> None:
    raw = "설명\n```typescript\nfunction add(a: number): number { return a + 1; }\n```"
    c = extract_fenced_code(raw, "typescript")
    assert "function add" in c


@pytest.mark.asyncio
async def test_polyglot_typescript_ontology_rejects_any() -> None:
    pe = PolyglotExecutor(None)
    bad = "function bad(x: any): any { return x; }"
    vr = await pe.validate_polyglot_ontology(bad, "typescript")
    assert vr.passed is False


@pytest.mark.asyncio
async def test_polyglot_rust_ontology_unwrap_cap() -> None:
    pe = PolyglotExecutor(None)
    code = "".join(
        [
            "fn demo() -> i32 {\n",
            "\n".join(f"  let _ = Some({i}).unwrap();" for i in range(5)),
            "\n  0\n}",
        ]
    )
    vr = await pe.validate_polyglot_ontology(code, "rust")
    assert vr.passed is False


@pytest.mark.asyncio
async def test_pipeline_languages_endpoint(client: AsyncClient) -> None:
    r = await client.get("/api/v1/pipeline/languages")
    assert r.status_code == 200
    j = r.json()
    assert set(j["languages"]) == SUPPORTED_LANGUAGES
    assert "typescript" in j["sandbox_required"]


@pytest.mark.asyncio
async def test_pipeline_validate_python(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/pipeline/validate",
        json={
            "code": "def foo():\n    return 42\n",
            "language": "python",
            "ontology": True,
        },
    )
    assert r.status_code == 200
    j = r.json()
    assert j["valid"] is True
    assert j["syntax_errors"] == []


@pytest.mark.asyncio
async def test_pipeline_validate_python_syntax_error(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/pipeline/validate",
        json={"code": "def broken(\n", "language": "python", "ontology": False},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["valid"] is False
    assert j["syntax_errors"]


def test_infer_function_name_ts() -> None:
    src = (
        "export function stringLengthSum(a: string, b: string): number { "
        "return a.length + b.length; }"
    )
    assert infer_function_name(src, "typescript") == "stringLengthSum"
