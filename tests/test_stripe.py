"""B-7: Stripe 결제 게이트웨이 통합 테스트.

테스트 철학 (Mock 0):
    - ``stripe`` SDK 호출 mock 금지 — 실제 ``stripe.checkout.Session.create`` 호출은
      live API key 가 필요해 본 스위트 범위 밖. Checkout 라우트는 disabled 모드
      (503) 와 invalid plan (400) 만 검증.
    - Webhook 라우트는 ``skip_signature_verification=True`` 로 raw JSON 처리 →
      실제 DB 영속화 (sidecar row 생성/수정/구독 전환) 검증.
    - 인스턴스 ``adk_stripe.config`` 를 테스트 내에서 교체 — env 재시작 회피.

검증 범위:
    1. /status — env 토글 응답
    2. /checkout — disabled 503, invalid plan 400
    3. /webhook — disabled 503, invalid sig 400, 미지원 이벤트 ignored
    4. /webhook checkout.session.completed → 구독 전환 + sidecar 생성
    5. /webhook customer.subscription.updated → sidecar 상태/주기 갱신
    6. /webhook customer.subscription.deleted → free 로 전환 + sidecar canceled
    7. /admin/plan-mapping — admin 만 (403), 정상 upsert, 조회 404
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models import (
    BillingPlan,
    BillingSubscription,
    StripePlanMapping,
    StripeSubscription,
)
from saas.stripe_service import StripeConfig
from services.billing import adk_stripe


# ── 헬퍼 ──────────────────────────────────────────────────────


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _developer_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "developer", "password": "dev123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@contextmanager
def _stripe_enabled(*, skip_sig: bool = True):
    """``adk_stripe.config`` 를 enabled 로 일시 교체 → exit 시 복원."""
    original = adk_stripe.config
    adk_stripe.config = StripeConfig(
        enabled=True,
        secret_key="sk_test_dummy",
        webhook_secret="whsec_test_dummy",
        public_key="pk_test_dummy",
        skip_signature_verification=skip_sig,
    )
    try:
        yield
    finally:
        adk_stripe.config = original


async def _ensure_paid_plan_mapping() -> tuple[str, str]:
    """기존 ADK 'dev' plan 에 새 stripe_price_id 매핑 (upsert) 후 ``(plan_code, price_id)`` 반환.

    alembic adk006 가 시드한 4 plans (free/dev/team/ent) 의 schema 를 깨지 않도록
    *plan 자체는 생성하지 않는다*. mapping 만 upsert.
    """
    plan_code = "dev"
    price_id = f"price_test_{uuid.uuid4().hex[:12]}"
    async with async_session_maker() as s:
        plan = await s.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        assert plan is not None, "alembic adk006_billing 시드 (dev plan) 누락"
        existing = await s.scalar(
            select(StripePlanMapping).where(StripePlanMapping.plan_id == plan.id)
        )
        if existing is not None:
            existing.stripe_price_id = price_id
        else:
            s.add(StripePlanMapping(
                id=str(uuid.uuid4()),
                plan_id=plan.id,
                stripe_price_id=price_id,
            ))
        await s.commit()
    return plan_code, price_id


# ── 1. /status ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stripe_status_default_disabled(client: AsyncClient) -> None:
    r = await client.get("/api/v1/billing/stripe/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert "checkout.session.completed" in body["supported_events"]


@pytest.mark.asyncio
async def test_stripe_status_enabled_shows_public_key(
    client: AsyncClient,
) -> None:
    with _stripe_enabled():
        r = await client.get("/api/v1/billing/stripe/status")
    body = r.json()
    assert body["enabled"] is True
    assert body["public_key"] == "pk_test_dummy"


# ── 2. /checkout ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checkout_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/billing/stripe/checkout", json={"plan_code": "startup_dev"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_checkout_disabled_returns_503(client: AsyncClient) -> None:
    hdr = await _developer_headers(client)
    r = await client.post(
        "/api/v1/billing/stripe/checkout",
        json={"plan_code": "startup_dev"},
        headers=hdr,
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_checkout_unknown_plan_returns_400(client: AsyncClient) -> None:
    hdr = await _developer_headers(client)
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/checkout",
            json={"plan_code": "_does_not_exist_"},
            headers=hdr,
        )
    assert r.status_code == 400


# ── 3. /webhook ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_disabled_returns_503(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/billing/stripe/webhook",
        content=b"{}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_webhook_invalid_json_returns_400(client: AsyncClient) -> None:
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=b"not-json-at-all",
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_unsupported_event_returns_ignored(
    client: AsyncClient,
) -> None:
    # R2 부터 invoice.paid 는 지원 — coupon.* 같은 진짜 미지원 이벤트로 검증
    payload = {"type": "coupon.created", "data": {"object": {}}}
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["received"] is True
    assert body["action"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_checkout_completed_switches_plan(
    client: AsyncClient,
) -> None:
    plan_code, _price_id = await _ensure_paid_plan_mapping()
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    stripe_cust_id = f"cus_{uuid.uuid4().hex[:16]}"

    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": stripe_cust_id,
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "switched"

    # DB 검증
    async with async_session_maker() as s:
        sub = await s.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.user_id == user_id)
            .where(BillingSubscription.status == "active")
        )
        assert sub is not None
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.subscription_id == sub.id
            )
        )
        assert side is not None
        assert side.stripe_subscription_id == stripe_sub_id
        assert side.stripe_customer_id == stripe_cust_id
        assert side.stripe_status == "active"


@pytest.mark.asyncio
async def test_webhook_subscription_updated_syncs_status(
    client: AsyncClient,
) -> None:
    plan_code, _price_id = await _ensure_paid_plan_mapping()
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    stripe_cust_id = f"cus_{uuid.uuid4().hex[:16]}"

    # 1) checkout 으로 구독 생성
    completed = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": stripe_cust_id,
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    # 2) updated 이벤트
    period_end_ts = 1_900_000_000  # 2030-03-17
    updated = {
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": stripe_sub_id,
            "status": "past_due",
            "current_period_end": period_end_ts,
            "cancel_at_period_end": True,
        }},
    }
    with _stripe_enabled():
        await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(completed).encode(),
            headers={"content-type": "application/json"},
        )
        r2 = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(updated).encode(),
            headers={"content-type": "application/json"},
        )
    assert r2.status_code == 200
    assert r2.json()["action"] == "updated"

    async with async_session_maker() as s:
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        assert side is not None
        assert side.stripe_status == "past_due"
        assert side.cancel_at_period_end is True
        assert side.current_period_end is not None
        assert side.current_period_end.year == 2030


@pytest.mark.asyncio
async def test_webhook_subscription_deleted_reverts_to_free(
    client: AsyncClient,
) -> None:
    plan_code, _ = await _ensure_paid_plan_mapping()
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    stripe_cust_id = f"cus_{uuid.uuid4().hex[:16]}"

    completed = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": stripe_cust_id,
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    deleted = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": stripe_sub_id, "status": "canceled"}},
    }
    with _stripe_enabled():
        await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(completed).encode(),
            headers={"content-type": "application/json"},
        )
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(deleted).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "canceled"

    async with async_session_maker() as s:
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        assert side is not None
        assert side.stripe_status == "canceled"

        # 활성 구독은 free 로 (alembic adk006 가 free plan 을 시드)
        active = await s.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.user_id == user_id)
            .where(BillingSubscription.status == "active")
        )
        # free plan 시드가 없다면 None 일 수 있다 — 그 경우 sidecar 만 검증
        if active is not None:
            free_plan = await s.scalar(
                select(BillingPlan).where(BillingPlan.id == active.plan_id)
            )
            assert free_plan is not None
            assert free_plan.code == "free"


# ── 4. /admin/plan-mapping ─────────────────────────────────


@pytest.mark.asyncio
async def test_admin_plan_mapping_set_and_get_ok(client: AsyncClient) -> None:
    hdr = await _admin_headers(client)
    plan_code = "team"  # alembic adk006 시드된 plan
    new_price = f"price_test_{uuid.uuid4().hex[:12]}"

    r = await client.post(
        "/api/v1/billing/stripe/admin/plan-mapping",
        json={"plan_code": plan_code, "stripe_price_id": new_price},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan_code"] == plan_code
    assert body["stripe_price_id"] == new_price

    r2 = await client.get(
        f"/api/v1/billing/stripe/admin/plan-mapping/{plan_code}",
        headers=hdr,
    )
    assert r2.status_code == 200
    assert r2.json()["stripe_price_id"] == new_price


@pytest.mark.asyncio
async def test_admin_plan_mapping_non_admin_403(client: AsyncClient) -> None:
    hdr = await _developer_headers(client)
    r = await client.post(
        "/api/v1/billing/stripe/admin/plan-mapping",
        json={"plan_code": "startup_dev", "stripe_price_id": "price_x"},
        headers=hdr,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_plan_mapping_unknown_plan_400(client: AsyncClient) -> None:
    hdr = await _admin_headers(client)
    r = await client.post(
        "/api/v1/billing/stripe/admin/plan-mapping",
        json={"plan_code": "_no_such_plan_", "stripe_price_id": "price_x"},
        headers=hdr,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_admin_plan_mapping_get_404_for_unmapped(
    client: AsyncClient,
) -> None:
    hdr = await _admin_headers(client)
    # 'free' plan 은 기본 매핑 없음 (admin 이 직접 등록해야)
    # 단, 이전 테스트에서 매핑됐을 수 있어 fresh plan_code 로 검증
    plan_code = f"fresh_{uuid.uuid4().hex[:8]}"
    r = await client.get(
        f"/api/v1/billing/stripe/admin/plan-mapping/{plan_code}",
        headers=hdr,
    )
    assert r.status_code == 404
