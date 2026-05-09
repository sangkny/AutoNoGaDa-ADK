"""Week 5 5-1-2: POST /api/v1/architecture/decide (DEBATE mock + DB Lore)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from agents.base import AgentType, LoreEntry
from agents.orchestrator import OrchestratorResult, OrchestraStrategy
from ontology.base import OntologyDomain

from database import async_session_maker
from models.software import SoftwareLoreDecision
from services.architecture_decider import parse_architecture_answer


def _lore_stub() -> list[LoreEntry]:
    return [
        LoreEntry(
            task_id="stub",
            agent=AgentType.PLANNER,
            action="plan",
            input_hash="aa",
            decision="요구 정리",
            model_used="fast",
            passed=True,
            iteration=0,
        ),
    ]


def _orch_result(rec_line: str, rationale: str) -> OrchestratorResult:
    body = (
        f"RECOMMENDATION:\n{rec_line}\n\nRATIONALE:\n{rationale}\n"
    )
    return OrchestratorResult(
        task_id="orch-stub",
        strategy=OrchestraStrategy.DEBATE,
        domain=OntologyDomain.SOFTWARE,
        passed=True,
        output=body,
        iterations=1,
        lore=_lore_stub(),
    )


@pytest.mark.asyncio
async def test_parse_architecture_answer_blocks() -> None:
    text = (
        "RECOMMENDATION:\n"
        "REST API\n\n"
        "RATIONALE:\n"
        "단순합니다. 캐싱이 좋습니다.\n"
    )
    rec, rat = parse_architecture_answer(text)
    assert "REST" in rec
    assert len(rat) > 5


@pytest.mark.asyncio
async def test_architecture_rest_vs_graphql_mocked(client: AsyncClient) -> None:
    orch = _orch_result(
        "REST API",
        "표준 HTTP 캐시·프록시와 잘 맞고 팀 온보딩 비용이 낮습니다.",
    )
    with patch(
        "services.architecture_decider.Orchestrator.execute",
        new_callable=AsyncMock,
        return_value=orch,
    ):
        r = await client.post(
            "/api/v1/architecture/decide",
            json={
                "requirement": "모바일 앱 백엔드를 설계한다. REST vs GraphQL 선택.",
            },
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("orchestrator_passed") is True
    assert "REST" in (j.get("recommendation") or "")
    assert j.get("strategy") == "debate"
    assert j.get("debate_note")

    did = j["decision_id"]
    async with async_session_maker() as session:
        row = await session.get(SoftwareLoreDecision, did)
        assert row is not None
        assert row.requirement
        assert row.lore_json is not None
        rows = json.loads(row.lore_json)
        assert isinstance(rows, list)
        assert len(rows) >= 1


@pytest.mark.asyncio
async def test_architecture_postgres_vs_mongodb_mocked(client: AsyncClient) -> None:
    orch = _orch_result(
        "PostgreSQL",
        "트랜잭션과 스키마 무결성이 중요한 도메인에는 RDB가 유리합니다.",
    )
    with patch(
        "services.architecture_decider.Orchestrator.execute",
        new_callable=AsyncMock,
        return_value=orch,
    ):
        r = await client.post(
            "/api/v1/architecture/decide",
            json={
                "requirement": "주문·결제 데이터 저장. PostgreSQL vs MongoDB 선택.",
            },
        )
    assert r.status_code == 200, r.text
    j = r.json()
    assert "PostgreSQL" in (j.get("recommendation") or "") or "postgres" in (
        j.get("recommendation") or ""
    ).lower()


@pytest.mark.asyncio
async def test_architecture_sync_vs_async_mocked(client: AsyncClient) -> None:
    orch = _orch_result(
        "비동기 I/O (async)",
        "다수 외부 호출이 있으면 이벤트 루프로 지연을 줄이는 편이 유리합니다.",
    )
    with patch(
        "services.architecture_decider.Orchestrator.execute",
        new_callable=AsyncMock,
        return_value=orch,
    ):
        r = await client.post(
            "/api/v1/architecture/decide",
            json={
                "requirement": "다수의 외부 API를 호출하는 서비스. 동기 vs 비동기 처리 선택.",
            },
        )
    assert r.status_code == 200, r.text
    j = r.json()
    rec = (j.get("recommendation") or "").lower()
    rat = (j.get("rationale") or "").lower()
    assert "비동기" in rec or "async" in rec or "비동기" in rat or "async" in rat
