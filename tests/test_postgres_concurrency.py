"""PostgreSQL integration: the concurrency proofs SQLite cannot give.

WHY THIS FILE EXISTS
--------------------
SQLite serializes writers with a whole-database lock. A "concurrency" test there
runs under a regime that removes most of the concurrency, and the loser of a
race is refused by SQLite's locking rather than by the code under test. That is
safe, but it does not prove the code is safe — it proves the database prevented
the interleaving from occurring.

PostgreSQL uses row-level locks and MVCC. Two sessions genuinely interleave, the
loser genuinely blocks on the row lock, re-evaluates the WHERE clause under READ
COMMITTED, and is refused by the conditional UPDATE matching zero rows. That is
the mechanism the payment executor actually relies on, and it is the regime
production runs in.

Part 1 re-tests the PHASE 3 authorization primitive before Phase 4 trusts it.
Part 2 tests the Phase 4 races that only exist on PostgreSQL.

Every test here skips loudly if no server is reachable. A concurrency guarantee
that was not exercised must never be reported as one that was.
"""

import asyncio

import pytest
from apps.api.db.models import AuditEventRow
from packages.schemas.audit import AuditReasonCode
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import (
    payment_executor_capabilities,
    security_kernel_capabilities,
)
from packages.schemas.domain import EventType
from packages.schemas.payment import (
    OutboxStatus,
    PaymentIntentState,
    WebhookEventType,
)
from services.audit_ledger.ledger import append_event, list_events
from services.audit_ledger.replay import replay_mission
from services.audit_ledger.verify import verify_mission_chain
from services.payment_executor.intents import (
    IdempotencyConflict,
    create_payment_intent,
    find_by_idempotency_key,
)
from services.payment_executor.outbox import claim_next_event
from services.payment_executor.providers.fake import (
    FakePaymentProvider,
    FaultMode,
    webhook_body,
)
from services.payment_executor.webhooks import handle_webhook
from services.payment_executor.worker import drain
from services.security_kernel.authorization import (
    AuthorizationFailure,
    AuthorizationReplayDetected,
    activate_authorization,
    consume_authorization,
    generate_nonce,
    issue_authorization,
    load_authorization,
)
from sqlalchemy import func, select, update
from tests.conftest import FIXED_EXPIRY, approved_transaction, authorized_mission, make_mission

pytestmark = pytest.mark.postgres

KERNEL = security_kernel_capabilities()
EXECUTOR = payment_executor_capabilities()


# =========================================================================== #
# PART 1 — Phase 3 authorization concurrency, RE-TESTED on PostgreSQL
# =========================================================================== #
async def _active_authorization(pg_sessionmaker):
    async with pg_sessionmaker() as setup:
        mission = await make_mission(setup)
        txn = approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce())
        row = await issue_authorization(
            setup, capabilities=KERNEL, mission_id=mission.id, transaction=txn
        )
        await activate_authorization(setup, authorization_id=row.authorization_id)
        await setup.commit()
        return mission.id, row.authorization_id, txn


async def test_pg_two_racing_requests_cannot_both_consume(pg_sessionmaker):
    """The Phase 3 double-consume race, with EXACT semantics.

    On PostgreSQL the loser is refused by the conditional UPDATE — not by the
    database declining to let the interleaving happen — so the precise reason
    code can be asserted, which is what SQLite could not give.
    """
    _, authorization_id, txn = await _active_authorization(pg_sessionmaker)

    async with pg_sessionmaker() as a, pg_sessionmaker() as b:
        # Both observe ACTIVE before either writes.
        seen_a = await load_authorization(a, authorization_id)
        seen_b = await load_authorization(b, authorization_id)
        assert seen_a.status == AuthorizationStatus.ACTIVE.value
        assert seen_b.status == AuthorizationStatus.ACTIVE.value

        outcomes = []
        for s in (a, b):
            try:
                await consume_authorization(s, authorization_id=authorization_id, transaction=txn)
                await s.commit()
                outcomes.append("ok")
            except AuthorizationFailure as failure:
                await s.rollback()
                outcomes.append(failure.reason_code)

    assert outcomes.count("ok") == 1, f"expected exactly one winner, got {outcomes}"
    # The exact PostgreSQL semantics: the loser is told it is a replay.
    assert "AUTHORIZATION_REPLAY_DETECTED" in outcomes

    async with pg_sessionmaker() as check:
        final = await load_authorization(check, authorization_id)
        assert final.status == AuthorizationStatus.CONSUMED.value
        assert final.consumed_at is not None


