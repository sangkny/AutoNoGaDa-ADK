"""파이프라인 실시간 상태 추적 — Redis( TTL 1h ) 또는 메모리(로컬/테스트)."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger("services.pipeline_monitor")

TTL_SEC = 3600
PREFIX = "pipeline:"
STATUS_SUFFIX = ":status"
ACTIVE_INDEX = "monitor:active_index"


@dataclass
class PipelineMetrics:
    """작업별 누적 메트릭(추정)."""

    estimated_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    ralf_iterations: int = 0


@dataclass
class PipelineStatus:
    task_id: str
    phase: str
    agent: str
    status: str
    progress: float
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: PipelineMetrics = field(default_factory=PipelineMetrics)
    started_at: str = ""
    updated_at: str = ""
    chan: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["metrics"] = asdict(self.metrics)
        return d


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_key() -> str:
    return date.today().strftime("%Y%m%d")


def _status_key(task_id: str) -> str:
    return f"{PREFIX}{task_id}{STATUS_SUFFIX}"


def _chan(task_id: str) -> str:
    return f"pipeline:chan:{task_id}"


class _MemoryKV:
    """테스트·redis 미설정 시 단순 저장 + WS 구독자."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._subs: dict[str, list[asyncio.Queue[str]]] = {}

    def setex_sync(self, key: str, ttl: int, value: str) -> None:
        self._data[key] = value

    def get_sync(self, key: str) -> str | None:
        return self._data.get(key)

    def delete_sync(self, key: str) -> None:
        self._data.pop(key, None)

    def scan_status_keys_sync(self) -> list[str]:
        return [k for k in self._data if k.startswith(PREFIX) and k.endswith(STATUS_SUFFIX)]

    async def subscribe(self, task_id: str) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        lst = self._subs.setdefault(task_id, [])
        lst.append(q)
        return q

    def unsubscribe_queue(self, task_id: str, q: asyncio.Queue[str]) -> None:
        lst = self._subs.get(task_id)
        if lst and q in lst:
            lst.remove(q)


