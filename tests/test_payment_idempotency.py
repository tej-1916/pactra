"""Idempotency: ONE LOGICAL PAYMENT REQUEST -> AT MOST ONE LOGICAL PAYMENT.

The invariant under test is ``logical_payment_count(idempotency_key) <= 1``, and
it is enforced by a UNIQUE index rather than by an application check, so a race
cannot slip between the check and the insert.

The second property is just as important and easier to get wrong: a reused key
must not SILENTLY reuse a payment when the request changed. Silent reuse is the
failure that turns an idempotency key from a safety mechanism into an attack
surface — mint a key for a small payment, present it for a large one, and get
back a "successful" small payment as if the large one had happened.
"""

import pytest
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import EventType
from packages.schemas.payment import PaymentIntentState, request_fingerprint
from services.audit_ledger.ledger import list_events
from services.payment_executor.intents import (
    IdempotencyConflict,
    create_payment_intent,
    find_by_idempotency_key,
)
from services.payment_executor.outbox import pending_events_for
from services.security_kernel.authorization import load_authorization
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()


# --------------------------------------------------------------------------- #
# #6 Same key + same transaction -> the SAME logical payment
# --------------------------------------------------------------------------- #
async def test_same_key_same_transaction_returns_the_same_intent(session):
    mission, authorization, _ = await authorized_mission(session)
    kwargs = dict(
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-repeat",
        provider="fake",
    )

    first = await create_payment_intent(session, **kwargs)
    second = await create_payment_intent(session, **kwargs)

    assert first.created is True
    assert second.created is False
    assert first.intent.id == second.intent.id


async def test_a_retry_does_not_consume_the_authorization_again(session):
    """The brief's explicit requirement: a retry of an already-created intent
    must NOT attempt to consume the authorization again.

    Proven by the authorization's own record — a second consume would have
    moved ``consumed_at``, and it does not move.
    """
    mission, authorization, _ = await authorized_mission(session)
    kwargs = dict(
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-no-double-consume",
        provider="fake",
    )

    await create_payment_intent(session, **kwargs)
    after_first = await load_authorization(session, authorization.authorization_id)
    assert after_first is not None
    consumed_at = after_first.consumed_at

    # A second consume of a CONSUMED authorization would raise
    # AUTHORIZATION_REPLAY_DETECTED. It does not raise, because it is not
    # attempted: the retry resolves the existing intent instead.
    result = await create_payment_intent(session, **kwargs)
    assert result.created is False

    after_second = await load_authorization(session, authorization.authorization_id)
    assert after_second is not None
    assert after_second.status == AuthorizationStatus.CONSUMED.value
    assert after_second.consumed_at == consumed_at


async def test_a_retry_queues_no_second_provider_call(session):
    """A duplicate request must not enqueue a second create instruction."""
    mission, authorization, _ = await authorized_mission(session)
    kwargs = dict(
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-one-outbox",
        provider="fake",
    )

    first = await create_payment_intent(session, **kwargs)
    for _ in range(4):
        await create_payment_intent(session, **kwargs)

    assert len(await pending_events_for(session, first.intent.id)) == 1


async def test_reuse_is_audited_as_reuse(session):
    mission, authorization, _ = await authorized_mission(session)
    kwargs = dict(
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-audited-reuse",
        provider="fake",
    )
    await create_payment_intent(session, **kwargs)
    await create_payment_intent(session, **kwargs)

    events = await list_events(session, mission.id)
    reused = [e for e in events if e.event_type == EventType.PAYMENT_INTENT_REUSED.value]
    assert len(reused) == 1
    assert reused[0].payload["authorization_consumed"] is False

    created = [e for e in events if e.event_type == EventType.PAYMENT_INTENT_CREATED.value]
    assert len(created) == 1


# --------------------------------------------------------------------------- #
# #7 Same key + DIFFERENT transaction -> IDEMPOTENCY_CONFLICT -> DENY
# --------------------------------------------------------------------------- #
async def test_same_key_different_transaction_is_rejected(session):
    """Never silently reused. The key names one payment, and only that one."""
    mission_a, authorization_a, _ = await authorized_mission(session, amount_inr=3799)
    mission_b, authorization_b, _ = await authorized_mission(session, amount_inr=9999)

    await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission_a.id,
        authorization_id=authorization_a.authorization_id,
        idempotency_key="idem-shared",
        provider="fake",
    )

    with pytest.raises(IdempotencyConflict) as exc:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_b.id,
            authorization_id=authorization_b.authorization_id,
            idempotency_key="idem-shared",
            provider="fake",
        )
    assert exc.value.reason_code == "IDEMPOTENCY_CONFLICT"


