"""Reconciliation: converging an uncertain payment onto a settled answer.

The requirement is that the system converge on SUCCEEDED or FAILED_TERMINAL
"rather than remaining permanently ambiguous". These tests drive each of the
four provider answers and assert the conclusion each one licenses — including
the one that licenses a retry, which is the only route out of uncertainty that
can create a second provider payment and therefore the one that must be
gated most carefully.
"""

from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import EventType
from packages.schemas.payment import (
    OutboxEventType,
    PaymentIntentState,
    ProviderPaymentStatus,
)
from services.audit_ledger.ledger import list_events
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.outbox import pending_events_for
from services.payment_executor.providers.fake import FakePaymentProvider, FaultMode
from services.payment_executor.worker import drain, run_once
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()


async def _uncertain(sessionmaker, key: str, fault: FaultMode):
    """A payment left in PROVIDER_PENDING by a timeout."""
    provider = FakePaymentProvider()
    provider.queue_faults(fault)
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await setup.commit()
        mission_id, intent_id = mission.id, result.intent.id

    await run_once(sessionmaker, provider=provider)
    return provider, mission_id, intent_id


async def _intent(sessionmaker, intent_id):
    from apps.api.db.models import PaymentIntentRow

    async with sessionmaker() as s:
        return await s.get(PaymentIntentRow, intent_id, populate_existing=True)


# --------------------------------------------------------------------------- #
# A reconciliation event is always scheduled for an uncertain payment
# --------------------------------------------------------------------------- #
async def test_uncertainty_always_schedules_reconciliation(sessionmaker):
    """Otherwise the payment would sit ambiguous forever with nobody asking."""
    _, _, intent_id = await _uncertain(
        sessionmaker, "idem-schedules", FaultMode.TIMEOUT_AFTER_CREATE
    )
    async with sessionmaker() as s:
        pending = await pending_events_for(s, intent_id)
    assert [e.event_type for e in pending] == [OutboxEventType.PAYMENT_RECONCILE_REQUESTED.value]


# --------------------------------------------------------------------------- #
# Provider says SUCCEEDED
# --------------------------------------------------------------------------- #
async def test_reconciliation_converges_on_success(sessionmaker):
    provider, mission_id, intent_id = await _uncertain(
        sessionmaker, "idem-rec-success", FaultMode.TIMEOUT_AFTER_CREATE
    )
    original = provider.created_payments["idem-rec-success"]

    await drain(sessionmaker, provider=provider, max_events=8)

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    assert intent.state == PaymentIntentState.SUCCEEDED.value
    assert intent.provider_payment_id == original.provider_payment_id
    assert provider.payment_count_for("idem-rec-success") == 1


# --------------------------------------------------------------------------- #
# Provider says FAILED
# --------------------------------------------------------------------------- #
async def test_reconciliation_converges_on_terminal_failure(sessionmaker):
    provider, mission_id, intent_id = await _uncertain(
        sessionmaker, "idem-rec-failed", FaultMode.TIMEOUT_AFTER_CREATE
    )
    # The provider settled the payment as failed while PACTRA was in the dark.
    provider.settle("idem-rec-failed", ProviderPaymentStatus.FAILED)

    await drain(sessionmaker, provider=provider, max_events=8)

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    assert intent.state == PaymentIntentState.FAILED_TERMINAL.value

    async with sessionmaker() as s:
        types = [e.event_type for e in await list_events(s, mission_id)]
    assert EventType.PAYMENT_RECONCILED.value in types


# --------------------------------------------------------------------------- #
# Provider says PENDING
# --------------------------------------------------------------------------- #
async def test_a_still_pending_payment_is_polled_again_not_resolved(sessionmaker):
    """Guessing an outcome here would be inventing information."""
    provider, _, intent_id = await _uncertain(
        sessionmaker, "idem-rec-pending", FaultMode.TIMEOUT_AFTER_CREATE
    )
    provider.settle("idem-rec-pending", ProviderPaymentStatus.PENDING)

    await run_once(sessionmaker, provider=provider)

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    assert intent.state == PaymentIntentState.PROVIDER_PENDING.value

    async with sessionmaker() as s:
        pending = await pending_events_for(s, intent_id)
    assert pending, "an unresolved payment must still have work queued"


async def test_a_pending_payment_converges_once_the_provider_settles(sessionmaker):
    """Ambiguity is temporary, not permanent."""
    from datetime import timedelta

    from packages.schemas.domain import utcnow

    provider, _, intent_id = await _uncertain(
        sessionmaker, "idem-rec-eventual", FaultMode.TIMEOUT_AFTER_CREATE
    )
    provider.settle("idem-rec-eventual", ProviderPaymentStatus.PENDING)
    await run_once(sessionmaker, provider=provider)
    assert (await _intent(sessionmaker, intent_id)).state == (
        PaymentIntentState.PROVIDER_PENDING.value
    )

    provider.settle("idem-rec-eventual", ProviderPaymentStatus.SUCCEEDED)
    await run_once(sessionmaker, provider=provider, now=utcnow() + timedelta(seconds=60))

    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value