class PipelineMonitor:
    """Redis에 상태 스냅샷 저장, 채널로 WS 알림."""

    METRICS_DAY = "monitor:daily:{}"
    RECENT_RUNS = "monitor:recent_runs"
    MODEL_USAGE = "monitor:model_usage"

    # 추정 토큰 — 로컬 e4b 근거 없을 때 플레이스홀더 (문자 수 기준 대략)
    TOKEN_FACTOR = 1.25
    COST_PER_1M_TOKENS_USD_LOCAL = 0.0

    def __init__(self, redis_url: str | None) -> None:
        self._url = (redis_url or "").strip()
        self._mem = _MemoryKV() if not self._url else None

    async def track(
        self,
        task_id: str,
        phase: str,
        agent: str,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
        now = _utc_iso()
        snap = await self._load_snapshot(task_id)
        snap.task_id = task_id
        if not snap.started_at:
            snap.started_at = now
        snap.phase = phase
        snap.agent = agent
        snap.status = status
        meta = dict(snap.metadata)
        meta.update(metadata)
        snap.metadata = meta
        event = {"ts": now, "phase": phase, "agent": agent, "status": status, "metadata": dict(metadata)}
        snap.events.append(event)
        snap.updated_at = now
        chan = _chan(task_id)
        snap.chan = chan

        prog = snap.metadata.get("_progress_hint")
        if isinstance(prog, (int, float)):
            snap.progress = float(min(100.0, max(0.0, prog)))
        elif snap.status == "completed":
            snap.progress = 100.0

        payload = json.dumps(snap.to_json_dict(), ensure_ascii=False)
        await self._persist_status(task_id, payload)
        await self._persist_active_hint(task_id)
        await self._publish(task_id, payload)

    async def record_completion(
        self,
        task_id: str,
        *,
        success: bool,
        latency_ms: float,
        iterations: int,
        ontology_passed: bool,
        rough_char_count: int = 0,
        model_hint: str = "local/pipeline",
    ) -> None:
        """종료 스냅샷·일별 통계·최근 실행·모델 사용량."""
        metrics = PipelineMetrics(
            estimated_tokens=max(120, int(rough_char_count * self.TOKEN_FACTOR)),
            latency_ms=float(latency_ms),
            estimated_cost_usd=self.COST_PER_1M_TOKENS_USD_LOCAL,
            ralf_iterations=int(iterations),
        )
        meta = {"success": success, "ontology_passed": ontology_passed}
        snap = await self._load_snapshot(task_id)
        snap.task_id = task_id
        now = _utc_iso()
        snap.metrics = metrics
        snap.metadata.update(meta)
        snap.metadata["_progress_hint"] = 100.0
        snap.phase = "complete"
        snap.agent = "PipelineRunner"
        snap.status = "completed" if success else "failed"
        snap.progress = 100.0
        snap.updated_at = now
        snap.events.append(
            {
                "ts": now,
                "phase": "complete",
                "agent": "PipelineRunner",
                "status": snap.status,
                "metadata": dict(meta),
            },
        )
        payload = json.dumps(snap.to_json_dict(), ensure_ascii=False)
        await self._persist_status(task_id, payload)
        await self._persist_active_hint(task_id)
        await self._publish(task_id, payload)

        day = self.METRICS_DAY.format(_today_key())
        await self._incr_day_stats(day, success, latency_ms, metrics.estimated_tokens, model_hint)
        await self._push_recent(task_id, success, latency_ms, metrics.estimated_tokens, model_hint)

    async def _load_snapshot(self, task_id: str) -> PipelineStatus:
        raw = await self._get_raw(task_id)
        if not raw:
            return PipelineStatus(
                task_id=task_id,
                phase="",
                agent="",
                status="pending",
                progress=0.0,
            )
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return PipelineStatus(
                task_id=task_id,
                phase="unknown",
                agent="",
                status="error",
                progress=0.0,
            )
        m = d.get("metrics") or {}
        return PipelineStatus(
            task_id=d.get("task_id", task_id),
            phase=d.get("phase", ""),
            agent=d.get("agent", ""),
            status=d.get("status", ""),
            progress=float(d.get("progress", 0.0)),
            metadata=d.get("metadata") or {},
            events=list(d.get("events") or []),
            metrics=PipelineMetrics(
                estimated_tokens=int(m.get("estimated_tokens", 0)),
                latency_ms=float(m.get("latency_ms", 0.0)),
                estimated_cost_usd=float(m.get("estimated_cost_usd", 0.0)),
                ralf_iterations=int(m.get("ralf_iterations", 0)),
            ),
            started_at=d.get("started_at", ""),
            updated_at=d.get("updated_at", ""),
            chan=d.get("chan", ""),
        )

    async def get_status(self, task_id: str) -> PipelineStatus:
        return await self._load_snapshot(task_id)

    async def get_metrics(self, task_id: str) -> PipelineMetrics:
        s = await self._load_snapshot(task_id)
        return s.metrics

    async def get_active_task_ids(self) -> list[str]:
        if self._mem:
            keys = self._mem.scan_status_keys_sync()
            out: list[str] = []
            for k in keys:
                rest = k[len(PREFIX) :]
                if rest.endswith(STATUS_SUFFIX):
                    tid = rest[: -len(STATUS_SUFFIX)]
                    if tid:
                        st = await self._load_snapshot(tid)
                        if st.status not in ("completed", "failed", ""):
                            out.append(tid)
            return out

        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            idx = await client.smembers(ACTIVE_INDEX)
            out: list[str] = []
            for tid in idx or []:
                if await client.exists(_status_key(tid)):
                    st = await self._load_snapshot(tid)
                    if st.status not in ("completed", "failed"):
                        out.append(tid)
            return out
        finally:
            await client.aclose()

    async def get_system_metrics(self) -> dict[str, Any]:
        day = self.METRICS_DAY.format(_today_key())
        h = await self._hgetall(day)
        total = int(h.get("total_runs", 0) or 0)
        ok = int(h.get("success", 0) or 0)
        fail = int(h.get("failed", 0) or 0)
        lat_sum = float(h.get("latency_sum_ms", 0) or 0.0)
        tok_sum = int(h.get("total_tokens", 0) or 0)
        cost_sum = float(h.get("estimated_cost_usd", 0) or 0.0)
        return {
            "date": _today_key(),
            "total_runs": total,
            "success": ok,
            "failed": fail,
            "avg_latency_ms": (lat_sum / total) if total else 0.0,
            "total_tokens": tok_sum,
            "estimated_cost_usd": cost_sum,
        }

    async def get_model_usage(self) -> dict[str, int]:
        if self._mem:
            raw = self._mem.get_sync(self.MODEL_USAGE)
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            h = await client.hgetall(self.MODEL_USAGE)
            return {k: int(v) for k, v in (h or {}).items()}
        finally:
            await client.aclose()

    async def get_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if self._mem:
            raw = self._mem.get_sync(self.RECENT_RUNS)
            if not raw:
                return []
            try:
                arr = json.loads(raw)
                return list(arr[:limit])
            except json.JSONDecodeError:
                return []
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            items = await client.lrange(self.RECENT_RUNS, 0, limit - 1)
            out: list[dict[str, Any]] = []
            for it in items or []:
                try:
                    out.append(json.loads(it))
                except json.JSONDecodeError:
                    continue
            return out
        finally:
            await client.aclose()

    async def get_dashboard_bundle(self, active_limit: int = 50) -> dict[str, Any]:
        sys_m = await self.get_system_metrics()
        total_runs = int(sys_m.get("total_runs", 0))
        ok = int(sys_m.get("success", 0))
        success_rate = (ok / total_runs) if total_runs > 0 else 0.0
        acts = []
        for tid in (await self.get_active_task_ids())[:active_limit]:
            st = await self.get_status(tid)
            acts.append(st.to_json_dict())

        models = await self.get_model_usage()
        return {
            "today": {
                "total_runs": total_runs,
                "success_rate": round(success_rate, 4),
                "avg_latency_ms": round(sys_m.get("avg_latency_ms", 0.0), 3),
                "total_tokens": int(sys_m.get("total_tokens", 0)),
                "estimated_cost_usd": sys_m.get("estimated_cost_usd", 0.0),
            },
            "active_pipelines": acts,
            "recent_runs": await self.get_recent_runs(24),
            "model_usage": models,
        }

    # ── internals ───────────────────────────────────────────

    async def _set_progress(self, task_id: str, pct: float) -> None:
        snap = await self._load_snapshot(task_id)
        snap.metadata["_progress_hint"] = pct
        await self._persist_status(task_id, json.dumps(snap.to_json_dict(), ensure_ascii=False))

    async def _get_raw(self, task_id: str) -> str | None:
        if self._mem:
            return self._mem.get_sync(_status_key(task_id))
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            return await client.get(_status_key(task_id))
        finally:
            await client.aclose()

    async def _persist_status(self, task_id: str, payload: str) -> None:
        if self._mem:
            self._mem.setex_sync(_status_key(task_id), TTL_SEC, payload)
            return
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            await client.setex(_status_key(task_id), TTL_SEC, payload)
        finally:
            await client.aclose()

    async def _persist_active_hint(self, task_id: str) -> None:
        if self._mem:
            return
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            await client.sadd(ACTIVE_INDEX, task_id)
        finally:
            await client.aclose()

    async def _publish(self, task_id: str, payload: str) -> None:
        if self._mem:
            for q in list(self._mem._subs.get(task_id, [])):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
            return
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            await client.publish(_chan(task_id), payload)
        except Exception as e:
            log.debug("Redis PUBLISH skip: %s", e)
        finally:
            await client.aclose()

    async def _incr_day_stats(
        self,
        day_key: str,
        success: bool,
        latency_ms: float,
        tokens: int,
        model_hint: str,
    ) -> None:
        if self._mem:
            raw = self._mem.get_sync(day_key) or "{}"
            try:
                h = json.loads(raw)
            except json.JSONDecodeError:
                h = {}
            h["total_runs"] = int(h.get("total_runs", 0)) + 1
            if success:
                h["success"] = int(h.get("success", 0)) + 1
            else:
                h["failed"] = int(h.get("failed", 0)) + 1
            h["latency_sum_ms"] = float(h.get("latency_sum_ms", 0.0)) + latency_ms
            h["total_tokens"] = int(h.get("total_tokens", 0)) + tokens
            self._mem.setex_sync(day_key, TTL_SEC * 48, json.dumps(h, ensure_ascii=False))
            mu_raw = self._mem.get_sync(self.MODEL_USAGE) or "{}"
            try:
                mu = json.loads(mu_raw)
            except json.JSONDecodeError:
                mu = {}
            mu[model_hint] = int(mu.get(model_hint, 0)) + 1
            self._mem.setex_sync(self.MODEL_USAGE, TTL_SEC * 48, json.dumps(mu))
            return

        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            await client.hincrby(day_key, "total_runs", 1)
            if success:
                await client.hincrby(day_key, "success", 1)
            else:
                await client.hincrby(day_key, "failed", 1)
            await client.hincrbyfloat(day_key, "latency_sum_ms", float(latency_ms))
            await client.hincrby(day_key, "total_tokens", int(tokens))
            await client.expire(day_key, TTL_SEC * 48)
            await client.hincrby(self.MODEL_USAGE, model_hint, 1)
        finally:
            await client.aclose()

    async def _push_recent(
        self,
        task_id: str,
        success: bool,
        latency_ms: float,
        tokens: int,
        model_hint: str,
    ) -> None:
        rec = {
            "task_id": task_id,
            "success": success,
            "latency_ms": round(latency_ms, 3),
            "estimated_tokens": tokens,
            "model": model_hint,
            "finished_at": _utc_iso(),
        }
        blob = json.dumps(rec, ensure_ascii=False)
        if self._mem:
            raw = self._mem.get_sync(self.RECENT_RUNS)
            arr: list[dict[str, Any]] = []
            if raw:
                try:
                    arr = json.loads(raw)
                except json.JSONDecodeError:
                    arr = []
            arr.insert(0, rec)
            self._mem.setex_sync(self.RECENT_RUNS, TTL_SEC * 48, json.dumps(arr[:48]))
            return
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            await client.lpush(self.RECENT_RUNS, blob)
            await client.ltrim(self.RECENT_RUNS, 0, 99)
        finally:
            await client.aclose()

    async def _hgetall(self, key: str) -> dict[str, str]:
        if self._mem:
            raw = self._mem.get_sync(key)
            if not raw:
                return {}
            try:
                d = json.loads(raw)
                return {str(k): str(v) for k, v in d.items()}
            except json.JSONDecodeError:
                return {}
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        try:
            return dict(await client.hgetall(key) or {})
        finally:
            await client.aclose()

    async def iter_ws_messages(self, task_id: str) -> asyncio.AsyncIterator[str]:
        """WS용: 초기 상태 1건 + 메모리(backpressure 제한 없음)·Redis 채널 구독."""
        st = await self.get_status(task_id)
        yield json.dumps(st.to_json_dict(), ensure_ascii=False)

        if self._mem:
            q = await self._mem.subscribe(task_id)
            try:
                while True:
                    payload = await q.get()
                    yield payload
            finally:
                self._mem.unsubscribe_queue(task_id, q)
            return

        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe(_chan(task_id))
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if isinstance(data, str):
                    yield data
        finally:
            await pubsub.unsubscribe(_chan(task_id))
            await pubsub.aclose()
            await client.aclose()


_monitor: PipelineMonitor | None = None


def get_pipeline_monitor() -> PipelineMonitor:
    global _monitor
    if _monitor is None:
        from config import get_settings

        _monitor = PipelineMonitor(get_settings().redis_url or None)
    return _monitor


def reset_pipeline_monitor_for_tests(mon: PipelineMonitor | None = None) -> None:
    global _monitor
    _monitor = mon
