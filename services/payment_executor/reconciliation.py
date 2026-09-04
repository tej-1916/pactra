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
    not found  -> for an idempotent-create provider, a retry may be scheduled;
                  for a fenced provider, remain uncertain and never recreate.
                  Once an id was linked, not-found is always unresolved.

The create fence is the crux. Once it exists, no timeout, empty search, elapsed
timer, attempt count, or later failure can promote a Razorpay intent back to a
create-capable state. Empty search after the fence cannot distinguish a crash
before POST from a created Order that is temporarily absent from search.
"""

from __future__ import annotations

from datetime import datetime

from apps.api.db.models import OutboxEventRow, PaymentIntentRow
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, ReasonCode, as_utc, utcnow
from packages.schemas.payment import PaymentIntentState
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import append_event
from services.payment_executor.executor import (
    ACTOR,
    DispatchResult,
    apply_payment_transition,
    apply_provider_payment,
    lock_payment_intent,
    provider_evidence_payload,
    record_payment_attempt,
    remember_provider_ambiguity,
    validate_provider_payment,
    validate_provider_route,
    verify_intent_authorization_before_provider_io,
)
from services.payment_executor.outbox import complete_event, reschedule_event
from services.payment_executor.providers.base import (
    PaymentProvider,
    ProviderAmbiguity,
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

    await verify_intent_authorization_before_provider_io(
        session, intent=intent, event=event, now=moment
    )
    if (
        not getattr(provider, "create_retries_are_idempotent", False)
        and intent.provider_create_fenced_at is None
    ):
        # Defensive closure for upgraded/legacy state: reconciliation can never
        # become a create-fence winner. It consumes permission before lookup,
        # commits, reloads, and remains search-only.
        await session.execute(
            update(PaymentIntentRow)
            .where(
                PaymentIntentRow.id == intent.id,
                PaymentIntentRow.provider_create_fenced_at.is_(None),
            )
            .values(provider_create_fenced_at=moment)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        intent = await lock_payment_intent(session, intent.id)
        validate_provider_route(intent=intent, provider=provider)
        current = PaymentIntentState(intent.state)
        if is_terminal(current):
            await complete_event(session, event=event, now=moment)
            return DispatchResult(
                state=current,
                provider_called=False,
                retry_scheduled=False,
            )
        await verify_intent_authorization_before_provider_io(
            session, intent=intent, event=event, now=moment
        )
    try:
        payment = await provider.get_payment(
            provider_payment_id=intent.provider_payment_id,
            idempotency_key=intent.idempotency_key,
        )
    except ProviderError as error:
        # Could not ask. Uncertainty is unchanged — which is the correct
        # outcome, not a failure to record. Try again later.
        if isinstance(error, ProviderAmbiguity):
            remember_provider_ambiguity(intent, now=moment)
            if current != PaymentIntentState.PROVIDER_PENDING:
                await apply_payment_transition(
                    session,
                    intent=intent,
                    target=PaymentIntentState.PROVIDER_PENDING,
                    event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
                    payload={
                        "provider": intent.provider,
                        "provider_ambiguity_observed": True,
                        "replacement_create_permitted": False,
                        "detail": error.detail,
                    },
                    reason_code=ReasonCode.PROVIDER_AMBIGUITY.value,
                )
                current = PaymentIntentState.PROVIDER_PENDING
            else:
                await session.flush()
                await append_event(
                    session,
                    mission_id=intent.mission_id,
                    event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
                    actor=ACTOR,
                    payload={
                        "payment_intent_id": str(intent.id),
                        "state": current.value,
                        "provider": intent.provider,
                        "provider_ambiguity_observed": True,
                        "replacement_create_permitted": False,
                        "detail": error.detail,
                        "reason_code": ReasonCode.PROVIDER_AMBIGUITY.value,
                    },
                )
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

    if intent.provider_ambiguity_observed_at is not None:
        # A later empty/single result cannot disprove previously observed
        # multiple exact Orders. Keep the durable ambiguity and never adopt,
        # settle, or restore create permission automatically.
        if current != PaymentIntentState.PROVIDER_PENDING:
            await apply_payment_transition(
                session,
                intent=intent,
                target=PaymentIntentState.PROVIDER_PENDING,
                event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
                payload={
                    "provider": intent.provider,
                    "provider_ambiguity_observed": True,
                    "replacement_create_permitted": False,
                    "resolution": "operator_review",
                },
                reason_code=ReasonCode.PROVIDER_AMBIGUITY.value,
            )
            current = PaymentIntentState.PROVIDER_PENDING
        else:
            remember_provider_ambiguity(intent, now=moment)
            await session.flush()
        retried = await reschedule_event(
            session,
            event=event,
            reason="known provider ambiguity remains unresolved",
            now=moment,
        )
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.PAYMENT_RECONCILED,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "provider": intent.provider,
                "reason_code": ReasonCode.PROVIDER_AMBIGUITY.value,
                "provider_ambiguity_observed": True,
                "current_search_result": (
                    "no_exact_match" if payment is None else "one_exact_candidate"
                ),
                **({} if payment is None else provider_evidence_payload(payment)),
                "candidate_adopted": False,
                "replacement_create_permitted": False,
                "manual_recovery_required": True,
            },
        )
        return DispatchResult(
            state=current,
            provider_called=True,
            retry_scheduled=retried,
        )

    if payment is None:
        if intent.provider_payment_id is not None:
            # A provider reference was already durably observed. Losing the
            # ability to fetch it (retention window, provider inconsistency,
            # temporary index lag) is not evidence that it never existed, so it
            # can NEVER license a replacement Order. Keep uncertainty and poll
            # until the retry budget dead-letters for operator attention.
            retried = await reschedule_event(
                session,
                event=event,
                reason="linked provider reference was not found",
                now=moment,
            )
            await append_event(
                session,
                mission_id=intent.mission_id,
                event_type=EventType.PAYMENT_RECONCILED,
                actor=ACTOR,
                payload={
                    "payment_intent_id": str(intent.id),
                    "provider": intent.provider,
                    "provider_payment_id": intent.provider_payment_id,
                    "reason_code": ReasonCode.PROVIDER_PAYMENT_NOT_FOUND.value,
                    "linked_provider_reference_unresolved": True,
                    "replacement_create_permitted": False,
                },
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
                    "reason_code": ReasonCode.PROVIDER_PAYMENT_NOT_FOUND.value,
                    "phase": "linked-reference-reconciliation",
                },
            )
            return DispatchResult(
                state=current,
                provider_called=True,
                retry_scheduled=retried,
            )
        if intent.provider_create_fenced_at is not None and not getattr(
            provider, "create_retries_are_idempotent", False
        ):
            # The fence is permanent. An empty search may mean the process died
            # before POST, or that Razorpay accepted an Order which is not yet
            # visible. Neither observation permits PACTRA to choose between
            # them, so availability yields to duplicate-payment safety.
            if current != PaymentIntentState.PROVIDER_PENDING:
                await apply_payment_transition(
                    session,
                    intent=intent,
                    target=PaymentIntentState.PROVIDER_PENDING,
                    event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
                    payload={
                        "provider": intent.provider,
                        "provider_create_fenced": True,
                        "provider_payment_may_exist": True,
                        "replacement_create_permitted": False,
                        "resolution": "reconciliation_or_operator_review",
                    },
                    reason_code=ReasonCode.PROVIDER_CREATE_FENCED.value,
                )
                current = PaymentIntentState.PROVIDER_PENDING
            else:
                intent.last_reason_code = ReasonCode.PROVIDER_CREATE_FENCED.value
                await session.flush()
            retried = await reschedule_event(
                session,
                event=event,
                reason="fenced create has no visible provider Order",
                now=moment,
            )
            await append_event(
                session,
                mission_id=intent.mission_id,
                event_type=EventType.PAYMENT_RECONCILED,
                actor=ACTOR,
                payload={
                    "payment_intent_id": str(intent.id),
                    "provider": intent.provider,
                    "reason_code": ReasonCode.PROVIDER_CREATE_FENCED.value,
                    "provider_search_found_no_match": True,
                    "provider_create_fenced": True,
                    "replacement_create_permitted": False,
                    "manual_recovery_may_be_required": True,
                },
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
                    "reason_code": ReasonCode.PROVIDER_CREATE_FENCED.value,
                    "phase": "fenced-create-reconciliation",
                },
            )
            return DispatchResult(
                state=current,
                provider_called=True,
                retry_scheduled=retried,
            )
        return await _resolve_no_provider_payment(
            session, intent=intent, event=event, now=moment, current=current
        )

    try:
        # QUEUED + fence is the intentional post-fence/pre-POST crash state.
        # Provider evidence makes PROCESSING/PAYMENT_ATTEMPTED truthful and
        # gives apply_provider_payment a legal path to any provider outcome.
        validate_provider_payment(
            intent=intent,
            payment=payment,
            require_idempotency_key=intent.provider_payment_id is None,
        )
        if current in {
            PaymentIntentState.QUEUED,
            PaymentIntentState.FAILED_RETRYABLE,
        }:
            await record_payment_attempt(
                session,
                intent=intent,
                provider_create_invoked=False,
                recovered_existing=True,
            )
            current = PaymentIntentState.PROCESSING
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
            **provider_evidence_payload(payment),
            "provider_state": payment.status.value,
            "state": state.value,
            # True whenever the provider handed back a payment it already held
            # — i.e. the lost-response case resolved onto the original payment.
            "resolved_existing_provider_payment": True,
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
    """An idempotent-create provider reports no payment for this key.

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
            "conclusion": "provider create contract makes a same-key retry idempotent",
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
