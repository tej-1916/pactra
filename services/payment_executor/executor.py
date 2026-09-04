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
scheduled.

Providers with a genuine idempotent-create contract may retry only after a
successful not-found lookup. Razorpay has no verified contract of that kind:
PACTRA commits a one-way local fence before its sole create call, and an empty
post-fence lookup can never authorize another create.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from apps.api.db.models import AuthorizationRow, Mission, OutboxEventRow, PaymentIntentRow
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, MissionState, ReasonCode, as_utc, utcnow
from packages.schemas.payment import (
    OutboxEventType,
    PaymentIntentState,
    PaymentRequest,
    ProviderPayment,
    ProviderPaymentStatus,
    provider_status_to_state,
)
from sqlalchemy import CursorResult, select, update
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
from services.security_kernel.authorization import (
    AuthorizationNotFound,
    TransactionBindingFailure,
    verify_authorization_for_payment,
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
    # The durable state already records this code. Carry the same value into the
    # source audit event so a Decision Trace can explain the transition without
    # consulting mutable live rows or inventing a reason later.
    #
    # The key is written even when the code is None, because this transition
    # CLEARED the reason on the intent row and replay has to be able to see
    # that. Omitting it would make "no reason any more" indistinguishable from
    # "this event says nothing about the reason", and a mission that failed
    # retryably and then succeeded would replay as still carrying the failure.
    #
    # Written LAST so the argument wins over any `reason_code` a caller also put
    # in `payload`: the event must state the same reason the intent row records,
    # and the argument is what was written there.
    event_payload = {
        "payment_intent_id": str(intent.id),
        "state": target.value,
        **payload,
        "reason_code": reason_code,
    }
    await append_event(
        session,
        mission_id=intent.mission_id,
        event_type=event_type,
        actor=ACTOR,
        payload=event_payload,
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

    def assign_once(attribute: str, value: str | None, label: str) -> None:
        if value is None:
            return
        existing = getattr(intent, attribute)
        if existing is None:
            setattr(intent, attribute, value)
        elif existing != value:
            raise ProviderPaymentMismatch(
                intent.provider,
                f"intent already records {label}={existing!r}; refusing to relink to {value!r}",
            )

    assign_once("provider_payment_id", payment.provider_payment_id, "provider reference")
    assign_once("provider_order_id", payment.provider_order_id, "provider order id")
    assign_once("provider_receipt", payment.provider_receipt, "provider receipt")
    # Only a captured/successful provider answer makes a pay_... id the durable
    # settlement identity. Failed Checkout attempts have their own ids too, but
    # those belong in webhook evidence and must not block a later successful
    # attempt on the same Razorpay Order.
    if payment.status is ProviderPaymentStatus.SUCCEEDED:
        assign_once(
            "provider_transaction_id",
            payment.provider_transaction_id,
            "provider transaction id",
        )
    if payment.provider_status is not None:
        intent.provider_status = payment.provider_status
    if payment.provider_attempts is not None:
        intent.provider_attempts = max(intent.provider_attempts or 0, payment.provider_attempts)
    await session.flush()


def provider_evidence_payload(payment: ProviderPayment) -> dict[str, str | int]:
    """Allow-list safe provider evidence for audit payloads."""
    evidence: dict[str, str | int | None] = {
        "provider_payment_id": payment.provider_payment_id,
        "provider_order_id": payment.provider_order_id,
        "provider_transaction_id": payment.provider_transaction_id,
        "provider_receipt": payment.provider_receipt,
        "provider_status": payment.provider_status,
        "provider_attempts": payment.provider_attempts,
    }
    return {key: value for key, value in evidence.items() if value is not None}


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


async def verify_intent_authorization_before_provider_io(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    now: datetime,
) -> None:
    """Re-verify proof and full transaction binding immediately before I/O."""
    authorization = await session.get(
        AuthorizationRow,
        intent.authorization_id,
        populate_existing=True,
    )
    if authorization is None:  # pragma: no cover - FK normally prevents this
        raise AuthorizationNotFound(intent.authorization_id, "authorization no longer exists")
    transaction = await verify_authorization_for_payment(
        session,
        row=authorization,
        expected_status=AuthorizationStatus.CONSUMED,
        now=now,
    )
    mismatches: list[str] = []
    if authorization.mission_id != intent.mission_id:
        mismatches.append("mission_id")
    if authorization.authorization_id != intent.authorization_id:
        mismatches.append("authorization_id")
    if authorization.transaction_digest != intent.transaction_digest:
        mismatches.append("transaction_digest")
    if transaction.merchant_id != intent.merchant_id:
        mismatches.append("merchant_id")
    if transaction.amount_inr != intent.amount_inr:
        mismatches.append("amount_inr")
    if transaction.currency != intent.currency:
        mismatches.append("currency")
    if event.payment_intent_id != intent.id:
        mismatches.append("outbox.payment_intent_id")
    if mismatches:
        raise TransactionBindingFailure(
            authorization.authorization_id,
            "durable payment intent disagrees with authorization: " + ", ".join(mismatches),
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
                **provider_evidence_payload(payment),
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
                **provider_evidence_payload(payment),
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
                **provider_evidence_payload(payment),
                "provider_state": payment.status.value,
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
    observed_reason_code = reason_code
    if (
        reason_code == ReasonCode.PROVIDER_AMBIGUITY.value
        or intent.provider_ambiguity_observed_at is not None
    ):
        remember_provider_ambiguity(intent, now=now)
        reason_code = ReasonCode.PROVIDER_AMBIGUITY.value
    if timed_out:
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.PAYMENT_PROVIDER_TIMEOUT,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "reason_code": observed_reason_code,
                "provider": intent.provider,
                "detail": detail,
                "provider_ambiguity_remains": (intent.provider_ambiguity_observed_at is not None),
            },
        )
    payload = {
        "provider": intent.provider,
        # Said plainly, because this is the whole point of the state.
        "provider_payment_may_exist": True,
        "resolution": "reconciliation",
        "provider_create_fenced": intent.provider_create_fenced_at is not None,
        "provider_ambiguity_observed": intent.provider_ambiguity_observed_at is not None,
        "replacement_create_permitted": False
        if intent.provider_create_fenced_at is not None
        else None,
        "detail": detail,
    }
    current = PaymentIntentState(intent.state)
    if current == PaymentIntentState.PROVIDER_PENDING:
        intent.last_reason_code = reason_code
        await session.flush()
        await append_event(
            session,
            mission_id=intent.mission_id,
            event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(intent.id),
                "state": PaymentIntentState.PROVIDER_PENDING.value,
                **payload,
                "reason_code": reason_code,
            },
        )
    else:
        await apply_payment_transition(
            session,
            intent=intent,
            target=PaymentIntentState.PROVIDER_PENDING,
            event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
            payload=payload,
            reason_code=reason_code,
        )
    await enqueue_outbox_event(
        session,
        payment_intent_id=intent.id,
        event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
        payload={"idempotency_key": intent.idempotency_key},
        available_at=now,
    )