# --------------------------------------------------------------------------- #
# Provider says NOT FOUND — the only answer that licenses a retry
# --------------------------------------------------------------------------- #
async def test_not_found_makes_the_payment_retryable(sessionmaker):
    provider, mission_id, intent_id = await _uncertain(
        sessionmaker, "idem-rec-notfound", FaultMode.TIMEOUT_BEFORE_CREATE
    )
    assert provider.payment_count_for("idem-rec-notfound") == 0

    # Reconcile only; do not let the follow-up create run yet.
    await run_once(sessionmaker, provider=provider)

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    assert intent.state == PaymentIntentState.FAILED_RETRYABLE.value

    async with sessionmaker() as s:
        events = await list_events(s, mission_id)
    reconciled = [e for e in events if e.event_type == EventType.PAYMENT_RECONCILED.value]
    assert reconciled[-1].payload["provider_holds_no_payment"] is True

    async with sessionmaker() as s:
        pending = await pending_events_for(s, intent_id)
    assert [e.event_type for e in pending] == [OutboxEventType.PAYMENT_CREATE_REQUESTED.value]


async def test_not_found_for_an_already_linked_provider_reference_never_recreates(sessionmaker):
    """A once-observed remote object cannot be assumed never to have existed."""
    from datetime import timedelta

    from packages.schemas.domain import utcnow

    provider = FakePaymentProvider(default_fault=FaultMode.PENDING)
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-linked-not-found",
            provider="fake",
        )
        intent_id = result.intent.id
        await setup.commit()

    await run_once(sessionmaker, provider=provider)
    linked = await _intent(sessionmaker, intent_id)
    assert linked.provider_payment_id is not None
    assert len(provider.create_calls) == 1

    # Simulate a provider retention/index gap after the id was durably linked.
    provider.created_payments.clear()
    provider._by_provider_id.clear()
    await run_once(sessionmaker, provider=provider, now=utcnow() + timedelta(seconds=60))

    unresolved = await _intent(sessionmaker, intent_id)
    assert unresolved.state == PaymentIntentState.PROVIDER_PENDING.value
    assert unresolved.provider_payment_id == linked.provider_payment_id
    assert len(provider.create_calls) == 1
    async with sessionmaker() as check:
        pending = await pending_events_for(check, intent_id)
    assert [event.event_type for event in pending] == [
        OutboxEventType.PAYMENT_RECONCILE_REQUESTED.value
    ]


async def test_reconciliation_never_reopens_a_settled_payment(sessionmaker):
    """Idempotent: running it again on a terminal payment changes nothing."""
    provider, _, intent_id = await _uncertain(
        sessionmaker, "idem-rec-terminal", FaultMode.TIMEOUT_AFTER_CREATE
    )
    await drain(sessionmaker, provider=provider, max_events=8)
    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value

    from datetime import timedelta

    from packages.schemas.domain import utcnow
    from services.payment_executor.outbox import enqueue_outbox_event

    async with sessionmaker() as s:
        await enqueue_outbox_event(
            s,
            payment_intent_id=intent_id,
            event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
            available_at=utcnow(),
        )
        await s.commit()

    provider.settle("idem-rec-terminal", ProviderPaymentStatus.FAILED)
    await run_once(sessionmaker, provider=provider, now=utcnow() + timedelta(seconds=1))

    # Still SUCCEEDED. A settled payment is not re-litigated.
    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value


async def test_a_second_provider_payment_is_never_linked(sessionmaker):
    """Relinking would hide a duplicate charge, so it raises instead."""
    from apps.api.db.models import PaymentIntentRow
    from packages.schemas.payment import ProviderPayment
    from services.payment_executor.executor import link_provider_payment

    provider, _, intent_id = await _uncertain(
        sessionmaker, "idem-relink", FaultMode.TIMEOUT_AFTER_CREATE
    )
    await drain(sessionmaker, provider=provider, max_events=8)

    other = ProviderPayment(
        provider="fake",
        provider_payment_id="fake_pay_someone_elses",
        status=ProviderPaymentStatus.SUCCEEDED,
        amount_inr=3799,
        currency="INR",
    )
    async with sessionmaker() as s:
        row = await s.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert row is not None
        try:
            await link_provider_payment(s, intent=row, payment=other)
            raise AssertionError("relinking should have been refused")
        except ValueError as exc:
            assert "refusing to relink" in str(exc)
        await s.rollback()
