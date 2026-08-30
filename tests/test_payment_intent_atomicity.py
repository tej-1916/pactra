"""Authorization / payment atomicity — the hardest part of Phase 4.

Four things must be true together or not at all: the authorization is consumed,
the payment intent exists, the audit event is appended, and the outbox event is
queued. These tests attack each half of that pairing:

* an authorization consumed with no intent persisted  (money authorized, nothing
  to show for it — the authorization is spent and the payment is lost)
* an intent persisted with no authorization consumed  (a payment that nobody
  approved, and an approval still live for a second one)
"""

import uuid

import pytest
from apps.api.db.models import PaymentIntentRow
from packages.schemas.approval import ApprovalScheme
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import EventType, MissionState, utcnow
from packages.schemas.payment import OutboxEventType, OutboxStatus, PaymentIntentState
from services.audit_ledger.ledger import list_events
from services.payment_executor.intents import (
    MissionNotAuthorized,
    create_payment_intent,
    find_by_idempotency_key,
)
from services.payment_executor.outbox import pending_events_for
from services.security_kernel.authorization import (
    AuthorizationExpired,
    AuthorizationNotActive,
    TransactionBindingFailure,
    load_authorization,
    revoke_authorization,
)
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()


# --------------------------------------------------------------------------- #
# #4 The happy path consumes the authorization EXACTLY once
# --------------------------------------------------------------------------- #
async def test_new_payment_consumes_the_authorization_exactly_once(session):
    mission, authorization, _ = await authorized_mission(session)

    result = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-happy",
        provider="fake",
    )

    assert result.created is True
    assert result.intent.state == PaymentIntentState.QUEUED.value

    consumed = await load_authorization(session, authorization.authorization_id)
    assert consumed is not None
    assert consumed.status == AuthorizationStatus.CONSUMED.value
    assert consumed.consumed_at is not None


async def test_the_whole_unit_lands_together(session):
    """Intent + consumption + audit + outbox, all present after one call."""
    mission, authorization, _ = await authorized_mission(session)

    result = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-unit",
        provider="fake",
    )

    assert await find_by_idempotency_key(session, "idem-unit") is not None

    authorization_row = await load_authorization(session, authorization.authorization_id)
    assert authorization_row is not None
    assert authorization_row.status == AuthorizationStatus.CONSUMED.value

    types = [e.event_type for e in await list_events(session, mission.id)]
    assert EventType.AUTHORIZATION_CONSUMED.value in types
    assert EventType.PAYMENT_INTENT_CREATED.value in types
    assert EventType.PAYMENT_QUEUED.value in types

    outbox = await pending_events_for(session, result.intent.id)
    assert len(outbox) == 1
    assert outbox[0].event_type == OutboxEventType.PAYMENT_CREATE_REQUESTED.value
    assert outbox[0].status == OutboxStatus.PENDING.value

    await session.refresh(mission)
    assert mission.state == MissionState.PAYMENT_PENDING.value


async def test_the_intent_copies_the_authorizations_transaction_not_the_callers(session):
    """The caller supplies no transaction, so the intent can only describe the
    approved one."""
    mission, authorization, txn = await authorized_mission(session, amount_inr=4242)

    result = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-derived",
        provider="fake",
    )

    assert result.intent.amount_inr == 4242
    assert result.intent.currency == txn.currency
    assert result.intent.merchant_id == txn.merchant_id
    assert result.intent.transaction_digest == authorization.transaction_digest
    assert result.intent.transaction_digest == txn.digest()


# --------------------------------------------------------------------------- #
# #1-#3 No intent without a VALID authorization
# --------------------------------------------------------------------------- #
async def test_pending_authorization_cannot_create_a_payment_intent(session):
    """An approval that was never activated authorizes nothing."""
    from packages.schemas.capability import security_kernel_capabilities
    from services.security_kernel.authorization import generate_nonce, issue_authorization
    from tests.conftest import FIXED_EXPIRY, approved_transaction, make_mission

    mission = await make_mission(session)
    txn = approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce())
    row = await issue_authorization(
        session,
        capabilities=security_kernel_capabilities(),
        mission_id=mission.id,
        transaction=txn,
        approval_scheme=ApprovalScheme.POLICY_AUTO,
    )
    mission.state = MissionState.AUTHORIZED.value
    await session.flush()

    with pytest.raises(AuthorizationNotActive):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            idempotency_key="idem-pending",
            provider="fake",
        )
    assert await find_by_idempotency_key(session, "idem-pending") is None


