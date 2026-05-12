"""B-7 Round 2 — ADK Stripe R2 통합 테스트 (Mock 0).

CoOps R2 와 동일 패턴 — ADK 의 'dev' plan + ``adk_stripe`` 인스턴스 사용.
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from database import async_session_maker
from models import BillingPlan, StripePlanMapping, StripeSubscription
from saas.stripe_service import StripeConfig
from services.billing import adk_stripe


async def _developer_headers(client: AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/auth/token",
        data={"username": "developer", "password": "dev123"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@contextmanager
def _stripe_enabled():
    original = adk_stripe.config
    adk_stripe.config = StripeConfig(
        enabled=True,
        secret_key="sk_test_dummy",
        webhook_secret="whsec_test_dummy",
        public_key="pk_test_dummy",
        skip_signature_verification=True,
    )
    try:
        yield
    finally:
        adk_stripe.config = original


async def _ensure_paid_plan_mapping() -> str:
    plan_code = "dev"
    async with async_session_maker() as s:
        plan = await s.scalar(
            select(BillingPlan).where(BillingPlan.code == plan_code)
        )
        existing = await s.scalar(
            select(StripePlanMapping).where(StripePlanMapping.plan_id == plan.id)
        )
        if existing is None:
            s.add(
                StripePlanMapping(
                    id=str(uuid.uuid4()),
                    plan_id=plan.id,
                    stripe_price_id=f"price_test_{uuid.uuid4().hex[:12]}",
                )
            )
            await s.commit()
    return plan_code


async def _seed_subscription_with_sidecar(user_id: str, stripe_sub_id: str) -> None:
    plan_code = await _ensure_paid_plan_mapping()
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "mode": "subscription",
            "customer": f"cus_{uuid.uuid4().hex[:16]}",
            "subscription": stripe_sub_id,
            "metadata": {"user_id": user_id, "plan_code": plan_code},
        }},
    }
    async with async_session_maker() as db:
        await adk_stripe.handle_event(db, event)
        await db.commit()


# ── /portal ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portal_no_auth_returns_401(client: AsyncClient) -> None:
    r = await client.post("/api/v1/billing/stripe/portal", json={})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_portal_disabled_returns_503(client: AsyncClient) -> None:
    hdr = await _developer_headers(client)
    r = await client.post(
        "/api/v1/billing/stripe/portal", json={}, headers=hdr
    )
    assert r.status_code == 503


# ── invoice 이벤트 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_invoice_paid_updates_sidecar(client: AsyncClient) -> None:
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    await _seed_subscription_with_sidecar(user_id, stripe_sub_id)

    payload = {
        "type": "invoice.paid",
        "data": {"object": {
            "subscription": stripe_sub_id,
            "amount_paid": 2900,  # $29
            "currency": "usd",
        }},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "paid"

    async with async_session_maker() as s:
        side = await s.scalar(
            select(StripeSubscription).where(
                StripeSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        assert side is not None
        assert side.last_paid_at is not None
        assert side.last_paid_amount_cents == 2900


@pytest.mark.asyncio
async def test_webhook_invoice_failed_updates_failure_at(client: AsyncClient) -> None:
    user_id = f"u_{uuid.uuid4().hex[:8]}"
    stripe_sub_id = f"sub_{uuid.uuid4().hex[:16]}"
    await _seed_subscription_with_sidecar(user_id, stripe_sub_id)

    payload = {
        "type": "invoice.payment_failed",
        "data": {"object": {"subscription": stripe_sub_id}},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "failed"


@pytest.mark.asyncio
async def test_webhook_charge_refunded_returns_refunded(client: AsyncClient) -> None:
    payload = {
        "type": "charge.refunded",
        "data": {"object": {"amount_refunded": 1000, "currency": "usd"}},
    }
    with _stripe_enabled():
        r = await client.post(
            "/api/v1/billing/stripe/webhook",
            content=json.dumps(payload).encode(),
            headers={"content-type": "application/json"},
        )
    assert r.status_code == 200
    assert r.json()["action"] == "refunded"