def remember_provider_ambiguity(intent: PaymentIntentRow, *, now: datetime) -> None:
    """Persist the first observed multiple-match fact without ever clearing it."""
    if intent.provider_ambiguity_observed_at is None:
        intent.provider_ambiguity_observed_at = now
    intent.last_reason_code = ReasonCode.PROVIDER_AMBIGUITY.value


async def record_payment_attempt(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    provider_create_invoked: bool,
    recovered_existing: bool = False,
) -> None:
    """Record execution only after provider evidence or create invocation."""
    current = PaymentIntentState(intent.state)
    if current == PaymentIntentState.FAILED_RETRYABLE:
        assert_payment_transition(current, PaymentIntentState.QUEUED)
        intent.state = PaymentIntentState.QUEUED.value
        current = PaymentIntentState.QUEUED
    if current == PaymentIntentState.PROCESSING:
        return
    if current != PaymentIntentState.QUEUED:
        return
    await apply_payment_transition(
        session,
        intent=intent,
        target=PaymentIntentState.PROCESSING,
        event_type=EventType.PAYMENT_ATTEMPTED,
        payload={
            "provider": intent.provider,
            "attempt": intent.attempts + 1,
            "provider_create_invoked": provider_create_invoked,
            "recovered_existing_provider_payment": recovered_existing,
        },
    )
    intent.attempts += 1
    await session.flush()