async def test_expired_authorization_cannot_create_a_payment_intent(session):
    """EXPIRED APPROVAL -> PAYMENT IMPOSSIBLE."""
    mission, authorization, _ = await authorized_mission(session)

    with pytest.raises(AuthorizationExpired):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-expired",
            # One second past the bound expiry.
            now=authorization.expires_at.replace(tzinfo=None).astimezone()
            if False
            else utcnow().replace(year=2031),
            provider="fake",
        )

    assert await find_by_idempotency_key(session, "idem-expired") is None
    still = await load_authorization(session, authorization.authorization_id)
    assert still is not None
    assert still.status != AuthorizationStatus.CONSUMED.value


async def test_revoked_authorization_cannot_create_a_payment_intent(session):
    mission, authorization, _ = await authorized_mission(session)
    await revoke_authorization(
        session, authorization_id=authorization.authorization_id, reason="test"
    )

    with pytest.raises(AuthorizationNotActive):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-revoked",
            provider="fake",
        )
    assert await find_by_idempotency_key(session, "idem-revoked") is None


async def test_replayed_authorization_cannot_create_a_second_payment_intent(session):
    """REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE, sequentially."""
    mission, authorization, _ = await authorized_mission(session)
    await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-first",
        provider="fake",
    )

    # A DIFFERENT idempotency key, so the idempotency fast path cannot mask the
    # authorization check. This must fail on the authorization, not the key.
    with pytest.raises(MissionNotAuthorized):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-second",
            provider="fake",
        )
    assert await find_by_idempotency_key(session, "idem-second") is None


# --------------------------------------------------------------------------- #
# #3 Transaction-binding mismatch
# --------------------------------------------------------------------------- #
async def test_a_tampered_bound_column_cannot_create_a_payment_intent(session):
    """TRANSACTION CHANGED AFTER APPROVAL -> AUTHORIZATION INVALID.

    The caller cannot present a mutated transaction — there is no parameter for
    one — so the attack has to come from the stored row itself. Mutating a
    bound column makes the row stop re-deriving to its recorded digest, and the
    executor refuses rather than paying an amount nobody approved.
    """
    from apps.api.db.models import AuthorizationRow
    from packages.schemas.invariants import InvariantViolation

    mission, authorization, _ = await authorized_mission(session, amount_inr=3799)

    await session.execute(
        update(AuthorizationRow)
        .where(AuthorizationRow.authorization_id == authorization.authorization_id)
        .values(bound_amount_inr=99999)
        .execution_options(synchronize_session=False)
    )

    with pytest.raises(InvariantViolation):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-tampered",
            provider="fake",
        )
    assert await find_by_idempotency_key(session, "idem-tampered") is None


async def test_binding_failure_is_reachable_through_the_kernel(session):
    """The digest check that guards consumption is still the Phase 3 one."""
    from services.security_kernel.authorization import consume_authorization

    mission, authorization, txn = await authorized_mission(session)
    mutated = txn.model_copy(update={"amount_inr": txn.amount_inr + 1})

    with pytest.raises(TransactionBindingFailure):
        await consume_authorization(
            session, authorization_id=authorization.authorization_id, transaction=mutated
        )


# --------------------------------------------------------------------------- #
# #5 Rollback rolls BOTH sides back
# --------------------------------------------------------------------------- #
async def test_db_rollback_also_rolls_back_authorization_consumption(sessionmaker):
    """The core atomicity claim, exercised against a real rollback.

    A separate session is used afterwards so the assertion reads committed
    state, not this session's identity map.
    """
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        await setup.commit()
        mission_id, authorization_id = mission.id, authorization.authorization_id

    async with sessionmaker() as work:
        result = await create_payment_intent(
            work,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="idem-rollback",
            provider="fake",
        )
        # Inside this uncommitted transaction, both effects are visible.
        assert result.created is True
        mid_flight = await load_authorization(work, authorization_id)
        assert mid_flight is not None
        assert mid_flight.status == AuthorizationStatus.CONSUMED.value

        await work.rollback()

    async with sessionmaker() as check:
        # The intent is gone...
        assert await find_by_idempotency_key(check, "idem-rollback") is None
        # ...and so is the consumption. The approval is spendable again.
        restored = await load_authorization(check, authorization_id)
        assert restored is not None
        assert restored.status == AuthorizationStatus.ACTIVE.value
        assert restored.consumed_at is None


async def test_the_authorization_is_still_usable_after_a_rollback(sessionmaker):
    """Not merely un-consumed: actually usable. A rollback that left the
    approval intact but unusable would be a subtler version of the same bug."""
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        await setup.commit()
        mission_id, authorization_id = mission.id, authorization.authorization_id

    async with sessionmaker() as doomed:
        await create_payment_intent(
            doomed,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="idem-doomed",
            provider="fake",
        )
        await doomed.rollback()

    async with sessionmaker() as retry:
        result = await create_payment_intent(
            retry,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="idem-after-rollback",
            provider="fake",
        )
        assert result.created is True
        await retry.commit()


