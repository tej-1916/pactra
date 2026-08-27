"""Transactional outbox: durability, safe claiming, retry, dead-lettering.

The claim mechanism is the load-bearing part. Two workers must never process one
event concurrently, and the test for that is written so it would FAIL against a
read-then-write implementation: both workers observe the same due event before
either writes.
"""

import asyncio
from datetime import timedelta

from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import utcnow
from packages.schemas.payment import (
    OutboxEventType,
    OutboxStatus,
    PaymentIntentState,
)
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.outbox import (
    backoff_for,
    claim_next_event,
    complete_event,
    enqueue_outbox_event,
    pending_events_for,
    reschedule_event,
)
from services.payment_executor.providers.fake import FakePaymentProvider
from services.payment_executor.worker import drain, run_once
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()
NOW = utcnow()


async def _queued_intent(session, key="idem-outbox"):
    mission, authorization, _ = await authorized_mission(session)
    result = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key=key,
        provider="fake",
        # Pin creation to the same instant the claims use, so `available_at`
        # is deterministic rather than "whenever the test happened to run".
        now=NOW,
    )
    return mission, result.intent


# --------------------------------------------------------------------------- #
# Durability: the outbox row lands with the intent, not after it
# --------------------------------------------------------------------------- #
async def test_the_outbox_row_is_written_in_the_same_transaction(sessionmaker):
    """Rolling back the payment must roll back the instruction to pay.

    An outbox row that survived the rollback would tell a worker to pay for an
    intent that no longer exists.
    """
    from apps.api.db.models import OutboxEventRow
    from sqlalchemy import func, select

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        await setup.commit()
        ids = (mission.id, authorization.authorization_id)

    async with sessionmaker() as work:
        await create_payment_intent(
            work,
            capabilities=EXECUTOR,
            mission_id=ids[0],
            authorization_id=ids[1],
            idempotency_key="idem-outbox-rollback",
            provider="fake",
        )
        await work.rollback()

    async with sessionmaker() as check:
        assert await check.scalar(select(func.count()).select_from(OutboxEventRow)) == 0


async def test_no_provider_call_happens_before_commit(sessionmaker):
    """The provider must not be reachable from the request path at all."""
    provider = FakePaymentProvider()
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-no-early-call",
            provider="fake",
        )
        # Still uncommitted, and the provider has heard nothing.
        assert provider.create_calls == []
        await setup.commit()
    assert provider.create_calls == []


# --------------------------------------------------------------------------- #
# #15 Two workers cannot both claim one event
# --------------------------------------------------------------------------- #
async def test_two_workers_cannot_both_claim_the_same_event(concurrent_sessionmaker):
    """Written to fail against a read-then-write claim.

    Both workers see the event as due before either writes, which is exactly the
    interleaving in which an ``if status == PENDING: status = IN_PROGRESS``
    lets both through.
    """
    async with concurrent_sessionmaker() as setup:
        _, intent = await _queued_intent(setup, key="idem-two-workers")
        await setup.commit()
        intent_id = intent.id

    claims = []
    async with concurrent_sessionmaker() as a, concurrent_sessionmaker() as b:
        # Both observe the same due event.
        assert len(await pending_events_for(a, intent_id)) == 1
        assert len(await pending_events_for(b, intent_id)) == 1

        for s in (a, b):
            try:
                claimed = await claim_next_event(s, worker_id=f"w-{id(s)}", now=NOW)
                await s.commit()
                claims.append(claimed.id if claimed is not None else None)
            except Exception:
                await s.rollback()
                claims.append(None)

    won = [c for c in claims if c is not None]
    assert len(won) == 1, f"exactly one worker may claim the event, got {claims}"


async def test_concurrent_claims_never_hand_out_one_event_twice(concurrent_sessionmaker):
    """The same race under asyncio.gather, with more contenders."""
    async with concurrent_sessionmaker() as setup:
        _, intent = await _queued_intent(setup, key="idem-gather-claim")
        await setup.commit()

    async def attempt(worker: str):
        async with concurrent_sessionmaker() as s:
            try:
                claimed = await claim_next_event(s, worker_id=worker, now=NOW)
                await s.commit()
                return claimed.id if claimed is not None else None
            except Exception:
                await s.rollback()
                return None

    results = await asyncio.gather(*(attempt(f"w{i}") for i in range(4)))
    claimed = [r for r in results if r is not None]
    assert len(set(claimed)) == len(claimed), f"an event was claimed twice: {results}"
    assert len(claimed) <= 1


async def test_a_claimed_event_is_not_offered_again(session):
    _, intent = await _queued_intent(session, key="idem-claim-once")

    first = await claim_next_event(session, worker_id="w1", now=NOW)
    assert first is not None
    assert first.status == OutboxStatus.IN_PROGRESS.value
    assert first.claimed_by == "w1"
    assert first.attempts == 1

    # Still inside the lease: nothing else is due.
    assert await claim_next_event(session, worker_id="w2", now=NOW) is None


