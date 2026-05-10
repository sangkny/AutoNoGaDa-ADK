"""Phase 2 W3 — 파이프라인 모니터링 API·WebSocket·대시보드."""
from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient

from main import app
from services.pipeline_monitor import PipelineMonitor, reset_pipeline_monitor_for_tests


@pytest.fixture(autouse=True)
def _memory_monitor() -> None:
    reset_pipeline_monitor_for_tests(PipelineMonitor(None))
    yield
    reset_pipeline_monitor_for_tests(None)


@pytest.mark.asyncio
async def test_monitor_status_track_and_get(client: AsyncClient) -> None:
    from services.pipeline_monitor import get_pipeline_monitor

    mon = get_pipeline_monitor()
    await mon.track("tid-001", "plan", "Planner", "running", {"k": 1})

    r = await client.get("/api/v1/monitor/tid-001")
    assert r.status_code == 200
    j = r.json()
    assert j["task_id"] == "tid-001"
    assert j["phase"] == "plan"
    assert j["agent"] == "Planner"


@pytest.mark.asyncio
async def test_monitor_status_404_unknown(client: AsyncClient) -> None:
    r = await client.get("/api/v1/monitor/does-not-exist-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_monitor_active_and_system_metrics(client: AsyncClient) -> None:
    from services.pipeline_monitor import get_pipeline_monitor

    mon = get_pipeline_monitor()
    await mon.track("run-a", "generate", "Generator", "running", {})

    r = await client.get("/api/v1/monitor/active")
    assert r.status_code == 200
    assert r.json()["count"] >= 1

    r2 = await client.get("/api/v1/monitor/metrics")
    assert r2.status_code == 200
    assert "system" in r2.json()


@pytest.mark.asyncio
async def test_dashboard_after_completion(client: AsyncClient) -> None:
    from services.pipeline_monitor import get_pipeline_monitor

    mon = get_pipeline_monitor()
    await mon.record_completion(
        "tid-done",
        success=True,
        latency_ms=250.0,
        iterations=2,
        ontology_passed=True,
        rough_char_count=400,
        model_hint="gemma-4-e4b",
    )

    r = await client.get("/api/v1/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert "today" in d and "active_pipelines" in d
    assert d["today"]["total_runs"] >= 1
    assert "model_usage" in d
    assert d["model_usage"].get("gemma-4-e4b", 0) >= 1
    assert len(d["recent_runs"]) >= 1


@pytest.mark.asyncio
async def test_task_metrics_endpoint(client: AsyncClient) -> None:
    from services.pipeline_monitor import get_pipeline_monitor

    mon = get_pipeline_monitor()
    await mon.record_completion(
        "tid-m",
        success=True,
        latency_ms=80.0,
        iterations=1,
        ontology_passed=True,
        rough_char_count=100,
    )

    r = await client.get("/api/v1/monitor/tid-m/metrics")
    assert r.status_code == 200
    j = r.json()
    assert j["task_id"] == "tid-m"
    assert j["ralf_iterations"] == 1
    assert j["estimated_tokens"] >= 120


def test_websocket_initial_payload() -> None:
    from services.pipeline_monitor import get_pipeline_monitor

    async def _seed() -> None:
        mon = get_pipeline_monitor()
        await mon.track("ws-t1", "pipeline", "PipelineRunner", "running", {})

    asyncio.run(_seed())

    with TestClient(app) as tc:
        with tc.websocket_connect("/api/v1/monitor/ws-t1/ws") as ws:
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["task_id"] == "ws-t1"
            assert len(data.get("events", [])) >= 1
