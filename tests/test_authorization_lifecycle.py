"""Authorization artifact lifecycle: issue, activate, expire, revoke.

Replay and binding-mutation behaviour live in tests/test_replay_protection.py.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from apps.api.db.models import AuthorizationRow
from packages.schemas.approval import ApprovalScheme
from packages.schemas.authorization import Authorization, AuthorizationStatus
from packages.schemas.capability import (
    buyer_agent_capabilities,
    security_kernel_capabilities,
)
from packages.schemas.domain import EventType
from packages.schemas.invariants import InvariantViolation
from packages.schemas.transaction import BINDING_VERSION
from pydantic import ValidationError
from services.audit_ledger.ledger import list_events
from services.security_kernel.authorization import (
    NONCE_BYTES,
    AuthorizationExpired,
    AuthorizationNotActive,
    AuthorizationNotFound,
    activate_authorization,
    authorization_for_mission,
    consume_authorization,
    expire_if_stale,
    generate_nonce,
    issue_authorization,
    load_authorization,
    revoke_authorization,
    to_authorization,
)
from services.security_kernel.capability import CapabilityDenied
from sqlalchemy import func, select
from tests.conftest import approved_transaction, make_mission

pytestmark = pytest.mark.asyncio

KERNEL = security_kernel_capabilities()
BUYER = buyer_agent_capabilities()

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
SOON = NOW + timedelta(minutes=15)


async def _count(session) -> int:
    return (await session.execute(select(func.count()).select_from(AuthorizationRow))).scalar_one()


async def _issue(session, mission, **overrides):
    txn = approved_transaction(expires_at=SOON, nonce=generate_nonce(), **overrides)
    row = await issue_authorization(
        session,
        capabilities=KERNEL,
        mission_id=mission.id,
        transaction=txn,
        approval_scheme=ApprovalScheme.POLICY_AUTO,
        issued_at=NOW,
    )
    return row, txn


# --------------------------------------------------------------------------- #
# Nonce generation
# --------------------------------------------------------------------------- #
async def test_nonce_is_high_entropy_hex():
    nonce = generate_nonce()
    assert len(nonce) == NONCE_BYTES * 2
    assert set(nonce) <= set("0123456789abcdef")


async def test_nonces_are_unique():
    """Not a proof of the security property — that rests on the CSPRNG and the
    UNIQUE constraint — but it catches an accidentally constant nonce."""
    assert len({generate_nonce() for _ in range(2000)}) == 2000


# --------------------------------------------------------------------------- #
# Issuance
# --------------------------------------------------------------------------- #
async def test_issue_creates_pending_authorization_bound_to_the_transaction(session):
    mission = await make_mission(session)
    row, txn = await _issue(session, mission)

    assert row.status == AuthorizationStatus.PENDING.value
    assert row.transaction_digest == txn.digest()
    assert row.binding_version == BINDING_VERSION
    assert row.consumed_at is None
    assert row.bound_merchant_id == txn.merchant_id
    assert row.bound_amount_inr == txn.amount_inr
    assert row.bound_quantity == txn.quantity
    assert row.bound_currency == txn.currency


async def test_issue_records_an_audit_event_without_the_nonce(session):
    """AUTHORIZATION_CREATED must be auditable without leaking the artifact's
    secret material."""
    mission = await make_mission(session)
    row, txn = await _issue(session, mission)

    events = await list_events(session, mission.id)
    created = [e for e in events if e.event_type == EventType.AUTHORIZATION_CREATED.value]
    assert len(created) == 1
    payload = created[0].payload
    assert payload["authorization_id"] == str(row.authorization_id)
    assert payload["status"] == AuthorizationStatus.PENDING.value
    # The digest appears only as a truncated prefix, and the nonce not at all.
    assert payload["transaction_digest_prefix"] == txn.digest()[:16]
    assert txn.nonce not in str(payload)
    assert "nonce" not in payload


# Invariant: LLM OUTPUT -> NEVER AUTHORIZATION.
async def test_buyer_agent_cannot_issue_an_authorization(session):
    mission = await make_mission(session)
    txn = approved_transaction(expires_at=SOON, nonce=generate_nonce())

    with pytest.raises(CapabilityDenied) as exc:
        await issue_authorization(
            session,
            capabilities=BUYER,
            mission_id=mission.id,
            transaction=txn,
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            issued_at=NOW,
        )

    assert exc.value.reason_code == "CAPABILITY_DENIED"
    # Enforcement happens before any write: nothing was created.
    assert await _count(session) == 0


async def test_already_expired_transaction_cannot_be_issued(session):
    mission = await make_mission(session)
    stale = approved_transaction(expires_at=NOW - timedelta(seconds=1), nonce=generate_nonce())
    with pytest.raises(InvariantViolation):
        await issue_authorization(
            session,
            capabilities=KERNEL,
            mission_id=mission.id,
            transaction=stale,
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            issued_at=NOW,
        )
    assert await _count(session) == 0


# --------------------------------------------------------------------------- #
# #13 Malformed transaction input cannot create a valid authorization
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "override",
    [
        {"amount_inr": 0},
        {"quantity": 0},
        {"currency": "RUPEES"},
        {"merchant_id": ""},
        {"product_id": ""},
        {"policy_version": ""},
        {"offer_version": ""},
    ],
)
async def test_malformed_transaction_creates_no_authorization(session, override):
    mission = await make_mission(session)
    with pytest.raises(ValidationError):
        await _issue(session, mission, **override)
    assert await _count(session) == 0


async def test_malformed_nonce_creates_no_authorization(session):
    mission = await make_mission(session)
    with pytest.raises(ValidationError):
        txn = approved_transaction(expires_at=SOON, nonce="not-a-valid-nonce")
        await issue_authorization(
            session,
            capabilities=KERNEL,
            mission_id=mission.id,
            transaction=txn,
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            issued_at=NOW,
        )
    assert await _count(session) == 0


# --------------------------------------------------------------------------- #
# Database-level constraints
# --------------------------------------------------------------------------- #
async def test_nonce_uniqueness_is_enforced_by_the_database(session):
    """`authorizations.nonce UNIQUE` — the same nonce can never back two
    authorizations, whatever the application layer does."""
    from sqlalchemy.exc import IntegrityError

    mission = await make_mission(session)
    row, _ = await _issue(session, mission)

    duplicate = AuthorizationRow(
        authorization_id=uuid.uuid4(),
        mission_id=mission.id,
        transaction_digest="f" * 64,
        nonce=row.nonce,  # same nonce
        binding_version=BINDING_VERSION,
        policy_version="policy-v1",
        offer_version="offer-v1",
        approval_scheme=ApprovalScheme.POLICY_AUTO.value,
        signing_key_id=None,
        approval_signature=None,
        status=AuthorizationStatus.PENDING.value,
        issued_at=NOW,
        expires_at=SOON,
        consumed_at=None,
        bound_merchant_id="merchant_a",
        bound_product_id="P1",
        bound_quantity=1,
        bound_amount_inr=3799,
        bound_currency="INR",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_consumed_status_requires_a_consumption_timestamp(session):
    """`ck_authorizations_consumed_at_matches_status` — no code path can mark an
    authorization consumed without recording when."""
    from sqlalchemy.exc import IntegrityError

    mission = await make_mission(session)
    bad = AuthorizationRow(
        authorization_id=uuid.uuid4(),
        mission_id=mission.id,
        transaction_digest="a" * 64,
        nonce=generate_nonce(),
        binding_version=BINDING_VERSION,
        policy_version="policy-v1",
        offer_version="offer-v1",
        approval_scheme=ApprovalScheme.POLICY_AUTO.value,
        signing_key_id=None,
        approval_signature=None,
        status=AuthorizationStatus.CONSUMED.value,
        issued_at=NOW,
        expires_at=SOON,
        consumed_at=None,  # inconsistent with CONSUMED
        bound_merchant_id="merchant_a",
        bound_product_id="P1",
        bound_quantity=1,
        bound_amount_inr=3799,
        bound_currency="INR",
    )
    session.add(bad)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_domain_model_mirrors_the_consumed_at_constraint():
    with pytest.raises(InvariantViolation):
        Authorization(
            authorization_id=uuid.uuid4(),
            mission_id=uuid.uuid4(),
            transaction_digest="a" * 64,
            nonce="b" * 64,
            issued_at=NOW,
            expires_at=SOON,
            status=AuthorizationStatus.ACTIVE,
            policy_version="policy-v1",
            offer_version="offer-v1",
            approval_scheme=ApprovalScheme.POLICY_AUTO,
            consumed_at=NOW,  # ACTIVE must not carry a consumption time
        )


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
async def test_activation_moves_pending_to_active_and_audits_it(session):
    mission = await make_mission(session)
    row, _ = await _issue(session, mission)

    activated = await activate_authorization(
        session, authorization_id=row.authorization_id, now=NOW
    )
    assert activated.status == AuthorizationStatus.ACTIVE.value

    events = await list_events(session, mission.id)
    assert EventType.AUTHORIZATION_ACTIVATED.value in [e.event_type for e in events]


async def test_activation_is_not_repeatable(session):
    mission = await make_mission(session)
    row, _ = await _issue(session, mission)
    await activate_authorization(session, authorization_id=row.authorization_id, now=NOW)

    with pytest.raises(AuthorizationNotActive):
        await activate_authorization(session, authorization_id=row.authorization_id, now=NOW)


async def test_expired_authorization_cannot_be_activated(session):
    mission = await make_mission(session)
    row, _ = await _issue(session, mission)

    with pytest.raises(AuthorizationExpired):
        await activate_authorization(
            session, authorization_id=row.authorization_id, now=SOON + timedelta(seconds=1)
        )

    refreshed = await load_authorization(session, row.authorization_id)
    assert refreshed is not None
    assert refreshed.status == AuthorizationStatus.EXPIRED.value


async def test_unknown_authorization_is_not_found(session):
    with pytest.raises(AuthorizationNotFound):
        await activate_authorization(session, authorization_id=uuid.uuid4(), now=NOW)


# --------------------------------------------------------------------------- #
# #9 Expiration
# --------------------------------------------------------------------------- #
async def test_expired_authorization_cannot_be_consumed(session):
    mission = await make_mission(session)
    row, txn = await _issue(session, mission)
    await activate_authorization(session, authorization_id=row.authorization_id, now=NOW)

    with pytest.raises(AuthorizationExpired) as exc:
        await consume_authorization(
            session,
            authorization_id=row.authorization_id,
            transaction=txn,
            now=SOON + timedelta(seconds=1),
        )

    assert exc.value.reason_code == "AUTHORIZATION_EXPIRED"
    refreshed = await load_authorization(session, row.authorization_id)
    assert refreshed is not None
    assert refreshed.status == AuthorizationStatus.EXPIRED.value
    assert refreshed.consumed_at is None  # nothing was consumed

    events = await list_events(session, mission.id)
    assert EventType.AUTHORIZATION_EXPIRED.value in [e.event_type for e in events]


async def test_authorization_is_consumable_up_to_but_not_at_expiry(session):
    """The window is half-open: usable strictly before `expires_at`."""
    mission = await make_mission(session)
    row, txn = await _issue(session, mission)
    await activate_authorization(session, authorization_id=row.authorization_id, now=NOW)

    with pytest.raises(AuthorizationExpired):
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=txn, now=SOON
        )


async def test_expire_if_stale_is_a_no_op_while_valid(session):
    mission = await make_mission(session)
    row, _ = await _issue(session, mission)
    assert await expire_if_stale(session, authorization_id=row.authorization_id, now=NOW) is False

    refreshed = await load_authorization(session, row.authorization_id)
    assert refreshed is not None
    assert refreshed.status == AuthorizationStatus.PENDING.value


# --------------------------------------------------------------------------- #
# Revocation
# --------------------------------------------------------------------------- #
async def test_revoked_authorization_cannot_be_consumed(session):
    mission = await make_mission(session)
    row, txn = await _issue(session, mission)
    await activate_authorization(session, authorization_id=row.authorization_id, now=NOW)
    await revoke_authorization(
        session, authorization_id=row.authorization_id, reason="operator", now=NOW
    )

    with pytest.raises(AuthorizationNotActive):
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=txn, now=NOW
        )

    refreshed = await load_authorization(session, row.authorization_id)
    assert refreshed is not None
    assert refreshed.status == AuthorizationStatus.REVOKED.value
    assert refreshed.consumed_at is None


async def test_pending_authorization_cannot_be_consumed(session):
    """Approval is a real gate: an un-activated artifact authorizes nothing."""
    mission = await make_mission(session)
    row, txn = await _issue(session, mission)

    with pytest.raises(AuthorizationNotActive):
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=txn, now=NOW
        )


# --------------------------------------------------------------------------- #
# Projections / reads
# --------------------------------------------------------------------------- #
async def test_to_authorization_normalizes_timestamps_to_utc(session):
    """SQLite returns naive datetimes; the domain object must still be aware,
    or every expiry comparison would raise instead of deciding."""
    mission = await make_mission(session)
    row, _ = await _issue(session, mission)

    auth = to_authorization(row)
    assert auth.issued_at.tzinfo is not None
    assert auth.expires_at.tzinfo is not None
    assert auth.is_expired_at(SOON + timedelta(seconds=1)) is True
    assert auth.is_expired_at(NOW) is False


async def test_authorization_for_mission_returns_the_artifact(session):
    mission = await make_mission(session)
    row, _ = await _issue(session, mission)
    found = await authorization_for_mission(session, mission.id)
    assert found is not None
    assert found.authorization_id == row.authorization_id


async def test_authorization_for_mission_is_none_when_never_issued(session):
    mission = await make_mission(session)
    assert await authorization_for_mission(session, mission.id) is None