async def test_pg_many_concurrent_consumers_yield_exactly_one_winner(pg_sessionmaker):
    """Eight genuinely concurrent attempts. Exactly one may win."""
    _, authorization_id, txn = await _active_authorization(pg_sessionmaker)

    async def attempt() -> str:
        async with pg_sessionmaker() as s:
            try:
                await consume_authorization(s, authorization_id=authorization_id, transaction=txn)
                await s.commit()
                return "ok"
            except Exception as exc:
                await s.rollback()
                return type(exc).__name__

    results = await asyncio.gather(*(attempt() for _ in range(8)))
    assert results.count("ok") == 1, f"more than one consumer won: {results}"

    async with pg_sessionmaker() as check:
        final = await load_authorization(check, authorization_id)
        assert final.status == AuthorizationStatus.CONSUMED.value


async def test_pg_a_stale_in_memory_copy_cannot_consume(pg_sessionmaker):
    """The decision belongs to the database, not to a loaded ORM object."""
    _, authorization_id, txn = await _active_authorization(pg_sessionmaker)

    async with pg_sessionmaker() as a:
        stale = await load_authorization(a, authorization_id)
        assert stale.status == AuthorizationStatus.ACTIVE.value

        async with pg_sessionmaker() as b:
            await consume_authorization(b, authorization_id=authorization_id, transaction=txn)
            await b.commit()

        # The in-memory copy still claims ACTIVE, and still grants nothing.
        assert stale.status == AuthorizationStatus.ACTIVE.value
        with pytest.raises(AuthorizationReplayDetected):
            await consume_authorization(a, authorization_id=authorization_id, transaction=txn)
        await a.rollback()


# =========================================================================== #
# PART 2 — Phase 4 payment concurrency
# =========================================================================== #
async def _authorized(pg_sessionmaker, **kwargs):
    async with pg_sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup, **kwargs)
        await setup.commit()
        return mission.id, authorization.authorization_id


# --------------------------------------------------------------------------- #
# #8 Concurrent same-idempotency requests -> at most ONE logical payment
# --------------------------------------------------------------------------- #
async def test_pg_concurrent_same_idempotency_key_creates_at_most_one_payment(
    pg_sessionmaker,
):
    """logical_payment_count(idempotency_key) <= 1, under genuine concurrency."""
    mission_id, authorization_id = await _authorized(pg_sessionmaker)
    from apps.api.db.models import PaymentIntentRow

    async def attempt() -> str:
        async with pg_sessionmaker() as s:
            try:
                result = await create_payment_intent(
                    s,
                    capabilities=EXECUTOR,
                    mission_id=mission_id,
                    authorization_id=authorization_id,
                    idempotency_key="idem-pg-concurrent",
                    provider="fake",
                )
                await s.commit()
                return "created" if result.created else "reused"
            except Exception as exc:
                await s.rollback()
                return type(exc).__name__

    results = await asyncio.gather(*(attempt() for _ in range(6)))

    async with pg_sessionmaker() as check:
        count = await check.scalar(
            select(func.count())
            .select_from(PaymentIntentRow)
            .where(PaymentIntentRow.idempotency_key == "idem-pg-concurrent")
        )
    assert count == 1, f"the key named {count} payments; results were {results}"
    assert results.count("created") == 1, f"more than one creator won: {results}"
    assert set(results) <= {"created", "reused"}, f"duplicate requests failed: {results}"