async def _finish_existing_before_create(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    existing: ProviderPayment,
    now: datetime,
) -> DispatchResult:
    if intent.provider_ambiguity_observed_at is not None:
        await _mark_uncertain(
            session,
            intent=intent,
            detail=(
                "one Order is currently visible, but multiple exact Orders were observed "
                "previously; automatic adoption remains prohibited"
            ),
            now=now,
            reason_code=ReasonCode.PROVIDER_AMBIGUITY.value,
            timed_out=False,
        )
        await complete_event(session, event=event, now=now)
        return DispatchResult(
            state=PaymentIntentState.PROVIDER_PENDING,
            provider_called=True,
            retry_scheduled=True,
        )
    try:
        # A matching receipt is only candidate evidence. Validate the provider's
        # transaction fields before recording PAYMENT_ATTEMPTED.
        validate_provider_payment(
            intent=intent,
            payment=existing,
            require_idempotency_key=True,
        )
        await record_payment_attempt(
            session,
            intent=intent,
            provider_create_invoked=False,
            recovered_existing=True,
        )
        state = await apply_provider_payment(session, intent=intent, payment=existing, now=now)
    except ProviderPaymentMismatch as mismatch:
        await _mark_uncertain(
            session,
            intent=intent,
            detail=mismatch.detail,
            now=now,
            reason_code=mismatch.reason_code,
            timed_out=False,
        )
        await complete_event(session, event=event, now=now)
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
            **provider_evidence_payload(existing),
            "state": state.value,
            "recovered_before_create": True,
            "provider_create_fenced": intent.provider_create_fenced_at is not None,
        },
    )
    if state == PaymentIntentState.PROVIDER_PENDING:
        await enqueue_outbox_event(
            session,
            payment_intent_id=intent.id,
            event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
            payload={"idempotency_key": intent.idempotency_key},
            available_at=now,
        )
    await complete_event(session, event=event, now=now)
    return DispatchResult(
        state=state,
        provider_called=True,
        retry_scheduled=state == PaymentIntentState.PROVIDER_PENDING,
    )


async def _recover_fenced_create(
    session: AsyncSession,
    *,
    provider: PaymentProvider,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    now: datetime,
) -> DispatchResult:
    """Search/reconcile a fenced intent without any path to create."""
    await verify_intent_authorization_before_provider_io(
        session, intent=intent, event=event, now=now
    )
    try:
        existing = await provider.get_payment(idempotency_key=intent.idempotency_key)
    except ProviderError as lookup_error:
        await _mark_uncertain(
            session,
            intent=intent,
            detail=f"fenced create recovery lookup failed: {lookup_error.detail}",
            now=now,
            reason_code=lookup_error.reason_code,
            timed_out=isinstance(lookup_error, ProviderTimeout),
        )
        await complete_event(session, event=event, now=now)
        return DispatchResult(
            state=PaymentIntentState.PROVIDER_PENDING,
            provider_called=True,
            retry_scheduled=True,
        )
    if existing is not None:
        return await _finish_existing_before_create(
            session,
            intent=intent,
            event=event,
            existing=existing,
            now=now,
        )
    await _mark_uncertain(
        session,
        intent=intent,
        detail="create permission is fenced and receipt search found no Order",
        now=now,
        reason_code=ReasonCode.PROVIDER_CREATE_FENCED.value,
        timed_out=False,
    )
    await complete_event(session, event=event, now=now)
    return DispatchResult(
        state=PaymentIntentState.PROVIDER_PENDING,
        provider_called=True,
        retry_scheduled=True,
    )


async def acquire_provider_create_fence(
    session: AsyncSession,
    *,
    intent: PaymentIntentRow,
    now: datetime,
) -> bool:
    """Commit the one-way create-permission CAS and report whether it won."""
    fence_result = await session.execute(
        update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent.id,
            PaymentIntentRow.state == PaymentIntentState.QUEUED.value,
            PaymentIntentRow.provider_create_fenced_at.is_(None),
        )
        .values(provider_create_fenced_at=now)
        .execution_options(synchronize_session=False)
    )
    fence_acquired = isinstance(fence_result, CursorResult) and fence_result.rowcount == 1
    await session.commit()
    return fence_acquired


