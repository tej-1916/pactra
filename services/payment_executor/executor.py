"""The privileged executor: turns a durable outbox event into a provider call.

This is the ONLY module that calls a payment provider. It is reachable from the
outbox worker and from nowhere else — in particular from no HTTP route and no
agent tool, so ``LLM -> provider`` has no path even if every layer above it is
compromised.

The one rule that makes this safe
---------------------------------
A ``ProviderTimeout`` is never resolved by guessing. It means the call did not
complete, and PACTRA cannot know whether a payment was created. The intent moves
to ``PROVIDER_PENDING`` — the uncertain state — and a reconciliation event is
scheduled. Nothing re-creates a payment until reconciliation has established
that the provider holds none.

The provider is also handed the idempotency key on every attempt, so even the
retry that reconciliation authorizes is deduplicated provider-side. The two
layers are independent on purpose: PACTRA's uncertainty handling does not
assume provider idempotency, and provider idempotency does not excuse blind
retries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from apps.api.db.models import Mission, OutboxEventRow, PaymentIntentRow
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, MissionState, ReasonCode, as_utc, utcnow
from packages.schemas.payment import (
    OutboxEventType,
    PaymentIntentState,
    PaymentRequest,
    ProviderPayment,
    provider_status_to_state,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_orchestrator.state_machine import can_transition
from services.audit_ledger.ledger import append_event
from services.payment_executor.outbox import (
    complete_event,
    enqueue_outbox_event,
    reschedule_event,
)
from services.payment_executor.providers.base import (
    PaymentProvider,
    ProviderError,
    ProviderPaymentMismatch,
    ProviderTerminalError,
    ProviderTimeout,
    ProviderTransientError,
)
from services.payment_executor.state_machine import (
    IllegalPaymentTransition,
    assert_payment_transition,
    is_terminal,
)
from services.security_kernel.capability_registry import enforce_registered

ACTOR = "payment-executor"

DIGEST_LOG_PREFIX = 16


@dataclass(frozen=True)
class DispatchResult:
    """What one dispatch attempt did. ``provider_called`` matters for tests that
    assert a terminal intent short-circuits without touching the provider."""

    state: PaymentIntentState
    provider_called: bool
    retry_scheduled: bool


async def lock_payment_intent(
    session: AsyncSession, payment_intent_id: uuid.UUID
) -> PaymentIntentRow:
    """Load one intent under a row lock for a state-machine decision.

    Reconciliation and webhooks may race. Both must serialize on the durable
    intent row before reading its state, otherwise two transactions can each
    approve a different terminal transition from the same stale
    ``PROVIDER_PENDING`` value.
    """
    result = await session.execute(
        select(PaymentIntentRow)
        .where(PaymentIntentRow.id == payment_intent_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    intent = result.scalar_one_or_none()
    if intent is None:  # pragma: no cover - outbox/webhook FKs prevent this
        raise ValueError(f"payment intent {payment_intent_id} does not exist")
    return intent


async def apply_mission_state(
    session: AsyncSession, mission_id: uuid.UUID, target: MissionState
) -> None:
    """Move the mission alongside the payment, when the move is legal.

    The payment state machine is authoritative for the payment. The mission
    state machine is a separate, coarser view, and a mission that has already
    moved on must not be dragged backwards — so an illegal move is skipped
    rather than forced. The payment's own state remains the record of truth.
    """
    mission = await session.get(Mission, mission_id)
    if mission is None:
        return
    if can_transition(MissionState(mission.state), target):
        mission.state = target.value
        await session.flush()


async def apply_payment_transition(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    target: PaymentIntentState,
    event_type: EventType,
    payload: dict,
    reason_code: str | None = None,
) -> None:
    """Apply a guarded payment transition and record it."""
    assert_payment_transition(PaymentIntentState(intent.state), target)
    intent.state = target.value
    intent.last_reason_code = reason_code
    await session.flush()
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=event_type,
        actor=ACTOR,
        payload={"payment_intent_id": str(intent.id), "state": target.value, **payload},
    )


async def link_provider_payment(
    session: AsyncSession, *, intent: PaymentIntentRow, payment: ProviderPayment
) -> None:
    """Record which provider payment this intent corresponds to.

    Written at most once. A second, DIFFERENT provider payment id arriving for
    the same intent means the system created two provider payments for one
    logical payment — the exact failure Phase 4 exists to prevent — so it raises
    instead of overwriting. Overwriting would hide the duplicate and leave the
    first charge unreferenced.
    """
    if intent.provider_payment_id is None:
        intent.provider_payment_id = payment.provider_payment_id
        await session.flush()
        return
    if intent.provider_payment_id != payment.provider_payment_id:
        raise ValueError(
            f"payment intent {intent.id} is already linked to provider payment "
            f"{intent.provider_payment_id}; refusing to relink to "
            f"{payment.provider_payment_id}"
        )


def validate_provider_payment(
    *,
    intent: PaymentIntentRow,
    payment: ProviderPayment,
    require_idempotency_key: bool = False,
) -> None:
    """Bind an untrusted provider response to the durable local intent.

    The provider may report state; it may not redefine which transaction was
    authorized.  Validation runs before the provider id is linked and before a
    success/failure transition is applied.
    """
    mismatches: list[str] = []
    if payment.provider != intent.provider:
        mismatches.append(f"provider={payment.provider!r}, expected {intent.provider!r}")
    if payment.amount_inr != intent.amount_inr:
        mismatches.append(f"amount_inr={payment.amount_inr}, expected {intent.amount_inr}")
    if payment.currency != intent.currency:
        mismatches.append(f"currency={payment.currency!r}, expected {intent.currency!r}")
    if payment.idempotency_key is None:
        if require_idempotency_key:
            mismatches.append("idempotency_key is absent")
    elif payment.idempotency_key != intent.idempotency_key:
        mismatches.append(
            f"idempotency_key={payment.idempotency_key!r}, expected {intent.idempotency_key!r}"
        )

    if mismatches:
        raise ProviderPaymentMismatch(
            intent.provider,
            "; ".join(mismatches),
        )


def validate_provider_route(*, intent: PaymentIntentRow, provider: PaymentProvider) -> None:
    """Refuse a worker that routed an intent to the wrong provider adapter."""
    if provider.name != intent.provider:
        raise ProviderPaymentMismatch(
            provider.name,
            f"adapter {provider.name!r} cannot process intent for {intent.provider!r}",
        )


async def apply_provider_payment(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    payment: ProviderPayment,
    now: datetime | None = None,
) -> PaymentIntentState:
    """Fold a provider's answer into the intent's state.

    Shared by dispatch, reconciliation, and webhook handling so all three agree
    on what a provider status means, and so the terminal-state guard is applied
    in exactly one place.
    """
    moment = as_utc(now or utcnow())
    current = PaymentIntentState(intent.state)
    target = provider_status_to_state(payment.status)

    # When nothing is linked yet, the idempotency key is the ONLY thing tying
    # this response to this intent — the recovery path asked "what do you hold
    # for key K?" and an answer that does not name K is not an answer about K.
    # Accepting it would let a payment with a coincidentally equal amount and
    # currency be adopted and settled as ours. Once a provider payment IS
    # linked, correlation is established by the id instead, and
    # `link_provider_payment` refuses to relink a different one.
    validate_provider_payment(
        intent=intent,
        payment=payment,
        require_idempotency_key=intent.provider_payment_id is None,
    )
    await link_provider_payment(session, intent=intent, payment=payment)

    if current == target or is_terminal(current):
        # Already there, or already settled. Idempotent no-op: this is what
        # makes duplicate outbox processing and repeated webhooks harmless.
        return current

    if target == PaymentIntentState.SUCCEEDED:
        await apply_payment_transition(
            session,
            intent=intent,
            target=target,
            event_type=EventType.PAYMENT_SUCCEEDED,
            payload={
                "provider": intent.provider,
                "provider_payment_id": payment.provider_payment_id,
                "amount_inr": intent.amount_inr,
                "currency": intent.currency,
                "settled_at": moment.isoformat(),
            },
        )
        await apply_mission_state(session, intent.mission_id, MissionState.PAYMENT_SUCCEEDED)
    elif target == PaymentIntentState.FAILED_TERMINAL:
        await apply_payment_transition(
            session,
            intent=intent,
            target=target,
            event_type=EventType.PAYMENT_FAILED,
            payload={
                "provider": intent.provider,
                "provider_payment_id": payment.provider_payment_id,
            },
            reason_code=ReasonCode.PROVIDER_TERMINAL_FAILURE.value,
        )
        await apply_mission_state(session, intent.mission_id, MissionState.PAYMENT_FAILED)
    else:
        await apply_payment_transition(
            session,
            intent=intent,
            target=PaymentIntentState.PROVIDER_PENDING,
            event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
            payload={
                "provider": intent.provider,
                "provider_payment_id": payment.provider_payment_id,
                "provider_status": payment.status.value,
            },
        )
    return PaymentIntentState(intent.state)


async def _mark_uncertain(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    detail: str,
    now: datetime,
    reason_code: str = ReasonCode.PAYMENT_PROVIDER_TIMEOUT.value,
    timed_out: bool = True,
) -> None:
    """Record that a provider payment MAY exist and its outcome is unknown.

    Two audit events, deliberately: ``PAYMENT_PROVIDER_TIMEOUT`` records what
    was observed, ``PAYMENT_PROVIDER_UNCERTAIN`` records what was concluded.
    Keeping them apart means the audit trail shows the inference, not just the
    result.
    """
    if timed_out:
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.PAYMENT_PROVIDER_TIMEOUT,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "reason_code": reason_code,
                "provider": intent.provider,
                "detail": detail,
            },
        )
    await apply_payment_transition(
        session,
        intent=intent,
        target=PaymentIntentState.PROVIDER_PENDING,
        event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
        payload={
            "provider": intent.provider,
            # Said plainly, because this is the whole point of the state.
            "provider_payment_may_exist": True,
            "resolution": "reconciliation",
            "reason_code": reason_code,
            "detail": detail,
        },
        reason_code=reason_code,
    )
    await enqueue_outbox_event(
        session,
        payment_intent_id=intent.id,
        event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
        payload={"idempotency_key": intent.idempotency_key},
        available_at=now,
    )


async def dispatch_create(
    session: AsyncSession,
    *,
    capabilities: CapabilitySet,
    provider: PaymentProvider,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    now: datetime | None = None,
) -> DispatchResult:
    """Attempt the provider call for one claimed ``PAYMENT_CREATE_REQUESTED``.

    PRIVILEGED: ``payment.execute`` is enforced before the provider is touched.
    """
    enforce_registered(capabilities, Capability.PAYMENT_EXECUTE)
    intent = await lock_payment_intent(session, intent.id)
    moment = as_utc(now or utcnow())
    current = PaymentIntentState(intent.state)

    # A routing mistake must be caught before either adapter method is called.
    validate_provider_route(intent=intent, provider=provider)

    # A duplicate delivery of an event for an already-settled payment. Doing
    # nothing here is what makes test "duplicate outbox processing creates no
    # duplicate provider payment" hold even before provider idempotency helps.
    if is_terminal(current):
        await complete_event(session, event=event, now=moment)
        return DispatchResult(state=current, provider_called=False, retry_scheduled=False)

    # The intent is uncertain: a provider payment may already exist. Creating
    # another would be the duplicate charge. Convert this into reconciliation.
    if current == PaymentIntentState.PROVIDER_PENDING:
        await enqueue_outbox_event(
            session,
            payment_intent_id=intent.id,
            event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
            payload={"idempotency_key": intent.idempotency_key},
            available_at=moment,
        )
        await complete_event(session, event=event, now=moment)
        return DispatchResult(state=current, provider_called=False, retry_scheduled=True)

    if current == PaymentIntentState.FAILED_RETRYABLE:
        assert_payment_transition(current, PaymentIntentState.QUEUED)
        intent.state = PaymentIntentState.QUEUED.value
        current = PaymentIntentState.QUEUED

    if current != PaymentIntentState.QUEUED:
        raise IllegalPaymentTransition(current, PaymentIntentState.PROCESSING)

    await apply_payment_transition(
        session,
        intent=intent,
        target=PaymentIntentState.PROCESSING,
        event_type=EventType.PAYMENT_ATTEMPTED,
        payload={"provider": intent.provider, "attempt": intent.attempts + 1},
    )
    intent.attempts += 1
    await session.flush()

    request = PaymentRequest(
        idempotency_key=intent.idempotency_key,
        amount_inr=intent.amount_inr,
        currency=intent.currency,
        merchant_id=intent.merchant_id,
        transaction_digest_prefix=intent.transaction_digest[:DIGEST_LOG_PREFIX],
    )

    # Recovery-safe preflight.  The local PROCESSING transition may have been
    # rolled back after an earlier provider success.  Looking up the durable
    # idempotency key before every create lets us adopt that payment without a
    # blind second create, even when the provider's create endpoint itself is
    # not idempotent.
    try:
        existing = await provider.get_payment(idempotency_key=intent.idempotency_key)
    except ProviderError as lookup_error:
        await _mark_uncertain(
            session,
            intent=intent,
            detail=f"pre-create lookup failed: {lookup_error.detail}",
            now=moment,
            reason_code=lookup_error.reason_code,
            timed_out=isinstance(lookup_error, ProviderTimeout),
        )
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=PaymentIntentState.PROVIDER_PENDING,
            provider_called=True,
            retry_scheduled=True,
        )

    if existing is not None:
        try:
            state = await apply_provider_payment(
                session, intent=intent, payment=existing, now=moment
            )
        except ProviderPaymentMismatch as mismatch:
            await _mark_uncertain(
                session,
                intent=intent,
                detail=mismatch.detail,
                now=moment,
                reason_code=mismatch.reason_code,
                timed_out=False,
            )
            await complete_event(session, event=event, now=moment)
            return DispatchResult(
                state=PaymentIntentState.PROVIDER_PENDING,
                provider_called=True,
                retry_scheduled=True,
            )

        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.PAYMENT_RECONCILED,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "provider": intent.provider,
                "provider_payment_id": existing.provider_payment_id,
                "state": state.value,
                "recovered_before_create": True,
            },
        )
        if state == PaymentIntentState.PROVIDER_PENDING:
            await enqueue_outbox_event(
                session,
                payment_intent_id=intent.id,
                event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
                payload={"idempotency_key": intent.idempotency_key},
                available_at=moment,
            )
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=state,
            provider_called=True,
            retry_scheduled=state == PaymentIntentState.PROVIDER_PENDING,
        )

    try:
        payment = await provider.create_payment(request)
    except ProviderTimeout as timeout:
        await _mark_uncertain(session, intent=intent, detail=timeout.detail, now=moment)
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=PaymentIntentState.PROVIDER_PENDING,
            provider_called=True,
            retry_scheduled=True,
        )
    except ProviderTransientError as transient:
        # The provider ANSWERED. Nothing was created, so a retry is safe.
        await apply_payment_transition(
            session,
            intent=intent,
            target=PaymentIntentState.FAILED_RETRYABLE,
            event_type=EventType.PAYMENT_FAILED,
            payload={"provider": intent.provider, "retryable": True},
            reason_code=ReasonCode.PROVIDER_TRANSIENT_FAILURE.value,
        )
        retried = await reschedule_event(session, event=event, reason=transient.detail, now=moment)
        await _audit_retry(session, intent=intent, retried=retried, event=event)
        return DispatchResult(
            state=PaymentIntentState.FAILED_RETRYABLE,
            provider_called=True,
            retry_scheduled=retried,
        )
    except ProviderTerminalError as terminal:
        await apply_payment_transition(
            session,
            intent=intent,
            target=PaymentIntentState.FAILED_TERMINAL,
            event_type=EventType.PAYMENT_FAILED,
            payload={"provider": intent.provider, "retryable": False, "detail": terminal.detail},
            reason_code=ReasonCode.PROVIDER_TERMINAL_FAILURE.value,
        )
        await apply_mission_state(session, intent.mission_id, MissionState.PAYMENT_FAILED)
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=PaymentIntentState.FAILED_TERMINAL,
            provider_called=True,
            retry_scheduled=False,
        )

    try:
        validate_provider_payment(
            intent=intent,
            payment=payment,
            require_idempotency_key=True,
        )
        state = await apply_provider_payment(session, intent=intent, payment=payment, now=moment)
    except ProviderPaymentMismatch as mismatch:
        await _mark_uncertain(
            session,
            intent=intent,
            detail=mismatch.detail,
            now=moment,
            reason_code=mismatch.reason_code,
            timed_out=False,
        )
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=PaymentIntentState.PROVIDER_PENDING,
            provider_called=True,
            retry_scheduled=True,
        )
    if state == PaymentIntentState.PROVIDER_PENDING:
        # Accepted but not settled: the outcome arrives by webhook or by poll.
        await enqueue_outbox_event(
            session,
            payment_intent_id=intent.id,
            event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
            payload={"idempotency_key": intent.idempotency_key},
            available_at=moment,
        )
    await complete_event(session, event=event, now=moment)
    return DispatchResult(
        state=state,
        provider_called=True,
        retry_scheduled=state == PaymentIntentState.PROVIDER_PENDING,
    )


async def _audit_retry(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    retried: bool,
    event: OutboxEventRow,
) -> None:
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=(
            EventType.PAYMENT_RETRY_SCHEDULED if retried else EventType.OUTBOX_EVENT_DEAD_LETTERED
        ),
        actor=ACTOR,
        payload={
            "payment_intent_id": str(intent.id),
            "outbox_event_id": str(event.id),
            "attempts": event.attempts,
            "max_attempts": event.max_attempts,
            "available_at": as_utc(event.available_at).isoformat(),
        },
    )