async def test_pg_concurrent_duplicates_consume_the_authorization_once(pg_sessionmaker):
    """The losing requests must not each burn a consume."""
    mission_id, authorization_id = await _authorized(pg_sessionmaker)

    async def attempt() -> str:
        async with pg_sessionmaker() as s:
            try:
                await create_payment_intent(
                    s,
                    capabilities=EXECUTOR,
                    mission_id=mission_id,
                    authorization_id=authorization_id,
                    idempotency_key="idem-pg-once",
                    provider="fake",
                )
                await s.commit()
                return "ok"
            except Exception as exc:
                await s.rollback()
                return type(exc).__name__

    results = await asyncio.gather(*(attempt() for _ in range(5)))
    assert results == ["ok"] * 5, f"same-key retries must reuse, got {results}"

    async with pg_sessionmaker() as check:
        row = await load_authorization(check, authorization_id)
        assert row.status == AuthorizationStatus.CONSUMED.value
        assert row.consumed_at is not None


# --------------------------------------------------------------------------- #
# #9 Two concurrent payment requests cannot both consume one authorization
# --------------------------------------------------------------------------- #
async def test_pg_two_payments_cannot_both_consume_one_authorization(pg_sessionmaker):
    """DIFFERENT idempotency keys, ONE authorization.

    The idempotency index cannot help here — the keys differ — so this is
    decided by the Phase 3 conditional UPDATE and by
    UNIQUE(payment_intents.authorization_id). Exactly one payment may exist.
    """
    mission_id, authorization_id = await _authorized(pg_sessionmaker)
    from apps.api.db.models import PaymentIntentRow

    async def attempt(key: str) -> str:
        async with pg_sessionmaker() as s:
            try:
                await create_payment_intent(
                    s,
                    capabilities=EXECUTOR,
                    mission_id=mission_id,
                    authorization_id=authorization_id,
                    idempotency_key=key,
                    provider="fake",
                )
                await s.commit()
                return "ok"
            except Exception as exc:
                await s.rollback()
                return type(exc).__name__

    results = await asyncio.gather(*(attempt(f"idem-pg-race-{i}") for i in range(4)))
    assert results.count("ok") == 1, f"more than one payment consumed it: {results}"

    async with pg_sessionmaker() as check:
        total = await check.scalar(
            select(func.count())
            .select_from(PaymentIntentRow)
            .where(PaymentIntentRow.authorization_id == authorization_id)
        )
        assert total == 1
        row = await load_authorization(check, authorization_id)
        assert row.status == AuthorizationStatus.CONSUMED.value


async def test_pg_a_conflicting_key_under_concurrency_is_still_denied(pg_sessionmaker):
    """Two different payments racing for one key: one wins, the other conflicts,
    and the loser's authorization is given back unspent."""
    mission_a, auth_a = await _authorized(pg_sessionmaker)
    mission_b, auth_b = await _authorized(pg_sessionmaker, amount_inr=8888)

    async def attempt(mission_id, authorization_id) -> str:
        async with pg_sessionmaker() as s:
            try:
                await create_payment_intent(
                    s,
                    capabilities=EXECUTOR,
                    mission_id=mission_id,
                    authorization_id=authorization_id,
                    idempotency_key="idem-pg-conflict",
                    provider="fake",
                )
                await s.commit()
                return "ok"
            except IdempotencyConflict:
                await s.rollback()
                return "IDEMPOTENCY_CONFLICT"
            except Exception as exc:
                await s.rollback()
                return type(exc).__name__

    results = await asyncio.gather(attempt(mission_a, auth_a), attempt(mission_b, auth_b))
    assert results.count("ok") == 1, f"both requests won the key: {results}"
    assert results.count("IDEMPOTENCY_CONFLICT") == 1, results

    async with pg_sessionmaker() as check:
        states = []
        for authorization_id in (auth_a, auth_b):
            row = await load_authorization(check, authorization_id)
            states.append(row.status)
    # Exactly one authorization was spent; the loser's is untouched.
    assert states.count(AuthorizationStatus.CONSUMED.value) == 1
    assert states.count(AuthorizationStatus.ACTIVE.value) == 1


