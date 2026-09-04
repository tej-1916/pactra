"""Crash recovery at the three dangerous boundaries.

The brief names them A, B and C. Each is simulated by stopping the process at
exactly that point — not by mocking the recovery path, but by actually leaving
the database in the state a crash would leave it in, then running the ordinary
worker and checking where the system lands.

The measurement in every case is the same and is taken from the PROVIDER, not
from PACTRA's own belief: how many provider payments exist for this idempotency
key. PACTRA claiming "one payment" while the provider holds two is precisely
the failure these tests must be able to catch.
"""

from datetime import timedelta

from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import utcnow
from packages.schemas.payment import (
    OutboxStatus,
    PaymentIntentState,
    PaymentRequest,
    ProviderPayment,
    ProviderPaymentStatus,
)
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.outbox import claim_next_event
from services.payment_executor.providers.fake import FakePaymentProvider, FaultMode
from services.payment_executor.worker import drain, process_claimed_event
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()


class NonIdempotentFakePaymentProvider(FakePaymentProvider):
    """Provider whose create endpoint does NOT deduplicate requests.

    Lookup by idempotency key still works, as required by ``PaymentProvider``.
    This exposes whether crash recovery is safe because PACTRA reconciles
    before retrying, or merely because the normal fake silently deduplicates a
    blind second create.
    """

    create_retries_are_idempotent = False

    def __init__(self) -> None:
        super().__init__()
        self.all_created_payments: list[ProviderPayment] = []

    def _record(self, request: PaymentRequest, status: ProviderPaymentStatus) -> ProviderPayment:
        payment = ProviderPayment(
            provider=self.name,
            provider_payment_id=f"non_idem_{len(self.all_created_payments) + 1}",
            status=status,
            amount_inr=request.amount_inr,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
            idempotent_replay=False,
        )
        self.all_created_payments.append(payment)
        self.created_payments[request.idempotency_key] = payment
        self._by_provider_id[payment.provider_payment_id] = request.idempotency_key
        return payment


async def _committed_intent(sessionmaker, key: str):
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
        return mission.id, result.intent.id


async def _intent(sessionmaker, intent_id):
    from apps.api.db.models import PaymentIntentRow

    async with sessionmaker() as s:
        return await s.get(PaymentIntentRow, intent_id, populate_existing=True)


# --------------------------------------------------------------------------- #
# A. Crash AFTER the DB transaction commits, BEFORE the provider call
# --------------------------------------------------------------------------- #
async def test_crash_after_commit_before_provider_call_recovers(sessionmaker):
    """The outbox exists for exactly this crash.

    The intent and its instruction are durable; nothing was sent. A worker
    starting cold must complete the payment, once.
    """
    key = "idem-crash-a"
    _, intent_id = await _committed_intent(sessionmaker, key)

    # The crash: the process ends here. Nothing has reached the provider.
    provider = FakePaymentProvider()
    assert provider.create_calls == []
    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.QUEUED.value

    # A fresh worker recovers from durable state alone.
    await drain(sessionmaker, provider=provider, max_events=8)

    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value
    assert provider.payment_count_for(key) == 1


async def test_a_crash_before_commit_leaves_nothing_to_recover(sessionmaker):
    """The mirror image: an uncommitted decision must not be half-remembered."""
    from apps.api.db.models import OutboxEventRow, PaymentIntentRow
    from sqlalchemy import func, select

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        await setup.commit()
        ids = (mission.id, authorization.authorization_id)

    async with sessionmaker() as doomed:
        await create_payment_intent(
            doomed,
            capabilities=EXECUTOR,
            mission_id=ids[0],
            authorization_id=ids[1],
            idempotency_key="idem-crash-precommit",
            provider="fake",
        )
        # The crash, before COMMIT.
        await doomed.rollback()

    provider = FakePaymentProvider()
    await drain(sessionmaker, provider=provider, max_events=8)

    async with sessionmaker() as s:
        assert await s.scalar(select(func.count()).select_from(PaymentIntentRow)) == 0
        assert await s.scalar(select(func.count()).select_from(OutboxEventRow)) == 0
    assert provider.create_calls == []


