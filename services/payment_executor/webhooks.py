"""Webhook ingestion — verify, deduplicate, then apply under the state machine.

Order is the security property here, so it is stated once and never varied::

    1. verify the signature over the RAW bytes      (provider.verify_webhook)
    2. resolve the payment by provider_payment_id   (server-side lookup)
    3. deduplicate on (provider, provider_event_id) (UNIQUE index)
    4. apply the transition ONLY if the state machine permits it

Nothing before step 1 reads the payload as meaning. The handler's parameter is
raw bytes plus a signature; the only way to obtain a ``VerifiedWebhookEvent`` is
to go through the provider's verifier, so "we forgot to check the signature" is
not a mistake this code can make — there is no other constructor on the path.

Three properties follow from steps 3 and 4:

* **Duplicate webhook** — the UNIQUE index rejects the second insert, so the
  transition runs at most once no matter how many times the provider delivers.
* **Delayed webhook** — terminal payment states have no outgoing transitions, so
  a late ``payment.failed`` after a settled success cannot regress anything.
* **Out-of-order webhook** — the transition table, not the arrival order,
  decides what is reachable. A provider-supplied sequence number is recorded for
  audit and is never the authority.

A rejected signature is never written to ``webhook_events``.  It also cannot be
placed on a mission audit chain: the unverified payload's claim about which
payment it concerns is exactly what was refused.  A future global security log
may record transport metadata, but it must not trust payload identifiers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from apps.api.db.models import PaymentIntentRow, WebhookEventRow
from packages.schemas.domain import EventType, MissionState, ReasonCode, as_utc, utcnow
from packages.schemas.payment import (
    PaymentIntentState,
    VerifiedWebhookEvent,
    WebhookVerificationError,
    webhook_type_to_state,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import append_event
from services.payment_executor.executor import (
    apply_mission_state,
    apply_payment_transition,
)
from services.payment_executor.providers.base import PaymentProvider
from services.payment_executor.state_machine import can_transition, is_terminal

ACTOR = "payment-executor"


class WebhookRejected(Exception):
    """The webhook was not accepted. Nothing about the payment changed."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(f"{reason_code}: {detail}")
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class WebhookOutcome:
    """What a delivery did.

    ``applied`` is False for every ignored case — duplicate, out-of-order,
    already-terminal — so a caller (and a test) can tell "we accepted this and
    changed nothing" from "we changed state".
    """

    accepted: bool
    applied: bool
    reason_code: str | None
    state: PaymentIntentState | None
    payment_intent_id: uuid.UUID | None


