"""파이프라인 모니터링 — HTTP + WebSocket · 대시보드."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from services.pipeline_monitor import get_pipeline_monitor

log = logging.getLogger("api.monitoring")

monitor_router = APIRouter(prefix="/monitor", tags=["monitoring"])
dashboard_router = APIRouter(tags=["dashboard"])


@monitor_router.get("/active")
async def list_active_pipelines() -> dict[str, Any]:
    mon = get_pipeline_monitor()
    ids = await mon.get_active_task_ids()
    summaries: list[dict[str, Any]] = []
    for tid in ids:
        st = await mon.get_status(tid)
        summaries.append(st.to_json_dict())
    return {"count": len(summaries), "pipelines": summaries}


@monitor_router.get("/metrics")
async def system_metrics() -> dict[str, Any]:
    mon = get_pipeline_monitor()
    sys_m = await mon.get_system_metrics()
    models = await mon.get_model_usage()
    return {"system": sys_m, "model_usage": models}


@monitor_router.get("/{task_id}/metrics")
async def pipeline_metrics(task_id: str) -> dict[str, Any]:
    mon = get_pipeline_monitor()
    m = await mon.get_metrics(task_id)
    return {
        "task_id": task_id,
        "estimated_tokens": m.estimated_tokens,
        "latency_ms": m.latency_ms,
        "estimated_cost_usd": m.estimated_cost_usd,
        "ralf_iterations": m.ralf_iterations,
    }


@monitor_router.get("/{task_id}")
async def pipeline_status(task_id: str) -> dict[str, Any]:
    mon = get_pipeline_monitor()
    st = await mon.get_status(task_id)
    if not st.started_at and st.status == "pending":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="task_id 상태 없음 또는 만료됨",
        )
    return st.to_json_dict()


@monitor_router.websocket("/{task_id}/ws")
async def pipeline_ws(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    mon = get_pipeline_monitor()
    try:
        async for payload in mon.iter_ws_messages(task_id):
            await websocket.send_text(payload)
    except WebSocketDisconnect:
        log.debug("WS disconnect task_id=%s", task_id[:16])
    except Exception as e:
        log.warning("WS 오류 task_id=%s: %s", task_id[:16], e)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@dashboard_router.get("/dashboard")
async def dashboard() -> dict[str, Any]:
    return await get_pipeline_monitor().get_dashboard_bundle()