# --------------------------------------------------------------------------- #
# #15 Two workers cannot both claim one outbox event (SKIP LOCKED)
# --------------------------------------------------------------------------- #
async def test_pg_two_workers_cannot_both_claim_one_event(pg_sessionmaker):
    """Exercises the PostgreSQL FOR UPDATE SKIP LOCKED claim path specifically."""
    mission_id, authorization_id = await _authorized(pg_sessionmaker)
    async with pg_sessionmaker() as setup:
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="idem-pg-claim",
            provider="fake",
        )
        await setup.commit()

    async def claim(worker: str):
        async with pg_sessionmaker() as s:
            event = await claim_next_event(s, worker_id=worker)
            await s.commit()
            return event.id if event is not None else None

    results = await asyncio.gather(*(claim(f"w{i}") for i in range(6)))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 1, f"the event was claimed {len(claimed)} times"


async def test_pg_skip_locked_lets_workers_take_different_events(pg_sessionmaker):
    """SKIP LOCKED must not serialize workers onto the head of the queue.

    Three workers and three due events: each should get one, rather than two
    blocking behind the first.
    """
    from apps.api.db.models import OutboxEventRow

    for i in range(3):
        mission_id, authorization_id = await _authorized(pg_sessionmaker)
        async with pg_sessionmaker() as setup:
            await create_payment_intent(
                setup,
                capabilities=EXECUTOR,
                mission_id=mission_id,
                authorization_id=authorization_id,
                idempotency_key=f"idem-pg-parallel-{i}",
                provider="fake",
            )
            await setup.commit()

    async def claim(worker: str):
        async with pg_sessionmaker() as s:
            event = await claim_next_event(s, worker_id=worker)
            await s.commit()
            return event.id if event is not None else None

    results = await asyncio.gather(*(claim(f"w{i}") for i in range(3)))
    claimed = [r for r in results if r is not None]
    assert len(claimed) == 3, f"workers blocked instead of skipping: {results}"
    assert len(set(claimed)) == 3, "the same event was handed out twice"

    async with pg_sessionmaker() as check:
        in_progress = await check.scalar(
            select(func.count())
            .select_from(OutboxEventRow)
            .where(OutboxEventRow.status == OutboxStatus.IN_PROGRESS.value)
        )
        assert in_progress == 3


# --------------------------------------------------------------------------- #
# End-to-end reliability on PostgreSQL
# --------------------------------------------------------------------------- #
async def test_pg_lost_response_resolves_without_a_duplicate(pg_sessionmaker):
    """The TIMEOUT_AFTER_CREATE demo, on the real database."""
    from apps.api.db.models import PaymentIntentRow

    key = "idem-pg-lost-response"
    mission_id, authorization_id = await _authorized(pg_sessionmaker)
    async with pg_sessionmaker() as setup:
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        intent_id = result.intent.id
        await setup.commit()

    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE)
    await drain(pg_sessionmaker, provider=provider, max_events=12)

    async with pg_sessionmaker() as check:
        row = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert row.state == PaymentIntentState.SUCCEEDED.value
        assert row.provider_payment_id is not None

    assert provider.payment_count_for(key) == 1
    assert len(provider.created_payments) == 1


async def test_pg_concurrent_workers_produce_one_provider_payment(pg_sessionmaker):
    """Several workers draining at once must not double-charge."""
    key = "idem-pg-workers"
    mission_id, authorization_id = await _authorized(pg_sessionmaker)
    async with pg_sessionmaker() as setup:
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await setup.commit()

    provider = FakePaymentProvider()
    await asyncio.gather(
        *(
            drain(pg_sessionmaker, provider=provider, worker_id=f"w{i}", max_events=4)
            for i in range(4)
        )
    )
    assert provider.payment_count_for(key) == 1
    assert len(provider.created_payments) == 1