async def _find_intent(
    session: AsyncSession, *, provider: str, provider_payment_id: str
) -> PaymentIntentRow | None:
    """Resolve the payment from SERVER-SIDE state.

    The lookup is by ``provider_payment_id`` — a value PACTRA itself recorded
    when it linked the provider payment. The webhook supplies a pointer; it
    never supplies the payment's amount, merchant, or authorization, so a
    verified-but-hostile webhook cannot restate what the payment was for.
    """
    result = await session.execute(
        select(PaymentIntentRow)
        .where(
            PaymentIntentRow.provider == provider,
            PaymentIntentRow.provider_payment_id == provider_payment_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def handle_webhook(
    session: AsyncSession,
    *,
    provider: PaymentProvider,
    body: bytes,
    signature: str,
    now: datetime | None = None,
) -> WebhookOutcome:
    """Verify and apply one webhook delivery. Idempotent."""
    moment = as_utc(now or utcnow())

    # ---- 1. VERIFY. Nothing below this line existed before the MAC checked. --
    try:
        event: VerifiedWebhookEvent = provider.verify_webhook(body=body, signature=signature)
    except WebhookVerificationError as failure:
        # NOT AUDITED, deliberately, and this comment says so because the code
        # says so. The audit ledger is mission-scoped, and the only thing that
        # names a mission here is the unverified payload — the exact claim the
        # MAC check just refused to believe. Writing the event would mean
        # picking a mission chain on the authority of a forged body, which
        # would let an attacker append noise to any mission it could name.
        # Recording rejections belongs in a transport-scoped security log that
        # Phase 4 does not build; until that exists, no rejection event is
        # produced and nothing here claims one is.
        raise WebhookRejected(
            ReasonCode.WEBHOOK_SIGNATURE_INVALID.value, failure.detail
        ) from failure

    # ---- 2. Resolve the payment from server-side state. ---------------------
    intent = await _find_intent(
        session, provider=event.provider, provider_payment_id=event.provider_payment_id
    )
    if intent is None:
        raise WebhookRejected(
            ReasonCode.WEBHOOK_UNKNOWN_PAYMENT.value,
            f"no payment intent is linked to provider payment {event.provider_payment_id}",
        )

    # ---- 3. DEDUPLICATE on the UNIQUE index, not on a prior SELECT. ---------
    try:
        async with session.begin_nested():
            stored_event = WebhookEventRow(
                id=uuid.uuid4(),
                provider=event.provider,
                provider_event_id=event.provider_event_id,
                event_type=event.event_type.value,
                provider_payment_id=event.provider_payment_id,
                payment_intent_id=intent.id,
                sequence=event.sequence,
                received_at=moment,
            )
            session.add(stored_event)
            await session.flush()
    except IntegrityError:
        # Already delivered. The savepoint rolls the insert back and the
        # transition below is never reached, so no side effect repeats.
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.DUPLICATE_WEBHOOK_IGNORED,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "reason_code": ReasonCode.WEBHOOK_DUPLICATE.value,
                "provider_event_id": event.provider_event_id,
                "state": intent.state,
            },
        )
        return WebhookOutcome(
            accepted=True,
            applied=False,
            reason_code=ReasonCode.WEBHOOK_DUPLICATE.value,
            state=PaymentIntentState(intent.state),
            payment_intent_id=intent.id,
        )

    # A delivery is "verified" once per provider event, after it wins the
    # deduplication insert.  Duplicate transport deliveries produce the
    # duplicate audit event above, not repeated verified events.
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=EventType.WEBHOOK_VERIFIED,
        actor=ACTOR,
        payload={
            "payment_intent_id": str(intent.id),
            "provider": event.provider,
            "provider_event_id": event.provider_event_id,
            "event_type": event.event_type.value,
            "sequence": event.sequence,
            # NOTE: neither the signature nor the webhook secret is recorded.
        },
    )

    # ---- 4. Apply ONLY what the state machine permits. ----------------------
    current = PaymentIntentState(intent.state)
    target = webhook_type_to_state(event.event_type)

    if current == target or is_terminal(current) or not can_transition(current, target):
        # Covers all three ignore cases at once, and they are genuinely one
        # rule: a transition the machine does not allow is not performed. A
        # delayed webhook hits `is_terminal`; an out-of-order one hits
        # `can_transition`; a repeat of the current state hits the equality.
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.WEBHOOK_OUT_OF_ORDER_IGNORED,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "reason_code": ReasonCode.ILLEGAL_PAYMENT_TRANSITION.value,
                "provider_event_id": event.provider_event_id,
                "current_state": current.value,
                "requested_state": target.value,
                "terminal": is_terminal(current),
            },
        )
        stored_event.processed_at = moment
        stored_event.applied_state = None
        await session.flush()
        return WebhookOutcome(
            accepted=True,
            applied=False,
            reason_code=ReasonCode.ILLEGAL_PAYMENT_TRANSITION.value,
            state=current,
            payment_intent_id=intent.id,
        )

    await apply_payment_transition(
        session,
        intent=intent,
        target=target,
        event_type=(
            EventType.PAYMENT_SUCCEEDED
            if target == PaymentIntentState.SUCCEEDED
            else EventType.PAYMENT_FAILED
            if target == PaymentIntentState.FAILED_TERMINAL
            else EventType.PAYMENT_PROVIDER_UNCERTAIN
        ),
        payload={
            "provider": event.provider,
            "provider_payment_id": event.provider_payment_id,
            "provider_event_id": event.provider_event_id,
            "source": "webhook",
        },
    )

    if target == PaymentIntentState.SUCCEEDED:
        await apply_mission_state(session, intent.mission_id, MissionState.PAYMENT_SUCCEEDED)
    elif target == PaymentIntentState.FAILED_TERMINAL:
        await apply_mission_state(session, intent.mission_id, MissionState.PAYMENT_FAILED)

    stored_event.processed_at = moment
    stored_event.applied_state = target.value
    await session.flush()

    return WebhookOutcome(
        accepted=True,
        applied=True,
        reason_code=None,
        state=target,
        payment_intent_id=intent.id,
    )