async def dispatch_create(
    session: AsyncSession,
    *,
    capabilities: CapabilitySet,
    provider: PaymentProvider,
    intent: PaymentIntentRow,
    event: OutboxEventRow,
    now: datetime | None = None,
) -> DispatchResult:
    """Handle one create instruction under the provider's retry contract."""
    enforce_registered(capabilities, Capability.PAYMENT_EXECUTE)
    intent = await lock_payment_intent(session, intent.id)
    moment = as_utc(now or utcnow())
    current = PaymentIntentState(intent.state)
    validate_provider_route(intent=intent, provider=provider)

    if is_terminal(current):
        await complete_event(session, event=event, now=moment)
        return DispatchResult(state=current, provider_called=False, retry_scheduled=False)

    create_retries_are_idempotent = getattr(provider, "create_retries_are_idempotent", False)

    # A pre-existing fence wins over every non-terminal state. This invocation
    # did not acquire it, so it can only search/reconcile and can never create.
    if not create_retries_are_idempotent and intent.provider_create_fenced_at is not None:
        return await _recover_fenced_create(
            session,
            provider=provider,
            intent=intent,
            event=event,
            now=moment,
        )

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

    # For non-idempotent create, consume permission BEFORE the first provider
    # lookup. Only this compare-and-set winner can proceed toward the possible
    # initial POST. The committed timestamp says nothing about provider I/O.
    await verify_intent_authorization_before_provider_io(
        session, intent=intent, event=event, now=moment
    )
    if not create_retries_are_idempotent:
        fence_acquired = await acquire_provider_create_fence(
            session,
            intent=intent,
            now=moment,
        )

        intent = await lock_payment_intent(session, intent.id)
        validate_provider_route(intent=intent, provider=provider)
        if intent.provider_create_fenced_at is None:  # pragma: no cover - DB invariant check
            raise RuntimeError("provider create fence was not durable")
        if not fence_acquired or PaymentIntentState(intent.state) != PaymentIntentState.QUEUED:
            return await _recover_fenced_create(
                session,
                provider=provider,
                intent=intent,
                event=event,
                now=moment,
            )

        # The fence commit is a transaction boundary. Re-verify before the
        # post-fence receipt search so no provider I/O trusts stale authority.
        await verify_intent_authorization_before_provider_io(
            session, intent=intent, event=event, now=moment
        )

    request = PaymentRequest(
        idempotency_key=intent.idempotency_key,
        amount_inr=intent.amount_inr,
        currency=intent.currency,
        merchant_id=intent.merchant_id,
        transaction_digest_prefix=intent.transaction_digest[:DIGEST_LOG_PREFIX],
    )

    # Deterministic-receipt preflight. For Razorpay the one-way fence is already
    # durable. Failure cannot fall through; one match is validated/adopted and
    # multiple exact matches persist monotonic provider ambiguity.
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
        return await _finish_existing_before_create(
            session,
            intent=intent,
            event=event,
            existing=existing,
            now=moment,
        )

    # Re-check immediately before create I/O. For Razorpay, this invocation is
    # still the sole fence winner; every other invocation returned through the
    # search-only recovery path above.
    await verify_intent_authorization_before_provider_io(
        session, intent=intent, event=event, now=moment
    )

    payment: ProviderPayment | None = None
    create_error: ProviderError | None = None
    try:
        payment = await provider.create_payment(request)
    except (ProviderTimeout, ProviderTransientError, ProviderTerminalError) as error:
        create_error = error

    # Reaching this line proves create_payment was invoked. Only now is a
    # PAYMENT_ATTEMPTED fact justified. For Razorpay, the fence already survived
    # independently if the process died before this local transaction commits.
    intent = await lock_payment_intent(session, intent.id)
    await record_payment_attempt(
        session,
        intent=intent,
        provider_create_invoked=True,
    )

    if isinstance(create_error, ProviderTimeout):
        await _mark_uncertain(session, intent=intent, detail=create_error.detail, now=moment)
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=PaymentIntentState.PROVIDER_PENDING,
            provider_called=True,
            retry_scheduled=True,
        )
    if isinstance(create_error, ProviderTransientError):
        if not create_retries_are_idempotent:
            await _mark_uncertain(
                session,
                intent=intent,
                detail=(
                    "provider refused the fenced create transiently; automatic create retry "
                    "remains prohibited"
                ),
                now=moment,
                reason_code=create_error.reason_code,
                timed_out=False,
            )
            await complete_event(session, event=event, now=moment)
            return DispatchResult(
                state=PaymentIntentState.PROVIDER_PENDING,
                provider_called=True,
                retry_scheduled=True,
            )
        await apply_payment_transition(
            session,
            intent=intent,
            target=PaymentIntentState.FAILED_RETRYABLE,
            event_type=EventType.PAYMENT_FAILED,
            payload={"provider": intent.provider, "retryable": True},
            reason_code=ReasonCode.PROVIDER_TRANSIENT_FAILURE.value,
        )
        retried = await reschedule_event(
            session, event=event, reason=create_error.detail, now=moment
        )
        await _audit_retry(session, intent=intent, retried=retried, event=event)
        return DispatchResult(
            state=PaymentIntentState.FAILED_RETRYABLE,
            provider_called=True,
            retry_scheduled=retried,
        )
    if isinstance(create_error, ProviderTerminalError):
        await apply_payment_transition(
            session,
            intent=intent,
            target=PaymentIntentState.FAILED_TERMINAL,
            event_type=EventType.PAYMENT_FAILED,
            payload={
                "provider": intent.provider,
                "retryable": False,
                "detail": create_error.detail,
            },
            reason_code=ReasonCode.PROVIDER_TERMINAL_FAILURE.value,
        )
        await apply_mission_state(session, intent.mission_id, MissionState.PAYMENT_FAILED)
        await complete_event(session, event=event, now=moment)
        return DispatchResult(
            state=PaymentIntentState.FAILED_TERMINAL,
            provider_called=True,
            retry_scheduled=False,
        )

    assert payment is not None
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
