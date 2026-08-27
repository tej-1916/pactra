"""Reconciliation — converting uncertainty into a settled answer.

``PROVIDER_PENDING`` is the honest state after a lost response, but a system
that stops there has only relocated the problem: a payment nobody can act on is
barely better than a payment nobody can explain. Reconciliation is the path that
makes the uncertain state temporary.

The question it asks the provider is deliberately *not* "did payment X
succeed?" — after a lost create response there is no X. It is "what do you hold
for idempotency key K?", because the key is the only handle PACTRA still has.
That is why the key is passed to the provider on every create call.

Four possible answers, four honest conclusions::

    SUCCEEDED  -> link the provider payment, state SUCCEEDED
    FAILED     -> state FAILED_TERMINAL
    PENDING    -> still genuinely unresolved; poll again with backoff
    not found  -> the provider holds NOTHING for this key, so no payment was
                  ever created and re-creating one cannot duplicate anything.
                  Only here does the intent become retryable again.

The last line is the crux. FAILED_RETRYABLE is reachable from
PROVIDER_PENDING through exactly one route — a provider that positively reports
holding no payment. There is no timeout, no elapsed timer, and no attempt count
that promotes an uncertain payment back to retryable, because none of those is
evidence about whether money moved.
"""

from __future__ import annotations

from datetime import datetime

from apps.api.db.models import OutboxEventRow, PaymentIntentRow
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, ReasonCode, as_utc, utcnow
from packages.schemas.payment import PaymentIntentState, ProviderPaymentStatus
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import append_event
from services.payment_executor.executor import (
    ACTOR,
    DispatchResult,
    apply_provider_payment,
    lock_payment_intent,
    validate_provider_route,
)
from services.payment_executor.outbox import complete_event, reschedule_event
from services.payment_executor.providers.base import (
    PaymentProvider,
    ProviderError,
    ProviderPaymentMismatch,
)
from services.payment_executor.state_machine import (
    assert_payment_transition,
    is_terminal,
)
from services.security_kernel.capability_registry import enforce_registered


async def reconcile_intent(
    session: AsyncSession,
    *,
    capabilities: CapabilitySet,
    provider: PaymentProvider,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    now: datetime | None = None,
) -> DispatchResult:
    """Resolve one uncertain payment against the provider's own records.

    PRIVILEGED: reconciliation reads provider payment state and can settle a
    payment, so it sits behind the same ``payment.execute`` gate as creation.
    """
    enforce_registered(capabilities, Capability.PAYMENT_EXECUTE)
    intent = await lock_payment_intent(session, intent.id)
    moment = as_utc(now or utcnow())
    current = PaymentIntentState(intent.state)

    validate_provider_route(intent=intent, provider=provider)

    if is_terminal(current):
        # Already settled — reconciliation has nothing to add and must not
        # reopen it. Idempotent by construction.
        await complete_event(session, event=event, now=moment)
        return DispatchResult(state=current, provider_called=False, retry_scheduled=False)

    try:
        payment = await provider.get_payment(
            provider_payment_id=intent.provider_payment_id,
            idempotency_key=intent.idempotency_key,
        )
    except ProviderError as error:
        # Could not ask. Uncertainty is unchanged — which is the correct
        # outcome, not a failure to record. Try again later.
        retried = await reschedule_event(session, event=event, reason=error.detail, now=moment)
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=(
                EventType.PAYMENT_RETRY_SCHEDULED
                if retried
                else EventType.OUTBOX_EVENT_DEAD_LETTERED
            ),
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "outbox_event_id": str(event.id),
                "reason_code": error.reason_code,
                "phase": "reconciliation",
            },
        )
        return DispatchResult(state=current, provider_called=True, retry_scheduled=retried)

    if payment is None:
        return await _resolve_no_provider_payment(
            session, intent=intent, event=event, now=moment, current=current
        )

    try:
        state = await apply_provider_payment(session, intent=intent, payment=payment, now=moment)
    except ProviderPaymentMismatch as mismatch:
        retried = await reschedule_event(
            session,
            event=event,
            reason=mismatch.detail,
            now=moment,
        )
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=(
                EventType.PAYMENT_RETRY_SCHEDULED
                if retried
                else EventType.OUTBOX_EVENT_DEAD_LETTERED
            ),
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "outbox_event_id": str(event.id),
                "reason_code": mismatch.reason_code,
                "phase": "reconciliation",
            },
        )
        return DispatchResult(
            state=current,
            provider_called=True,
            retry_scheduled=retried,
        )
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=EventType.PAYMENT_RECONCILED,
        actor=ACTOR,
        payload={
            "payment_intent_id": str(intent.id),
            "provider": intent.provider,
            "provider_payment_id": payment.provider_payment_id,
            "provider_status": payment.status.value,
            "state": state.value,
            # True whenever the provider handed back a payment it already held
            # — i.e. the lost-response case resolved onto the original payment.
            "resolved_existing_provider_payment": payment.status
            is not ProviderPaymentStatus.CREATED,
        },
    )

    if state == PaymentIntentState.PROVIDER_PENDING:
        # Genuinely still in flight at the provider. Poll again.
        retried = await reschedule_event(
            session, event=event, reason="provider payment still pending", now=moment
        )
        return DispatchResult(state=state, provider_called=True, retry_scheduled=retried)

    await complete_event(session, event=event, now=moment)
    return DispatchResult(state=state, provider_called=True, retry_scheduled=False)


async def _resolve_no_provider_payment(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    now: datetime,
    current: PaymentIntentState,
) -> DispatchResult:
    """The provider holds nothing for this key.

    This is positive evidence, not an absence of evidence: the provider was
    asked and answered. It is therefore safe — and only now safe — to make the
    intent retryable so a fresh create attempt can run.
    """
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=EventType.PAYMENT_RECONCILED,
        actor=ACTOR,
        payload={
            "payment_intent_id": str(intent.id),
            "provider": intent.provider,
            "reason_code": ReasonCode.PROVIDER_PAYMENT_NOT_FOUND.value,
            "provider_holds_no_payment": True,
            "conclusion": "safe to retry creation; no duplicate is possible",
        },
    )

    assert_payment_transition(current, PaymentIntentState.FAILED_RETRYABLE)
    intent.state = PaymentIntentState.FAILED_RETRYABLE.value
    intent.last_reason_code = ReasonCode.PROVIDER_PAYMENT_NOT_FOUND.value
    await session.flush()

    # Re-queue as a CREATE, not as another reconcile: there is nothing left to
    # reconcile once the provider has told us it holds nothing.
    from packages.schemas.payment import OutboxEventType

    from services.payment_executor.outbox import enqueue_outbox_event

    await enqueue_outbox_event(
        session,
        payment_intent_id=intent.id,
        event_type=OutboxEventType.PAYMENT_CREATE_REQUESTED,
        payload={"idempotency_key": intent.idempotency_key},
        available_at=now,
    )
    await complete_event(session, event=event, now=now)
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=EventType.PAYMENT_RETRY_SCHEDULED,
        actor=ACTOR,
        payload={
            "payment_intent_id": str(intent.id),
            "state": PaymentIntentState.FAILED_RETRYABLE.value,
            "reason_code": ReasonCode.PROVIDER_PAYMENT_NOT_FOUND.value,
        },
    )
    return DispatchResult(
        state=PaymentIntentState.FAILED_RETRYABLE,
        provider_called=True,
        retry_scheduled=True,
    )