async def test_a_conflicting_reuse_consumes_nothing(session):
    """The denial must be free of side effects, or a conflicting retry would
    still burn the second authorization."""
    mission_a, authorization_a, _ = await authorized_mission(session, amount_inr=3799)
    mission_b, authorization_b, _ = await authorized_mission(session, amount_inr=9999)

    await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission_a.id,
        authorization_id=authorization_a.authorization_id,
        idempotency_key="idem-conflict-clean",
        provider="fake",
    )
    with pytest.raises(IdempotencyConflict):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_b.id,
            authorization_id=authorization_b.authorization_id,
            idempotency_key="idem-conflict-clean",
            provider="fake",
        )

    untouched = await load_authorization(session, authorization_b.authorization_id)
    assert untouched is not None
    assert untouched.status == AuthorizationStatus.ACTIVE.value
    assert untouched.consumed_at is None


async def test_conflict_is_audited_without_leaking_the_other_request(session):
    mission_a, authorization_a, _ = await authorized_mission(session, amount_inr=3799)
    mission_b, authorization_b, _ = await authorized_mission(session, amount_inr=9999)

    await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission_a.id,
        authorization_id=authorization_a.authorization_id,
        idempotency_key="idem-conflict-audit",
        provider="fake",
    )
    with pytest.raises(IdempotencyConflict):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_b.id,
            authorization_id=authorization_b.authorization_id,
            idempotency_key="idem-conflict-audit",
            provider="fake",
        )

    events = await list_events(session, mission_a.id)
    conflicts = [e for e in events if e.event_type == EventType.IDEMPOTENCY_CONFLICT.value]
    assert len(conflicts) == 1
    payload = conflicts[0].payload
    assert payload["reason_code"] == "IDEMPOTENCY_CONFLICT"
    # Fingerprint prefixes only — never the other request's amount or merchant,
    # which may belong to a different mission entirely.
    assert "9999" not in str(payload)
    assert len(payload["existing_fingerprint_prefix"]) == 16


async def test_a_different_provider_is_a_different_request(session):
    """The provider is part of the fingerprint: the same key cannot be used to
    route the same approval to a second rail."""
    mission, authorization, _ = await authorized_mission(session)
    await create_payment_intent(
        session,
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-provider-swap",
        provider="fake",
    )
    with pytest.raises(IdempotencyConflict):
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-provider-swap",
            provider="razorpay_test",
        )


# --------------------------------------------------------------------------- #
# Fingerprint properties
# --------------------------------------------------------------------------- #
import uuid  # noqa: E402

FINGERPRINT_ARGS = dict(
    mission_id=uuid.UUID(int=1),
    authorization_id=uuid.UUID(int=2),
    transaction_digest="a" * 64,
    amount_inr=3799,
    currency="INR",
    merchant_id="merchant_a",
    provider="fake",
)


def test_fingerprint_is_deterministic():
    assert request_fingerprint(**FINGERPRINT_ARGS) == request_fingerprint(**FINGERPRINT_ARGS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("mission_id", uuid.UUID(int=99)),
        ("authorization_id", uuid.UUID(int=99)),
        ("transaction_digest", "b" * 64),
        ("amount_inr", 3800),
        ("currency", "USD"),
        ("merchant_id", "merchant_b"),
        ("provider", "razorpay_test"),
    ],
)
def test_every_fingerprinted_field_changes_the_fingerprint(field, value):
    """Exhaustive: no field can be varied while the fingerprint stays equal.

    A field that failed this would be a field an attacker could change while
    reusing somebody's idempotency key.
    """
    mutated = dict(FINGERPRINT_ARGS)
    mutated[field] = value
    assert request_fingerprint(**mutated) != request_fingerprint(**FINGERPRINT_ARGS)


async def test_at_most_one_intent_exists_per_key(session):
    """The invariant, stated directly."""
    mission, authorization, _ = await authorized_mission(session)
    kwargs = dict(
        capabilities=EXECUTOR,
        mission_id=mission.id,
        authorization_id=authorization.authorization_id,
        idempotency_key="idem-count",
        provider="fake",
    )
    for _ in range(6):
        await create_payment_intent(session, **kwargs)

    from apps.api.db.models import PaymentIntentRow
    from sqlalchemy import func, select

    count = await session.scalar(
        select(func.count())
        .select_from(PaymentIntentRow)
        .where(PaymentIntentRow.idempotency_key == "idem-count")
    )
    assert count == 1

    held = await find_by_idempotency_key(session, "idem-count")
    assert held is not None
    assert held.state == PaymentIntentState.QUEUED.value