async def test_pg_rollback_also_rolls_back_authorization_consumption(pg_sessionmaker):
    """The atomicity claim, on the database that will actually run it."""
    mission_id, authorization_id = await _authorized(pg_sessionmaker)

    async with pg_sessionmaker() as work:
        await create_payment_intent(
            work,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="idem-pg-rollback",
            provider="fake",
        )
        await work.rollback()

    async with pg_sessionmaker() as check:
        assert await find_by_idempotency_key(check, "idem-pg-rollback") is None
        row = await load_authorization(check, authorization_id)
        assert row.status == AuthorizationStatus.ACTIVE.value
        assert row.consumed_at is None


# --------------------------------------------------------------------------- #
# Concurrent state transitions and audit allocation
# --------------------------------------------------------------------------- #
async def test_pg_concurrent_webhooks_cannot_apply_conflicting_terminal_states(
    pg_sessionmaker,
):
    """Success and failure racing from the same pending state serialize.

    Exactly one terminal transition applies. The loser re-reads the locked row
    and is recorded as out-of-order; it can never overwrite the winner.
    """
    from apps.api.db.models import PaymentIntentRow, WebhookEventRow

    key = "idem-pg-webhook-race"
    mission_id, authorization_id = await _authorized(pg_sessionmaker)
    async with pg_sessionmaker() as setup:
        created = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        intent_id = created.intent.id
        await setup.commit()

    provider = FakePaymentProvider(default_fault=FaultMode.PENDING)
    await drain(pg_sessionmaker, provider=provider, max_events=1)
    provider_payment_id = provider.created_payments[key].provider_payment_id

    bodies = [
        webhook_body(
            event_id="evt-pg-race-success",
            event_type=WebhookEventType.PAYMENT_SUCCEEDED,
            provider_payment_id=provider_payment_id,
        ),
        webhook_body(
            event_id="evt-pg-race-failure",
            event_type=WebhookEventType.PAYMENT_FAILED,
            provider_payment_id=provider_payment_id,
        ),
    ]

    async def deliver(body: bytes):
        async with pg_sessionmaker() as session:
            outcome = await handle_webhook(
                session,
                provider=provider,
                body=body,
                signature=provider.sign(body),
            )
            await session.commit()
            return outcome

    outcomes = await asyncio.gather(*(deliver(body) for body in bodies))
    assert sum(outcome.applied for outcome in outcomes) == 1

    async with pg_sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id)
        assert intent.state in {
            PaymentIntentState.SUCCEEDED.value,
            PaymentIntentState.FAILED_TERMINAL.value,
        }
        webhook_rows = list(
            (
                await check.execute(
                    select(WebhookEventRow).where(WebhookEventRow.payment_intent_id == intent_id)
                )
            ).scalars()
        )
        assert len(webhook_rows) == 2
        assert all(row.processed_at is not None for row in webhook_rows)
        events = await list_events(check, mission_id)
        assert [event.sequence for event in events] == list(range(len(events)))


async def test_pg_concurrent_audit_appends_remain_contiguous(pg_sessionmaker):
    """The per-mission chain has one serialized sequence allocator."""
    async with pg_sessionmaker() as setup:
        mission = await make_mission(setup)
        mission_id = mission.id
        await setup.commit()

    async def append(index: int) -> None:
        async with pg_sessionmaker() as session:
            await append_event(
                session,
                mission_id=mission_id,
                event_type=EventType.PAYMENT_INTENT_REUSED,
                actor=f"concurrent-{index}",
                payload={"index": index},
            )
            await session.commit()

    await asyncio.gather(*(append(index) for index in range(8)))

    async with pg_sessionmaker() as check:
        events = await list_events(check, mission_id)
    assert len(events) == 8
    assert [event.sequence for event in events] == list(range(8))
    assert all(
        event.previous_hash == ("0" * 64 if index == 0 else events[index - 1].event_hash)
        for index, event in enumerate(events)
    )


