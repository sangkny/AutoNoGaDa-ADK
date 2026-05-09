"""WEEK4 4-3-2: /pipeline/generate · /review · /fix (Orchestrator·Agent 는 mock)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from agents.base import AgentResult, AgentStatus, AgentType
from agents.orchestrator import OrchestratorResult, OrchestraStrategy
from agents.reviewer import ReviewResult
from ontology.base import OntologyDomain


ADD_SNIPPET = """def add(a, b):
    return a + b
"""


@pytest.mark.asyncio
async def test_pipeline_generate_add_mocked(client: AsyncClient) -> None:
    """POST /api/v1/pipeline/generate — add(a,b) 생성 (Orchestrator.execute stub)."""
    orch_res = OrchestratorResult(
        task_id="stub",
        strategy=OrchestraStrategy.PIPELINE,
        domain=OntologyDomain.SOFTWARE,
        passed=True,
        output=ADD_SNIPPET,
        iterations=1,
    )
    with patch(
        "services.pipeline_runner.Orchestrator.execute",
        new_callable=AsyncMock,
        return_value=orch_res,
    ):
        r = await client.post(
            "/api/v1/pipeline/generate",
            json={
                "task": "두 정수 a,b를 더하는 add(a, b) 함수를 작성하세요.",
                "language": "python",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "def add" in (body.get("output_code") or "")
    assert body.get("quality_report") is not None
    assert "ontology_errors" in (body.get("quality_report") or {})


@pytest.mark.asyncio
async def test_pipeline_review_mocked(client: AsyncClient) -> None:
    """POST /api/v1/pipeline/review — ReviewerAgent 결과 mock."""
    ar = AgentResult(
        agent_type=AgentType.REVIEWER,
        task_id="t1",
        status=AgentStatus.COMPLETED,
        output=ReviewResult(
            passed=True,
            feedback="타입 힌트 추가 권장",
            llm_review="docstring 권장",
        ),
    )
    with patch("services.pipeline_runner.ReviewerAgent") as mock_rev:
        mock_rev.return_value.run = AsyncMock(return_value=ar)
        r = await client.post(
            "/api/v1/pipeline/review",
            json={"code": ADD_SNIPPET, "language": "python"},
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("passed") is True
    assert "feedback" in j


@pytest.mark.asyncio
async def test_pipeline_fix_mocked(client: AsyncClient) -> None:
    """POST /api/v1/pipeline/fix — FixerAgent 결과 mock."""
    fixed = ADD_SNIPPET + "\n# fixed\n"
    ar = AgentResult(
        agent_type=AgentType.FIXER,
        task_id="t2",
        status=AgentStatus.COMPLETED,
        output=fixed,
    )
    with patch("services.pipeline_runner.FixerAgent") as mock_fix:
        mock_fix.return_value.run = AsyncMock(return_value=ar)
        r = await client.post(
            "/api/v1/pipeline/fix",
            json={
                "code": "def add(a,b): return",
                "error_message": "return 값 없음",
            },
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("error") is None
    assert "def add" in (j.get("fixed_code") or "")