# --------------------------------------------------------------------------- #
# B. Crash AFTER the provider succeeds, BEFORE local success is persisted
# --------------------------------------------------------------------------- #
async def test_crash_after_provider_success_before_local_persist_recovers(sessionmaker):
    """The provider moved money; PACTRA never recorded it.

    Simulated exactly: the provider records the payment and then the response
    is lost, which is indistinguishable from the process dying between the two.
    Recovery must adopt the EXISTING payment, never make a second.
    """
    key = "idem-crash-b"
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE)
    _, intent_id = await _committed_intent(sessionmaker, key)

    await drain(sessionmaker, provider=provider, max_events=1)

    # The provider holds a real payment; PACTRA holds only uncertainty.
    assert provider.payment_count_for(key) == 1
    created = provider.created_payments[key]
    intent = await _intent(sessionmaker, intent_id)
    assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
    assert intent.provider_payment_id is None

    # Recovery.
    await drain(sessionmaker, provider=provider, max_events=8)

    intent = await _intent(sessionmaker, intent_id)
    assert intent.state == PaymentIntentState.SUCCEEDED.value
    assert intent.provider_payment_id == created.provider_payment_id
    # NO DUPLICATE LOGICAL PAYMENT.
    assert provider.payment_count_for(key) == 1
    assert len(provider.created_payments) == 1


async def test_a_rolled_back_success_is_re_derived_not_lost(sessionmaker):
    """A harsher variant: the provider succeeded and the local COMMIT was lost.

    The intent reverts to QUEUED. A naive retry would create a second payment;
    provider-side idempotency on the same key returns the original instead, and
    the intent links to that one.
    """
    key = "idem-crash-b2"
    provider = FakePaymentProvider()
    _, intent_id = await _committed_intent(sessionmaker, key)

    async with sessionmaker() as crashing:
        event = await claim_next_event(crashing, worker_id="doomed")
        assert event is not None
        await process_claimed_event(crashing, provider=provider, event=event)
        # The provider has now created the payment...
        assert provider.payment_count_for(key) == 1
        # ...and the process dies before COMMIT.
        await crashing.rollback()

    original = provider.created_payments[key]
    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.QUEUED.value

    await drain(sessionmaker, provider=provider, max_events=8)

    intent = await _intent(sessionmaker, intent_id)
    assert intent.state == PaymentIntentState.SUCCEEDED.value
    assert intent.provider_payment_id == original.provider_payment_id
    assert provider.payment_count_for(key) == 1
    assert len(provider.created_payments) == 1


async def test_rolled_back_success_is_safe_without_provider_create_idempotency(sessionmaker):
    """Recovery looks up the key before a second create.

    The provider creates a new payment on every create call, so provider-side
    idempotency cannot hide a blind-retry bug.  After the local transaction is
    rolled back, the next worker must discover the first payment and adopt it.
    """
    key = "idem-crash-non-idempotent-provider"
    provider = NonIdempotentFakePaymentProvider()
    _, intent_id = await _committed_intent(sessionmaker, key)

    async with sessionmaker() as crashing:
        event = await claim_next_event(crashing, worker_id="doomed")
        assert event is not None
        await process_claimed_event(crashing, provider=provider, event=event)
        assert len(provider.all_created_payments) == 1
        await crashing.rollback()

    original = provider.all_created_payments[0]
    await drain(
        sessionmaker,
        provider=provider,
        max_events=8,
        now=utcnow() + timedelta(seconds=45),
    )

    intent = await _intent(sessionmaker, intent_id)
    assert intent.state == PaymentIntentState.SUCCEEDED.value
    assert intent.provider_payment_id == original.provider_payment_id
    assert provider.create_calls == [key]
    assert len(provider.all_created_payments) == 1


# --------------------------------------------------------------------------- #
# C. Crash AFTER local state updates, BEFORE the outbox acknowledgement
# --------------------------------------------------------------------------- #
async def test_crash_before_outbox_acknowledgement_recovers(sessionmaker):
    """The event stays IN_PROGRESS with a lease nobody will release.

    Recovery is the lease lapsing. Re-handling must be a no-op because the
    payment is already terminal — the executor short-circuits before the
    provider is touched at all.
    """
    key = "idem-crash-c"
    provider = FakePaymentProvider()
    _, intent_id = await _committed_intent(sessionmaker, key)
    start = utcnow()

    async with sessionmaker() as s:
        event = await claim_next_event(s, worker_id="dying", now=start)
        assert event is not None
        await process_claimed_event(s, provider=provider, event=event)
        # Undo only the acknowledgement, leaving the payment recorded — the
        # exact state a crash between the two would produce.
        event.status = OutboxStatus.IN_PROGRESS.value
        event.processed_at = None
        await s.commit()
        event_id = event.id

    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value
    calls_before = len(provider.create_calls)

    # The lease lapses and another worker picks the event up.
    later = start + timedelta(seconds=45)
    async with sessionmaker() as s:
        reclaimed = await claim_next_event(s, worker_id="recovering", now=later)
        assert reclaimed is not None
        assert reclaimed.id == event_id
        await process_claimed_event(s, provider=provider, event=reclaimed, now=later)
        await s.commit()

    # The provider was never called again, and nothing changed.
    assert len(provider.create_calls) == calls_before
    assert provider.payment_count_for(key) == 1
    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value

    async with sessionmaker() as s:
        from apps.api.db.models import OutboxEventRow

        final = await s.get(OutboxEventRow, event_id, populate_existing=True)
        assert final is not None
        assert final.status == OutboxStatus.PROCESSED.value


