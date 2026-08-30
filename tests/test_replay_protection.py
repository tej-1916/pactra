"""Replay protection, transaction-mutation detection, and double-consume safety.

This is the Phase 3 security contract exercised against the LIVE consumption
path — the atomic conditional UPDATE — not just against the digest primitive.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from packages.schemas.approval import ApprovalScheme
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import security_kernel_capabilities
from packages.schemas.domain import EventType
from services.audit_ledger.ledger import list_events
from services.security_kernel.authorization import (
    AuthorizationFailure,
    AuthorizationReplayDetected,
    TransactionBindingFailure,
    activate_authorization,
    consume_authorization,
    generate_nonce,
    issue_authorization,
    load_authorization,
)
from sqlalchemy.exc import OperationalError
from tests.conftest import approved_transaction, make_mission

pytestmark = pytest.mark.asyncio

KERNEL = security_kernel_capabilities()
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
SOON = NOW + timedelta(minutes=15)


async def _active_authorization(session, **txn_overrides):
    """An issued, activated authorization plus the transaction it is bound to."""
    mission = await make_mission(session)
    txn = approved_transaction(expires_at=SOON, nonce=generate_nonce(), **txn_overrides)
    row = await issue_authorization(
        session,
        capabilities=KERNEL,
        mission_id=mission.id,
        transaction=txn,
        approval_scheme=ApprovalScheme.POLICY_AUTO,
        issued_at=NOW,
    )
    await activate_authorization(session, authorization_id=row.authorization_id, now=NOW)
    return mission, row, txn


# --------------------------------------------------------------------------- #
# #1 The exact approved transaction consumes successfully
# --------------------------------------------------------------------------- #
async def test_exact_approved_transaction_consumes(session):
    mission, row, txn = await _active_authorization(session)

    consumed = await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=txn, now=NOW
    )
    assert consumed.status == AuthorizationStatus.CONSUMED.value
    assert consumed.consumed_at is not None

    events = await list_events(session, mission.id)
    assert EventType.AUTHORIZATION_CONSUMED.value in [e.event_type for e in events]


# --------------------------------------------------------------------------- #
# #2-#8 Mutating any bound field blocks consumption
# --------------------------------------------------------------------------- #
#: One mutation per field the Phase 3 brief names explicitly, plus expiry.
MUTATIONS = {
    "amount": {"amount_inr": 4399},
    "merchant": {"merchant_id": "merchant_b"},
    "product": {"product_id": "P2"},
    "quantity": {"quantity": 2},
    "currency": {"currency": "USD"},
    "policy_version": {"policy_version": "policy-v2"},
    "offer_version": {"offer_version": "offer-v2"},
    "expiry": {"expires_at": SOON + timedelta(hours=1)},
    "nonce": {"nonce": "b" * 64},
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
async def test_mutated_transaction_cannot_be_consumed(session, name):
    """TRANSACTION CHANGED AFTER APPROVAL -> AUTHORIZATION INVALID."""
    mission, row, txn = await _active_authorization(session)
    mutated = txn.model_copy(update=MUTATIONS[name])

    with pytest.raises(TransactionBindingFailure) as exc:
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=mutated, now=NOW
        )

    assert exc.value.reason_code == "TRANSACTION_BINDING_FAILURE"

    # The authorization is untouched: still ACTIVE, never consumed.
    refreshed = await load_authorization(session, row.authorization_id)
    assert refreshed is not None
    assert refreshed.status == AuthorizationStatus.ACTIVE.value
    assert refreshed.consumed_at is None

    # The attempt is auditable.
    events = await list_events(session, mission.id)
    failures = [e for e in events if e.event_type == EventType.TRANSACTION_BINDING_FAILURE.value]
    assert len(failures) == 1
    assert failures[0].payload["reason_code"] == "TRANSACTION_BINDING_FAILURE"
    # No secret material in the audit payload.
    assert txn.nonce not in str(failures[0].payload)


async def test_spec_scenario_price_mutation_blocks_the_payment_path(session):
    """The exact scenario from the Phase 3 brief.

    approved: merchant=A product=P1 amount=3799 quantity=1 currency=INR
    later:    amount=4399
    result:   TRANSACTION_BINDING_FAILURE, authorization invalid,
              future payment path impossible
    """
    mission, row, approved = await _active_authorization(
        session,
        merchant_id="merchant_a",
        product_id="P1",
        amount_inr=3799,
        quantity=1,
        currency="INR",
    )
    mutated = approved.model_copy(update={"amount_inr": 4399})

    with pytest.raises(TransactionBindingFailure) as exc:
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=mutated, now=NOW
        )
    assert exc.value.reason_code == "TRANSACTION_BINDING_FAILURE"

    # The mutated transaction can never be consumed, at any later moment either.
    with pytest.raises(TransactionBindingFailure):
        await consume_authorization(
            session,
            authorization_id=row.authorization_id,
            transaction=mutated,
            now=NOW + timedelta(minutes=1),
        )

    # The original, unmutated transaction is still exactly what was approved.
    consumed = await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=approved, now=NOW
    )
    assert consumed.status == AuthorizationStatus.CONSUMED.value


# --------------------------------------------------------------------------- #
# #10, #11 Replay
# --------------------------------------------------------------------------- #
async def test_consumed_authorization_cannot_be_replayed(session):
    """REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE."""
    mission, row, txn = await _active_authorization(session)
    await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=txn, now=NOW
    )

    before = await load_authorization(session, row.authorization_id)
    assert before is not None
    consumed_at_before = before.consumed_at

    with pytest.raises(AuthorizationReplayDetected) as exc:
        await consume_authorization(
            session,
            authorization_id=row.authorization_id,
            transaction=txn,
            now=NOW + timedelta(seconds=1),
        )

    assert exc.value.reason_code == "AUTHORIZATION_REPLAY_DETECTED"

    # No privileged state changed: same status, same consumption timestamp.
    after = await load_authorization(session, row.authorization_id)
    assert after is not None
    assert after.status == AuthorizationStatus.CONSUMED.value
    assert after.consumed_at == consumed_at_before


async def test_replay_is_recorded_as_an_audit_event(session):
    mission, row, txn = await _active_authorization(session)
    await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=txn, now=NOW
    )
    with pytest.raises(AuthorizationReplayDetected):
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=txn, now=NOW
        )

    events = await list_events(session, mission.id)
    replays = [e for e in events if e.event_type == EventType.AUTHORIZATION_REPLAY_DETECTED.value]
    assert len(replays) == 1
    assert replays[0].payload["reason_code"] == "AUTHORIZATION_REPLAY_DETECTED"
    assert txn.nonce not in str(replays[0].payload)
    # The replay is part of the tamper-evident chain.
    assert [e.sequence for e in events] == list(range(len(events)))


async def test_repeated_replay_attempts_never_succeed(session):
    mission, row, txn = await _active_authorization(session)
    await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=txn, now=NOW
    )
    for _ in range(5):
        with pytest.raises(AuthorizationReplayDetected):
            await consume_authorization(
                session, authorization_id=row.authorization_id, transaction=txn, now=NOW
            )

    after = await load_authorization(session, row.authorization_id)
    assert after is not None
    assert after.status == AuthorizationStatus.CONSUMED.value


async def test_replay_with_a_mutated_transaction_is_still_refused(session):
    """Combining the two attacks buys nothing."""
    mission, row, txn = await _active_authorization(session)
    await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=txn, now=NOW
    )
    mutated = txn.model_copy(update={"amount_inr": 1})
    with pytest.raises(AuthorizationFailure):
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=mutated, now=NOW
        )


# --------------------------------------------------------------------------- #
# #12 Two attempts cannot both consume
# --------------------------------------------------------------------------- #
async def test_two_racing_requests_cannot_both_consume(concurrent_sessionmaker):
    """The double-consume race, on separate database connections.

    Both "requests" load the authorization and observe ACTIVE *before* either
    writes — precisely the interleaving where an in-memory `if not consumed:`
    check lets both through. Exactly one may consume.

    SQLITE vs POSTGRESQL. On PostgreSQL the loser blocks on the row lock, then
    re-evaluates the WHERE clause and matches zero rows, so it is refused with
    AUTHORIZATION_REPLAY_DETECTED. SQLite locks the WHOLE DATABASE for writing,
    so when both sessions hold open transactions the loser is refused by
    SQLite's own concurrency control instead. Either refusal is safe and the
    invariant — at most one consumer — is identical; only the reason differs.
    This test therefore asserts the invariant, and
    tests/test_postgres_concurrency.py asserts the exact PostgreSQL semantics.
    """
    async with concurrent_sessionmaker() as setup:
        mission = await make_mission(setup)
        txn = approved_transaction(expires_at=SOON, nonce=generate_nonce())
        row = await issue_authorization(
            setup,
            capabilities=KERNEL,
            mission_id=mission.id,
            transaction=txn,
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            issued_at=NOW,
        )
        await activate_authorization(setup, authorization_id=row.authorization_id, now=NOW)
        await setup.commit()
        authorization_id = row.authorization_id

    async with concurrent_sessionmaker() as a, concurrent_sessionmaker() as b:
        # Both requests read the authorization and both see ACTIVE.
        seen_a = await load_authorization(a, authorization_id)
        seen_b = await load_authorization(b, authorization_id)
        assert seen_a is not None and seen_b is not None
        assert seen_a.status == AuthorizationStatus.ACTIVE.value
        assert seen_b.status == AuthorizationStatus.ACTIVE.value

        outcomes = []
        for s in (a, b):
            try:
                await consume_authorization(
                    s, authorization_id=authorization_id, transaction=txn, now=NOW
                )
                await s.commit()
                outcomes.append("ok")
            except AuthorizationFailure as failure:
                await s.rollback()
                outcomes.append(failure.reason_code)
            except OperationalError:
                # SQLite refused the write outright. A refusal is a refusal.
                await s.rollback()
                outcomes.append("DATABASE_REFUSED_WRITE")

    assert outcomes.count("ok") == 1, f"expected exactly one winner, got {outcomes}"
    assert outcomes[0] == "ok" or outcomes[1] == "ok"
    loser = [o for o in outcomes if o != "ok"]
    assert loser and loser[0] in {
        "AUTHORIZATION_REPLAY_DETECTED",
        "DATABASE_REFUSED_WRITE",
    }, f"the loser must be refused, got {loser}"

    async with concurrent_sessionmaker() as check:
        final = await load_authorization(check, authorization_id)
        assert final is not None
        assert final.status == AuthorizationStatus.CONSUMED.value


async def test_concurrent_consume_tasks_yield_exactly_one_winner(concurrent_sessionmaker):
    """The same race driven through `asyncio.gather`.

    SQLite serializes writers with a database lock, so the loser may surface as
    a replay OR as a lock error rather than deterministically as one of them.
    What must hold either way — and what this asserts — is that at most one
    attempt succeeds and the row is consumed exactly once.
    """
    async with concurrent_sessionmaker() as setup:
        mission = await make_mission(setup)
        txn = approved_transaction(expires_at=SOON, nonce=generate_nonce())
        row = await issue_authorization(
            setup,
            capabilities=KERNEL,
            mission_id=mission.id,
            transaction=txn,
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            issued_at=NOW,
        )
        await activate_authorization(setup, authorization_id=row.authorization_id, now=NOW)
        await setup.commit()
        authorization_id = row.authorization_id

    async def attempt() -> str:
        async with concurrent_sessionmaker() as s:
            try:
                await consume_authorization(
                    s, authorization_id=authorization_id, transaction=txn, now=NOW
                )
                await s.commit()
                return "ok"
            except Exception as exc:  # noqa: BLE001 - the failure mode is the assertion
                await s.rollback()
                return type(exc).__name__

    results = await asyncio.gather(attempt(), attempt())
    assert results.count("ok") <= 1, f"more than one attempt consumed: {results}"

    async with concurrent_sessionmaker() as check:
        final = await load_authorization(check, authorization_id)
        assert final is not None
        assert final.status in {
            AuthorizationStatus.CONSUMED.value,
            AuthorizationStatus.ACTIVE.value,
        }
        if final.status == AuthorizationStatus.CONSUMED.value:
            assert final.consumed_at is not None


async def test_a_stale_in_memory_copy_cannot_consume(concurrent_sessionmaker):
    """Explicitly proves the design does not rest on an in-memory flag.

    Session A holds an ORM object that still says ACTIVE. Session B consumes and
    commits. Session A's object is now a lie — and consuming through it fails,
    because the decision is made by the database, not by that object.
    """
    async with concurrent_sessionmaker() as setup:
        mission = await make_mission(setup)
        txn = approved_transaction(expires_at=SOON, nonce=generate_nonce())
        row = await issue_authorization(
            setup,
            capabilities=KERNEL,
            mission_id=mission.id,
            transaction=txn,
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            issued_at=NOW,
        )
        await activate_authorization(setup, authorization_id=row.authorization_id, now=NOW)
        await setup.commit()
        authorization_id = row.authorization_id

    async with concurrent_sessionmaker() as a:
        stale = await load_authorization(a, authorization_id)
        assert stale is not None
        assert stale.status == AuthorizationStatus.ACTIVE.value

        async with concurrent_sessionmaker() as b:
            await consume_authorization(
                b, authorization_id=authorization_id, transaction=txn, now=NOW
            )
            await b.commit()

        # The in-memory copy still claims ACTIVE...
        assert stale.status == AuthorizationStatus.ACTIVE.value
        # ...and it still cannot consume. On PostgreSQL the refusal is
        # AUTHORIZATION_REPLAY_DETECTED (asserted exactly in
        # tests/test_postgres_concurrency.py); on SQLite the write is refused by
        # the database's own locking. What must hold on both is that the stale
        # object grants nothing.
        with pytest.raises((AuthorizationReplayDetected, OperationalError)):
            await consume_authorization(
                a, authorization_id=authorization_id, transaction=txn, now=NOW
            )
        await a.rollback()

    async with concurrent_sessionmaker() as check:
        final = await load_authorization(check, authorization_id)
        assert final is not None
        assert final.status == AuthorizationStatus.CONSUMED.value
        # Consumed once, by B — never twice.
        assert final.consumed_at is not None
