"""SaaS 비즈니스 트랙 (Phase 2 → C-3) — shared 의 enforce_quota factory + record_call.

ADK 의 ``enforce_quota`` 와 ``record_call`` API 형태는 그대로 유지하되, 내부는
``shared_libraries.saas.quota`` 의 일반화된 구현으로 위임한다.

기존에 ADK 가 노출하던 심볼 (``QuotaContext``, ``enforce_quota``, ``record_call``,
``quota_headers``) 을 import 하던 코드 (``api/pipeline.py``, ``services/pipeline_runner.py``,
``tests/test_billing.py``) 는 변경 없이 동작.
"""
from __future__ import annotations

from auth.dependencies import current_user_strict
from database import get_db
from saas import QuotaContext, make_enforce_quota_dep, quota_headers
from saas import record_call as _shared_record_call
from services.billing import adk_billing

# FastAPI deps factory — service 마다 한 번 생성.
enforce_quota = make_enforce_quota_dep(
    adk_billing,
    get_user=current_user_strict,
    get_db=get_db,
)


async def record_call(
    db,
    quota: QuotaContext,
    *,
    success: bool,
    model_used: str | None = None,
    tokens_estimated: int = 0,
    latency_ms: int | None = None,
) -> None:
    """ADK 의 ``record_call`` — shared.record_call 에 ADK 의 BillingService 주입."""
    return await _shared_record_call(
        adk_billing,
        db,
        quota,
        success=success,
        model_used=model_used,
        tokens_estimated=tokens_estimated,
        latency_ms=latency_ms,
    )


__all__ = [
    "QuotaContext",
    "enforce_quota",
    "quota_headers",
    "record_call",
]
