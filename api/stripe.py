"""ADK Stripe 결제 게이트웨이 라우트 (B-7, 2026-05-12).

엔드포인트 (모두 ``/api/v1/billing/stripe/...``):
    - GET  /status              — env 토글 + supported events 진단
    - POST /checkout            — 인증 사용자가 plan_code 로 Checkout Session 생성
    - POST /webhook             — Stripe 가 호출 (raw body + Stripe-Signature)
    - POST /admin/plan-mapping  — admin 이 plan ↔ stripe_price_id 매핑 등록
    - GET  /admin/plan-mapping/{plan_code} — admin 이 매핑 조회

설계 결정:
    - ``STRIPE_ENABLED=0`` (기본) 일 때 checkout / webhook 은 503 반환.
    - Webhook 은 raw body 가 필요해 ``Request.body()`` 직접 사용.
    - Webhook 실패 (서명/JSON) 는 400, Stripe 에 재시도 위임.
"""
from __future__ import annotations

import logging

from auth.dependencies import current_user_strict, require_role
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from saas.schemas import (
    StripeCheckoutRequest,
    StripeCheckoutResponse,
    StripePlanMappingOut,
    StripePlanMappingRequest,
    StripePortalRequest,
    StripePortalResponse,
    StripeStatusResponse,
    StripeWebhookResponse,
)
from saas.stripe_service import (
    SUPPORTED_EVENTS,
    StripeDisabled,
    StripeSignatureError,
)
from services.billing import adk_stripe

log = logging.getLogger("api.stripe")
router = APIRouter()


@router.get(
    "/status",
    response_model=StripeStatusResponse,
    summary="Stripe 통합 상태 (env 토글 확인)",
)
async def stripe_status() -> StripeStatusResponse:
    cfg = adk_stripe.config
    return StripeStatusResponse(
        enabled=cfg.enabled,
        public_key=cfg.public_key if cfg.enabled else None,
        supported_events=sorted(SUPPORTED_EVENTS),
    )


@router.post(
    "/checkout",
    response_model=StripeCheckoutResponse,
    summary="Stripe Checkout Session 생성 (인증)",
)
async def create_checkout(
    body: StripeCheckoutRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> StripeCheckoutResponse:
    try:
        session = await adk_stripe.create_checkout_session(
            db,
            user_id=str(user.get("user_id", "")),
            plan_code=body.plan_code,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
        )
    except StripeDisabled as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return StripeCheckoutResponse(session_id=session["id"], url=session["url"])


@router.post(
    "/webhook",
    response_model=StripeWebhookResponse,
    summary="Stripe Webhook 수신 (raw body + Stripe-Signature)",
)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StripeWebhookResponse:
    if not adk_stripe.is_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe 가 비활성 상태 (STRIPE_ENABLED=0)",
        )
    raw = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = adk_stripe.parse_event(raw, sig)
    except StripeSignatureError as e:
        log.warning("Stripe webhook 서명 검증 실패: %s", e)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e

    result = await adk_stripe.handle_event(db, event)
    return StripeWebhookResponse(**result)


@router.post(
    "/admin/plan-mapping",
    response_model=StripePlanMappingOut,
    summary="Plan ↔ stripe_price_id 매핑 등록 (admin)",
)
async def admin_set_plan_mapping(
    body: StripePlanMappingRequest,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_role("admin")),
) -> StripePlanMappingOut:
    try:
        await adk_stripe.set_plan_mapping(
            db, plan_code=body.plan_code, stripe_price_id=body.stripe_price_id
        )
    except ValueError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return StripePlanMappingOut(
        plan_code=body.plan_code, stripe_price_id=body.stripe_price_id
    )


@router.post("/portal", response_model=StripePortalResponse)
async def create_portal(
    body: StripePortalRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(current_user_strict),
) -> StripePortalResponse:
    """Stripe Customer Portal session 생성 (B-7 Round 2)."""
    try:
        session = await adk_stripe.create_portal_session(
            db,
            user_id=str(user.get("user_id", "")),
            return_url=body.return_url,
        )
    except StripeDisabled as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        ) from e
    except ValueError as e:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(e)
        ) from e
    return StripePortalResponse(session_id=session["id"], url=session["url"])


@router.get(
    "/admin/plan-mapping/{plan_code}",
    response_model=StripePlanMappingOut,
    summary="Plan 매핑 조회 (admin)",
)
async def admin_get_plan_mapping(
    plan_code: str,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(require_role("admin")),
) -> StripePlanMappingOut:
    mapping = await adk_stripe.get_plan_mapping(db, plan_code=plan_code)
    if mapping is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"plan '{plan_code}' has no Stripe price mapping",
        )
    return StripePlanMappingOut(
        plan_code=plan_code, stripe_price_id=mapping.stripe_price_id
    )
