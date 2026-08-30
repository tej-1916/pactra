"""Phase 4 runtime surface: request a payment, and receive provider webhooks.

WHAT THESE ROUTES DELIBERATELY DO NOT DO
----------------------------------------
Neither route calls a payment provider. ``POST .../payment`` writes a durable
PaymentIntent and an outbox row inside one transaction and returns; the provider
is reached only by the outbox worker, out of band. That is not an implementation
detail — it is the reason ``LLM -> provider`` has no path. An HTTP request
cannot move money, because no code reachable from an HTTP request talks to a
payment rail.

WHAT THE CALLER MAY NOT SUPPLY
------------------------------
The amount, the merchant, the product, the currency, or a capability set. There
is no field for any of them. The request body carries nothing at all: the intent
is derived entirely from the authorization the kernel issued and holds, so a
mutated amount cannot be offered, only refused-that-was-never-asked. The
capability set comes from the server-owned registry inside the service call, not
from the request.

The idempotency key arrives in the ``Idempotency-Key`` header and is REQUIRED.
Generating one server-side would make every retry a new logical payment, which
is the opposite of what the header is for.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from services.payment_executor.intents import (
    IdempotencyConflict,
    MissionNotAuthorized,
    PaymentRequestRejected,
    create_payment_intent,
    payment_intent_for_mission,
)
from services.payment_executor.registry import (
    ProviderUnavailable,
    UnknownProvider,
    provider_for,
    signature_header_for,
)
from services.payment_executor.webhooks import WebhookRejected, handle_webhook
from services.payment_executor.worker import executor_capabilities
from services.security_kernel.authorization import (
    AuthorizationFailure,
    authorization_for_mission,
)
from services.security_kernel.capability import CapabilityDenied
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import Mission, PaymentIntentRow
from apps.api.db.session import get_session
from apps.api.pactra.config import get_settings
from apps.api.pactra.schemas_api import PaymentIntentOut, WebhookAck

router = APIRouter(prefix="/api/v1", tags=["payments"])

#: Cap on the accepted idempotency key. A key is an opaque client handle, not a
#: payload; an unbounded one is a free write-amplification primitive against the
#: UNIQUE index.
MAX_IDEMPOTENCY_KEY_LENGTH = 200

#: Cap on a webhook body before the MAC is even computed. Hashing is linear in
#: body size, so an unbounded body is a cheap way to make the server work hard
#: for an attacker who does not hold the secret.
MAX_WEBHOOK_BODY_BYTES = 64 * 1024


def _payment_out(row: PaymentIntentRow) -> PaymentIntentOut:
    return PaymentIntentOut(
        payment_intent_id=row.id,
        mission_id=row.mission_id,
        authorization_id=row.authorization_id,
        state=row.state,
        idempotency_key=row.idempotency_key,
        amount_inr=row.amount_inr,
        currency=row.currency,
        merchant_id=row.merchant_id,
        provider=row.provider,
        provider_payment_id=row.provider_payment_id,
        attempts=row.attempts,
        last_reason_code=row.last_reason_code,
        created_at=row.created_at,
    )


@router.post("/missions/{mission_id}/payment", response_model=PaymentIntentOut)
async def request_payment(
    mission_id: uuid.UUID,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    provider: str | None = Header(default=None, alias="X-Payment-Provider"),
    session: AsyncSession = Depends(get_session),
) -> PaymentIntentOut:
    """Create (or return) the one logical payment for an approved mission.

    201 when this call brought a payment into existence, 200 when it returned
    the one that already did. The distinction is the whole observable surface of
    the idempotency guarantee, so it is reported rather than flattened.
    """
    settings = get_settings()
    provider_name = provider or ("fake" if settings.app_env != "production" else "razorpay_test")

    if not idempotency_key or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={
                "reason_code": "IDEMPOTENCY_KEY_INVALID",
                "detail": f"Idempotency-Key must be 1..{MAX_IDEMPOTENCY_KEY_LENGTH} characters",
            },
        )

    # Resolved through the server-owned registry: an unregistered name is
    # refused here rather than stored on an intent no worker could ever route.
    try:
        provider_for(provider_name, app_env=settings.app_env)
    except UnknownProvider as unknown:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": unknown.reason_code, "provider": provider_name},
        ) from unknown
    except ProviderUnavailable as unavailable:
        raise HTTPException(
            status_code=503,
            detail={"reason_code": unavailable.reason_code, "detail": unavailable.detail},
        ) from unavailable

    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found")

    authorization = await authorization_for_mission(session, mission_id)
    if authorization is None:
        # NO VALID AUTHORIZATION -> NO PAYMENT INTENT, at the outermost layer.
        # The service enforces it again; this is the 404 rather than a 500.
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "NO_AUTHORIZATION",
                "detail": "this mission has no authorization to spend",
            },
        )

    try:
        result = await create_payment_intent(
            session,
            # NEVER from the request. The registry decides what this principal
            # holds, and the route has no way to widen it.
            capabilities=executor_capabilities(),
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key=idempotency_key,
            provider=provider_name,
        )
    except CapabilityDenied as denied:  # pragma: no cover - registry set is fixed
        raise HTTPException(
            status_code=403,
            detail={"reason_code": denied.reason_code},
        ) from denied
    except IdempotencyConflict as conflict:
        # SAME KEY + DIFFERENT TRANSACTION -> IDEMPOTENCY_CONFLICT. Never
        # resolved by reusing the held intent and never by creating a second.
        raise HTTPException(
            status_code=409,
            detail={"reason_code": conflict.reason_code, "detail": conflict.detail},
        ) from conflict
    except MissionNotAuthorized as unauthorized:
        raise HTTPException(
            status_code=409,
            detail={"reason_code": unauthorized.reason_code, "detail": unauthorized.detail},
        ) from unauthorized
    except AuthorizationFailure as failure:
        # Replayed, expired, or binding-mismatched authorization.
        raise HTTPException(
            status_code=409,
            detail={"reason_code": failure.reason_code, "detail": failure.detail},
        ) from failure
    except PaymentRequestRejected as rejected:
        raise HTTPException(
            status_code=409,
            detail={"reason_code": rejected.reason_code, "detail": rejected.detail},
        ) from rejected

    # The payment intent, the authorization consumption and the outbox event
    # were written in one transaction; they become durable together here,
    # before the caller learns a payment exists to be polled for.
    await session.commit()
    response.status_code = 201 if result.created else 200
    return _payment_out(result.intent)


@router.get("/missions/{mission_id}/payment", response_model=PaymentIntentOut)
async def get_payment(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> PaymentIntentOut:
    """Read the mission's payment intent, including its uncertain states.

    ``PROVIDER_PENDING`` is reported as itself rather than smoothed into
    "processing": a payment whose outcome PACTRA does not know is exactly what
    the caller needs to be told.
    """
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found")
    intent = await payment_intent_for_mission(session, mission_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="no payment intent for this mission")
    return _payment_out(intent)


@router.post("/webhooks/{provider_name}", response_model=WebhookAck)
async def receive_webhook(
    provider_name: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> WebhookAck:
    """Ingest one provider webhook.

    The body is read as RAW BYTES and handed to the adapter unparsed, because
    the MAC covers the exact bytes on the wire. Letting FastAPI parse a model
    first would re-serialize them, and a signature over re-serialized JSON is a
    signature over different bytes.

    An invalid signature returns 401 and changes nothing — including the audit
    ledger, which is mission-scoped and would have to pick its mission from the
    very payload the MAC check just refused to believe.
    """
    settings = get_settings()
    try:
        provider = provider_for(provider_name, app_env=settings.app_env)
        header_name = signature_header_for(provider_name)
    except UnknownProvider as unknown:
        raise HTTPException(
            status_code=404, detail={"reason_code": unknown.reason_code}
        ) from unknown
    except ProviderUnavailable as unavailable:
        raise HTTPException(
            status_code=503,
            detail={"reason_code": unavailable.reason_code, "detail": unavailable.detail},
        ) from unavailable

    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        # Refused before the MAC is computed: hashing is linear in body size.
        raise HTTPException(status_code=413, detail={"reason_code": "WEBHOOK_BODY_TOO_LARGE"})

    signature = request.headers.get(header_name, "")

    try:
        outcome = await handle_webhook(session, provider=provider, body=body, signature=signature)
    except WebhookRejected as rejected:
        status = 404 if rejected.reason_code == "WEBHOOK_UNKNOWN_PAYMENT" else 401
        raise HTTPException(
            status_code=status,
            detail={"reason_code": rejected.reason_code},
        ) from rejected

    # A provider treats a 2xx as "delivered, do not resend". The state
    # transition this webhook caused must therefore be durable before the ack
    # is written, or an accepted-but-lost event is never redelivered.
    await session.commit()
    return WebhookAck(
        accepted=outcome.accepted,
        applied=outcome.applied,
        reason_code=outcome.reason_code,
        state=outcome.state.value if outcome.state is not None else None,
    )