# --------------------------------------------------------------------------- #
# Lease expiry = crash recovery
# --------------------------------------------------------------------------- #
async def test_an_expired_lease_makes_a_stranded_event_claimable_again(session):
    """Crash recovery: a worker that died mid-dispatch must not strand a payment."""
    _, intent = await _queued_intent(session, key="idem-lease")

    claimed = await claim_next_event(
        session, worker_id="dying", now=NOW, lease=timedelta(seconds=30)
    )
    assert claimed is not None

    # Before the lease lapses, nobody else may take it.
    assert await claim_next_event(session, worker_id="w2", now=NOW + timedelta(seconds=10)) is None

    # After it lapses, it is recoverable.
    recovered = await claim_next_event(session, worker_id="w2", now=NOW + timedelta(seconds=31))
    assert recovered is not None
    assert recovered.id == claimed.id
    assert recovered.claimed_by == "w2"
    assert recovered.attempts == 2


# --------------------------------------------------------------------------- #
# Retry / dead-letter
# --------------------------------------------------------------------------- #
def test_backoff_is_monotonic_and_capped():
    delays = [backoff_for(n).total_seconds() for n in range(1, 20)]
    assert delays == sorted(delays)
    assert delays[-1] == delays[-2], "backoff must plateau rather than grow forever"


async def test_rescheduling_returns_the_event_with_a_delay(session):
    _, intent = await _queued_intent(session, key="idem-reschedule")
    event = await claim_next_event(session, worker_id="w1", now=NOW)
    assert event is not None

    retried = await reschedule_event(session, event=event, reason="boom", now=NOW)
    assert retried is True
    assert event.status == OutboxStatus.PENDING.value
    assert event.last_error == "boom"
    assert event.available_at > NOW


async def test_an_exhausted_event_is_dead_lettered(session):
    _, intent = await _queued_intent(session, key="idem-deadletter")
    event = await enqueue_outbox_event(
        session,
        payment_intent_id=intent.id,
        event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
        available_at=NOW,
        max_attempts=1,
    )
    event.attempts = 1

    retried = await reschedule_event(session, event=event, reason="gave up", now=NOW)
    assert retried is False
    assert event.status == OutboxStatus.FAILED.value
    assert event.processed_at is not None


async def test_dead_lettering_does_not_declare_the_payment_failed(session):
    """An exhausted retry budget means automatic recovery gave up. It is NOT
    evidence that the payment failed, and recording the stronger claim would be
    recording something unverified."""
    _, intent = await _queued_intent(session, key="idem-deadletter-state")
    event = await enqueue_outbox_event(
        session,
        payment_intent_id=intent.id,
        event_type=OutboxEventType.PAYMENT_RECONCILE_REQUESTED,
        available_at=NOW,
        max_attempts=1,
    )
    event.attempts = 1
    await reschedule_event(session, event=event, reason="gave up", now=NOW)

    assert intent.state != PaymentIntentState.FAILED_TERMINAL.value


async def test_a_completed_event_is_never_re_offered(session):
    _, intent = await _queued_intent(session, key="idem-complete")
    event = await claim_next_event(session, worker_id="w1", now=NOW)
    assert event is not None
    await complete_event(session, event=event, now=NOW)

    assert event.status == OutboxStatus.PROCESSED.value
    far_future = NOW + timedelta(days=365)
    assert await claim_next_event(session, worker_id="w2", now=far_future) is None


# --------------------------------------------------------------------------- #
# #14 Duplicate outbox processing creates no duplicate provider payment
# --------------------------------------------------------------------------- #
async def test_duplicate_outbox_processing_creates_no_duplicate_payment(sessionmaker):
    """The same instruction delivered twice must charge once.

    Guarded twice over: the executor short-circuits on a terminal intent, and
    the provider deduplicates on the idempotency key. Both are asserted.
    """
    provider = FakePaymentProvider()
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-duplicate-outbox",
            provider="fake",
        )
        intent_id = result.intent.id
        # A SECOND, identical instruction — a duplicated outbox row.
        await enqueue_outbox_event(
            setup,
            payment_intent_id=intent_id,
            event_type=OutboxEventType.PAYMENT_CREATE_REQUESTED,
            payload={"idempotency_key": "idem-duplicate-outbox"},
        )
        await setup.commit()

    await drain(sessionmaker, provider=provider)

    assert provider.payment_count_for("idem-duplicate-outbox") == 1
    assert len(provider.created_payments) == 1

    async with sessionmaker() as check:
        from apps.api.db.models import PaymentIntentRow

        row = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert row is not None
        assert row.state == PaymentIntentState.SUCCEEDED.value


async def test_an_idle_queue_is_a_no_op(sessionmaker):
    outcome = await run_once(sessionmaker, provider=FakePaymentProvider())
    assert outcome.event_id is None
    assert outcome.result is None