async def test_pg_concurrently_written_chain_verifies(pg_sessionmaker):
    """8 concurrent legitimate appends produce a chain that VERIFIES.

    The test above proves the sequences come out contiguous. This one proves the
    stronger property Phase 5 depends on: the `previous_hash` links written
    under genuine row-lock contention recompute correctly, so serialization did
    not merely produce tidy numbers but a chain a verifier accepts.

    PostgreSQL is authoritative here. SQLite serializes writers with a
    whole-database lock and ignores FOR UPDATE, so a chain written "concurrently"
    there was never written concurrently at all.
    """
    async with pg_sessionmaker() as setup:
        mission = await make_mission(setup)
        mission_id = mission.id
        await setup.commit()

    async def append(index: int) -> None:
        async with pg_sessionmaker() as session:
            await append_event(
                session,
                mission_id=mission_id,
                event_type=EventType.SECURITY_VIOLATION,
                actor=f"concurrent-{index}",
                payload={"index": index, "reason_code": "AUTHORITY_ESCALATION"},
            )
            await session.commit()

    await asyncio.gather(*(append(index) for index in range(8)))

    async with pg_sessionmaker() as check:
        verification = await verify_mission_chain(check, mission_id)
        events = await list_events(check, mission_id)

    assert verification.valid is True, verification.detail
    assert verification.events_checked == 8
    assert verification.reason_code is AuditReasonCode.AUDIT_VALID
    assert [event.sequence for event in events] == list(range(8))


async def test_pg_tampering_a_concurrently_written_chain_is_detected(pg_sessionmaker):
    """Tamper evidence holds on PostgreSQL too, not only on SQLite.

    The timestamp round trip differs between the two backends — PostgreSQL
    returns timezone-aware values where SQLite returns naive ones — so a
    verifier that got the normalization right on one could still be wrong on the
    other. Running the corruption case on both closes that.
    """
    async with pg_sessionmaker() as setup:
        mission = await make_mission(setup)
        mission_id = mission.id
        for index in range(6):
            await append_event(
                setup,
                mission_id=mission_id,
                event_type=EventType.PAYMENT_ATTEMPTED,
                actor="payment-executor",
                payload={"index": index, "state": "PROCESSING"},
            )
        await setup.commit()

    async with pg_sessionmaker() as clean:
        assert (await verify_mission_chain(clean, mission_id)).valid is True

    async with pg_sessionmaker() as attacker:
        await attacker.execute(
            update(AuditEventRow)
            .where(AuditEventRow.mission_id == mission_id, AuditEventRow.sequence == 3)
            .values(payload={"index": 3, "state": "SUCCEEDED"})
            .execution_options(synchronize_session=False)
        )
        await attacker.commit()

    async with pg_sessionmaker() as check:
        verification = await verify_mission_chain(check, mission_id)
        replayed = await replay_mission(check, mission_id)

    assert verification.valid is False
    assert verification.reason_code is AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH
    assert verification.first_invalid_sequence == 3
    # And the integrity gate refuses to reconstruct from it.
    assert replayed.trusted is False
    assert replayed.state is None


async def test_pg_replay_reconstructs_a_payment_written_across_sessions(pg_sessionmaker):
    """Replay on the backend production actually runs on.

    The intent, the provider call and the settlement are each written by a
    SEPARATE session, exactly as the worker does it, so the chain being replayed
    spans transactions rather than living in one uncommitted unit of work.
    """
    provider = FakePaymentProvider()

    async with pg_sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        mission_id = mission.id
        await create_payment_intent(
            setup,
            capabilities=payment_executor_capabilities(),
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-pg-replay",
            provider="fake",
        )
        await setup.commit()

    await drain(pg_sessionmaker, provider=provider)

    async with pg_sessionmaker() as check:
        result = await replay_mission(check, mission_id)
        events = await list_events(check, mission_id)

    assert result.audit_valid is True, result.verification.detail
    assert result.trusted is True
    assert result.events_replayed == len(events)
    assert result.state is not None
    assert result.state.payment.state == PaymentIntentState.SUCCEEDED.value
    assert result.state.authorization.status == AuthorizationStatus.CONSUMED.value
    assert result.comparison is not None
    assert result.comparison.matches is True
    assert result.comparison.payment_matches is True
    assert result.comparison.authorization_matches is True
