"""Week 6 — Redis 플랫폼 이벤트 구독 (AutoNoGaDa 측)."""
from __future__ import annotations

import logging
from typing import Any

from events.constants import EVENT_CODE_GENERATED

log = logging.getLogger("services.platform_event_handlers")


async def autonogada_incoming_dispatch(event_type: str, data: dict[str, Any]) -> None:
    """`code.generated` 수신 시 품질·텔레메트리 후속 처리(플레이스홀더)."""
    if event_type != EVENT_CODE_GENERATED:
        return
    tid = str(data.get("task_id", "") or "")
    qr = data.get("quality_report")
    log.info(
        "[AutoNoGaDa] 코드 생성 이벤트 → 품질 리포트 알림(예정) task=%s summary_keys=%s",
        tid[:12] if tid else "?",
        list(qr.keys()) if isinstance(qr, dict) else "none",
    )