async def test_repeated_crashes_still_yield_one_payment(sessionmaker):
    """Crash, recover, crash again. The invariant must survive repetition.

    A guarantee that holds for one crash but not for three is not a guarantee.
    """
    key = "idem-crash-repeat"
    provider = FakePaymentProvider()
    provider.queue_faults(
        FaultMode.TIMEOUT_BEFORE_CREATE,
        FaultMode.TRANSIENT_FAILURE,
        FaultMode.TIMEOUT_AFTER_CREATE,
    )
    _, intent_id = await _committed_intent(sessionmaker, key)

    now = utcnow()
    for offset in (0, 1, 5, 20, 60, 180, 400, 900):
        await drain(
            sessionmaker, provider=provider, max_events=6, now=now + timedelta(seconds=offset)
        )

    intent = await _intent(sessionmaker, intent_id)
    assert intent.state == PaymentIntentState.SUCCEEDED.value
    assert provider.payment_count_for(key) == 1
    assert len(provider.created_payments) == 1


async def test_a_worker_exception_returns_the_event_to_the_queue(sessionmaker):
    """A handler that blows up must not silently drop the payment.

    The failure is recorded in a SEPARATE transaction, because the one that was
    doing the work has been rolled back.
    """
    import pytest
    from apps.api.db.models import OutboxEventRow
    from services.payment_executor.worker import run_once

    key = "idem-worker-boom"
    _, intent_id = await _committed_intent(sessionmaker, key)

    class ExplodingProvider(FakePaymentProvider):
        async def create_payment(self, request):
            raise RuntimeError("catastrophic provider client bug")

    with pytest.raises(RuntimeError):
        await run_once(sessionmaker, provider=ExplodingProvider())

    async with sessionmaker() as s:
        from sqlalchemy import select

        event = (
            await s.execute(
                select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == intent_id)
            )
        ).scalar_one()
        assert event.status == OutboxStatus.PENDING.value
        assert event.attempts == 1
        assert "catastrophic" in (event.last_error or "")

    # And the payment is still completable afterwards.
    await drain(
        sessionmaker,
        provider=FakePaymentProvider(),
        max_events=6,
        now=utcnow() + timedelta(seconds=120),
    )
    assert (await _intent(sessionmaker, intent_id)).state == PaymentIntentState.SUCCEEDED.value


async def test_a_permanently_failing_handler_eventually_dead_letters(sessionmaker):
    """The retry budget must actually be spent.

    Regression guard for a subtle bug: the claim increments ``attempts``, but a
    handler that throws rolls that increment back with everything else. If the
    recovery path did not re-apply it, the budget would reset on every pass and
    the worker would retry forever.
    """

    from apps.api.db.models import OutboxEventRow
    from services.payment_executor.worker import run_once
    from sqlalchemy import select

    key = "idem-deadletter-loop"
    _, intent_id = await _committed_intent(sessionmaker, key)

    async with sessionmaker() as s:
        event = (
            await s.execute(
                select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == intent_id)
            )
        ).scalar_one()
        event.max_attempts = 3
        await s.commit()

    class ExplodingProvider(FakePaymentProvider):
        async def create_payment(self, request):
            raise RuntimeError("always broken")

    now = utcnow()
    for offset in (0, 10, 60, 300, 900, 1800):
        try:
            await run_once(
                sessionmaker,
                provider=ExplodingProvider(),
                now=now + timedelta(seconds=offset),
            )
        except RuntimeError:
            pass

    async with sessionmaker() as s:
        event = (
            await s.execute(
                select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == intent_id)
            )
        ).scalar_one()
        assert event.status == OutboxStatus.FAILED.value
        assert event.attempts >= event.max_attempts

    # Dead-lettering stops the retry loop; it does NOT declare the payment
    # failed, because nothing verified that it failed.
    assert (await _intent(sessionmaker, intent_id)).state != (
        PaymentIntentState.FAILED_TERMINAL.value
    )