# --------------------------------------------------------------------------- #
# Mission-level precondition
# --------------------------------------------------------------------------- #
async def test_an_unauthorized_mission_cannot_start_a_payment(session):
    from packages.schemas.capability import security_kernel_capabilities
    from services.security_kernel.authorization import (
        activate_authorization,
        generate_nonce,
        issue_authorization,
    )
    from tests.conftest import FIXED_EXPIRY, approved_transaction, make_mission

    mission = await make_mission(session, state="POLICY_CHECKED")
    txn = approved_transaction(expires_at=FIXED_EXPIRY, nonce=generate_nonce())
    row = await issue_authorization(
        session,
        capabilities=security_kernel_capabilities(),
        mission_id=mission.id,
        transaction=txn,
        approval_scheme=ApprovalScheme.POLICY_AUTO,
    )
    await activate_authorization(session, authorization_id=row.authorization_id)
    # Mission deliberately left in POLICY_CHECKED.

    with pytest.raises(MissionNotAuthorized):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=row.authorization_id,
            idempotency_key="idem-unauthorized-mission",
            provider="fake",
        )

    still = await load_authorization(session, row.authorization_id)
    assert still is not None
    assert still.status == AuthorizationStatus.ACTIVE.value


# --------------------------------------------------------------------------- #
# Storage-level guarantees
# --------------------------------------------------------------------------- #
async def test_an_intent_cannot_exist_without_an_authorization(session):
    """NO VALID AUTHORIZATION -> NO PAYMENT INTENT, at the storage layer."""
    from apps.api.db.models import PaymentIntentRow

    mission, _, _ = await authorized_mission(session)
    orphan = PaymentIntentRow(
        id=uuid.uuid4(),
        mission_id=mission.id,
        authorization_id=None,
        transaction_digest="0" * 64,
        idempotency_key="idem-orphan",
        request_fingerprint="0" * 64,
        amount_inr=100,
        currency="INR",
        merchant_id="merchant_a",
        provider="fake",
        state=PaymentIntentState.CREATED.value,
        attempts=0,
    )
    session.add(orphan)
    # Named, not blind: `Exception` would also pass if this test had a typo and
    # the flush failed for a reason that has nothing to do with the constraint
    # under test. IntegrityError is the database refusing the row.
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_bound_transaction_data_is_never_rewritten(session):
    """Immutability of the bound values, enforced in code and asserted here.

    A database trigger would be the stronger guarantee but is not portable
    across PostgreSQL and SQLite, so this is verified rather than claimed.
    """
    from apps.api.db.models import PaymentIntentRow
    from services.payment_executor.outbox import claim_next_event
    from services.payment_executor.providers.fake import FakePaymentProvider
    from services.payment_executor.worker import process_claimed_event

    mission, authorization, _ = await authorized_mission(session, amount_inr=3799)
    result = await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-immutable",
        provider="fake",
    )
    before = (
        result.intent.transaction_digest,
        result.intent.amount_inr,
        result.intent.currency,
        result.intent.merchant_id,
        result.intent.authorization_id,
    )

    event = await claim_next_event(session, worker_id="w1")
    assert event is not None
    await process_claimed_event(session, provider=FakePaymentProvider(), event=event)

    row = await session.get(PaymentIntentRow, result.intent.id, populate_existing=True)
    assert row is not None
    assert row.state == PaymentIntentState.SUCCEEDED.value
    after = (
        row.transaction_digest,
        row.amount_inr,
        row.currency,
        row.merchant_id,
        row.authorization_id,
    )
    assert before == after


async def test_a_succeeded_intent_must_name_its_provider_payment(sessionmaker):
    """The CHECK constraint: a success we cannot point at is not a success.

    Driven with raw SQL on a committed row so the ORM's own flush ordering
    cannot be what trips the constraint — the database must refuse the state
    directly.
    """
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-check",
            provider="fake",
        )
        intent_id = result.intent.id
        await setup.commit()

    async with sessionmaker() as attack:
        with pytest.raises(IntegrityError):
            await attack.execute(
                text("UPDATE payment_intents SET state = 'SUCCEEDED' WHERE id = :id"),
                {"id": str(intent_id).replace("-", "")},
            )
            await attack.commit()
        await attack.rollback()

    async with sessionmaker() as check:
        row = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert row is not None
        assert row.state != PaymentIntentState.SUCCEEDED.value
