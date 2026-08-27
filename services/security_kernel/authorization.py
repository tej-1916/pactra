"""Authorization lifecycle: issue, activate, consume, revoke, expire.

WHAT THIS IS: a **server-issued authorization artifact**. Phase 3 implements no
signing and no signature verification, so nothing here is described as
"cryptographically signed". The artifact is authoritative because it is minted,
held, and consumed entirely inside the trusted server boundary.

Concurrency design
------------------
Every privileged state transition is a SINGLE atomic conditional UPDATE whose
WHERE clause carries the entire precondition, and the database's ``rowcount``
is the only thing that decides whether the transition happened::

    UPDATE authorizations
       SET status='CONSUMED', consumed_at=:now
     WHERE authorization_id=:id
       AND status='ACTIVE'              -- not already consumed/revoked/expired
       AND transaction_digest=:digest   -- bound to THIS exact transaction
       AND expires_at > :now            -- still inside its window

There is deliberately no read-then-write and no in-memory boolean on the
decision path. Two requests that both observed ``ACTIVE`` will both issue this
UPDATE; exactly one gets ``rowcount == 1`` because the row is no longer ACTIVE
by the time the second executes. The loser is told
``AUTHORIZATION_REPLAY_DETECTED`` and changes nothing.

The row is re-read AFTER a failed UPDATE only to classify *why* it failed, so
the caller gets a precise reason code. That read never grants anything: the
privileged transition was already refused by the database.

Logging discipline
------------------
The ``nonce`` is server-held authorization material and is NEVER written to an
audit payload or returned by the API. Audit payloads carry a truncated digest
prefix — enough to correlate events, not enough to be a copy of the artifact.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import cast

from apps.api.db.models import AuthorizationRow
from packages.schemas.authorization import Authorization, AuthorizationStatus
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, ReasonCode, as_utc, utcnow
from packages.schemas.invariants import require
from packages.schemas.transaction import BINDING_VERSION, BoundTransaction
from sqlalchemy import CursorResult, Update, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import append_event
from services.security_kernel.binding import digests_match
from services.security_kernel.capability import enforce

ACTOR = "security-kernel"

#: 32 bytes of CSPRNG entropy, hex-encoded. Wide enough that nonce collision is
#: not a practical concern; the DB UNIQUE constraint is the hard guarantee.
NONCE_BYTES = 32

#: How long a freshly issued authorization stays usable, unless overridden.
DEFAULT_TTL = timedelta(minutes=15)

#: How much of the digest appears in audit payloads. Enough to correlate events
#: across a mission, not enough to reproduce the artifact.
DIGEST_LOG_PREFIX = 16


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #
class AuthorizationFailure(Exception):
    """Base class for every refusal to honour an authorization."""

    reason_code: str = "AUTHORIZATION_FAILURE"

    def __init__(self, authorization_id: uuid.UUID | None, detail: str) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.authorization_id = authorization_id
        self.detail = detail


class TransactionBindingFailure(AuthorizationFailure):
    """The live transaction does not hash to the digest that was approved."""

    reason_code = ReasonCode.TRANSACTION_BINDING_FAILURE.value


class AuthorizationReplayDetected(AuthorizationFailure):
    """A consumed authorization was presented again."""

    reason_code = ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value


class AuthorizationExpired(AuthorizationFailure):
    """The authorization is past ``expires_at``."""

    reason_code = ReasonCode.AUTHORIZATION_EXPIRED.value


class AuthorizationNotActive(AuthorizationFailure):
    """The authorization exists but is not in a consumable state."""

    reason_code = ReasonCode.AUTHORIZATION_NOT_ACTIVE.value


class AuthorizationNotFound(AuthorizationFailure):
    reason_code = ReasonCode.AUTHORIZATION_NOT_FOUND.value


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def generate_nonce() -> str:
    """A fresh, unpredictable nonce. Uniqueness is additionally enforced by the
    ``uq_authorizations_nonce`` database constraint."""
    return secrets.token_hex(NONCE_BYTES)


def to_authorization(row: AuthorizationRow) -> Authorization:
    """Project a persisted row into the kernel's domain object, normalizing
    every timestamp to timezone-aware UTC (SQLite returns naive datetimes)."""
    return Authorization(
        authorization_id=row.authorization_id,
        mission_id=row.mission_id,
        transaction_digest=row.transaction_digest,
        nonce=row.nonce,
        issued_at=as_utc(row.issued_at),
        expires_at=as_utc(row.expires_at),
        status=AuthorizationStatus(row.status),
        policy_version=row.policy_version,
        offer_version=row.offer_version,
        binding_version=row.binding_version,
        consumed_at=None if row.consumed_at is None else as_utc(row.consumed_at),
    )


def _digest_prefix(digest: str) -> str:
    return digest[:DIGEST_LOG_PREFIX]


async def _apply_transition(session: AsyncSession, statement: Update) -> int:
    """Run a conditional UPDATE and return how many rows it actually changed.

    This return value IS the security decision. A precondition that belongs in
    the WHERE clause must never be re-checked in Python afterwards: doing so
    reintroduces the read-then-write window this design exists to close.

    ``AsyncSession.execute`` is typed as returning ``Result``; a DML statement
    always yields a ``CursorResult``, which is where ``rowcount`` lives.
    """
    result = cast(CursorResult, await session.execute(statement))
    return result.rowcount


async def _reload(session: AsyncSession, authorization_id: uuid.UUID) -> AuthorizationRow | None:
    """Re-read a row from the database, discarding any stale identity-map copy.

    ``populate_existing=True`` matters: the atomic UPDATEs below run with
    ``synchronize_session=False``, so an ORM object already loaded in this
    session is deliberately left stale. Trusting that stale copy is exactly the
    in-memory check this design refuses to rely on.
    """
    return await session.get(AuthorizationRow, authorization_id, populate_existing=True)


async def _audit(
    session: AsyncSession,
    *,
    mission_id: uuid.UUID,
    event_type: EventType,
    payload: dict,
) -> None:
    await append_event(
        session,
        mission_id=mission_id,
        event_type=event_type,
        actor=ACTOR,
        payload=payload,
    )


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
async def issue_authorization(
    session: AsyncSession,
    *,
    capabilities: CapabilitySet,
    mission_id: uuid.UUID,
    transaction: BoundTransaction,
    issued_at: datetime | None = None,
) -> AuthorizationRow:
    """Mint a PENDING authorization bound to ``transaction``.

    Guarded by the ``authorization.issue`` capability, which the buyer-agent
    principal is explicitly denied. A compromised agent therefore cannot mint an
    authorization: enforcement happens before anything is written, so no row
    exists on a denied call.
    """
    enforce(capabilities, Capability.AUTHORIZATION_ISSUE)

    now = as_utc(issued_at or utcnow())
    require(
        transaction.expires_at > now,
        "authorization.issued_before_expiry",
        f"transaction expires at {transaction.expires_at.isoformat()}, "
        f"which is not after issuance at {now.isoformat()}",
    )

    digest = transaction.digest()
    row = AuthorizationRow(
        authorization_id=uuid.uuid4(),
        mission_id=mission_id,
        transaction_digest=digest,
        nonce=transaction.nonce,
        binding_version=BINDING_VERSION,
        policy_version=transaction.policy_version,
        offer_version=transaction.offer_version,
        status=AuthorizationStatus.PENDING.value,
        issued_at=now,
        expires_at=transaction.expires_at,
        consumed_at=None,
        bound_merchant_id=transaction.merchant_id,
        bound_product_id=transaction.product_id,
        bound_quantity=transaction.quantity,
        bound_amount_inr=transaction.amount_inr,
        bound_currency=transaction.currency,
    )
    session.add(row)
    await session.flush()

    await _audit(
        session,
        mission_id=mission_id,
        event_type=EventType.AUTHORIZATION_CREATED,
        payload={
            "authorization_id": str(row.authorization_id),
            "status": row.status,
            # Truncated: enough to correlate, not a copy of the artifact.
            "transaction_digest_prefix": _digest_prefix(digest),
            "policy_version": transaction.policy_version,
            "offer_version": transaction.offer_version,
            "binding_version": BINDING_VERSION,
            "expires_at": transaction.expires_at.isoformat(),
            "bound_merchant_id": transaction.merchant_id,
            "bound_product_id": transaction.product_id,
            "bound_quantity": transaction.quantity,
            "bound_amount_inr": transaction.amount_inr,
            "bound_currency": transaction.currency,
            # NOTE: the nonce is deliberately absent.
        },
    )
    return row


async def activate_authorization(
    session: AsyncSession,
    *,
    authorization_id: uuid.UUID,
    now: datetime | None = None,
) -> AuthorizationRow:
    """Atomically move PENDING -> ACTIVE. Refuses an expired authorization."""
    moment = as_utc(now or utcnow())
    changed = await _apply_transition(
        session,
        update(AuthorizationRow)
        .where(
            AuthorizationRow.authorization_id == authorization_id,
            AuthorizationRow.status == AuthorizationStatus.PENDING.value,
            AuthorizationRow.expires_at > moment,
        )
        .values(status=AuthorizationStatus.ACTIVE.value)
        .execution_options(synchronize_session=False),
    )
    if changed != 1:
        await _classify_and_raise(
            session,
            authorization_id=authorization_id,
            transaction=None,
            now=moment,
            expected_status=AuthorizationStatus.PENDING,
        )

    row = await _reload(session, authorization_id)
    if row is None:  # pragma: no cover - the UPDATE just matched this row
        raise AuthorizationNotFound(authorization_id, "authorization vanished after activation")

    await _audit(
        session,
        mission_id=row.mission_id,
        event_type=EventType.AUTHORIZATION_ACTIVATED,
        payload={
            "authorization_id": str(row.authorization_id),
            "status": row.status,
            "transaction_digest_prefix": _digest_prefix(row.transaction_digest),
        },
    )
    return row


async def consume_authorization(
    session: AsyncSession,
    *,
    authorization_id: uuid.UUID,
    transaction: BoundTransaction,
    now: datetime | None = None,
) -> AuthorizationRow:
    """Atomically move ACTIVE -> CONSUMED, one time only.

    The whole precondition — still ACTIVE, still unexpired, still bound to this
    exact transaction — lives in the WHERE clause, so the database decides.
    A second attempt matches zero rows and raises
    ``AuthorizationReplayDetected`` without changing any privileged state.
    """
    moment = as_utc(now or utcnow())
    digest = transaction.digest()

    changed = await _apply_transition(
        session,
        update(AuthorizationRow)
        .where(
            AuthorizationRow.authorization_id == authorization_id,
            AuthorizationRow.status == AuthorizationStatus.ACTIVE.value,
            AuthorizationRow.transaction_digest == digest,
            AuthorizationRow.expires_at > moment,
        )
        .values(
            status=AuthorizationStatus.CONSUMED.value,
            consumed_at=moment,
        )
        .execution_options(synchronize_session=False),
    )
    if changed != 1:
        await _classify_and_raise(
            session,
            authorization_id=authorization_id,
            transaction=transaction,
            now=moment,
            expected_status=AuthorizationStatus.ACTIVE,
        )

    row = await _reload(session, authorization_id)
    if row is None:  # pragma: no cover - the UPDATE just matched this row
        raise AuthorizationNotFound(authorization_id, "authorization vanished after consumption")

    await _audit(
        session,
        mission_id=row.mission_id,
        event_type=EventType.AUTHORIZATION_CONSUMED,
        payload={
            "authorization_id": str(row.authorization_id),
            "status": row.status,
            "transaction_digest_prefix": _digest_prefix(digest),
            "consumed_at": moment.isoformat(),
        },
    )
    return row


async def revoke_authorization(
    session: AsyncSession,
    *,
    authorization_id: uuid.UUID,
    reason: str,
    now: datetime | None = None,
) -> AuthorizationRow:
    """Atomically move PENDING/ACTIVE -> REVOKED. Never resurrects a terminal row."""
    moment = as_utc(now or utcnow())
    changed = await _apply_transition(
        session,
        update(AuthorizationRow)
        .where(
            AuthorizationRow.authorization_id == authorization_id,
            AuthorizationRow.status.in_(
                (AuthorizationStatus.PENDING.value, AuthorizationStatus.ACTIVE.value)
            ),
        )
        .values(status=AuthorizationStatus.REVOKED.value)
        .execution_options(synchronize_session=False),
    )
    if changed != 1:
        await _classify_and_raise(
            session,
            authorization_id=authorization_id,
            transaction=None,
            now=moment,
            expected_status=AuthorizationStatus.ACTIVE,
        )

    row = await _reload(session, authorization_id)
    if row is None:  # pragma: no cover - the UPDATE just matched this row
        raise AuthorizationNotFound(authorization_id, "authorization vanished after revocation")

    await _audit(
        session,
        mission_id=row.mission_id,
        event_type=EventType.AUTHORIZATION_REVOKED,
        payload={
            "authorization_id": str(row.authorization_id),
            "status": row.status,
            "reason": reason,
        },
    )
    return row


async def expire_if_stale(
    session: AsyncSession,
    *,
    authorization_id: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Atomically demote a stale PENDING/ACTIVE authorization to EXPIRED.

    This is a demotion, never a grant, so running it opportunistically is safe.
    Returns True if this call performed the transition.
    """
    moment = as_utc(now or utcnow())
    changed = await _apply_transition(
        session,
        update(AuthorizationRow)
        .where(
            AuthorizationRow.authorization_id == authorization_id,
            AuthorizationRow.status.in_(
                (AuthorizationStatus.PENDING.value, AuthorizationStatus.ACTIVE.value)
            ),
            AuthorizationRow.expires_at <= moment,
        )
        .values(status=AuthorizationStatus.EXPIRED.value)
        .execution_options(synchronize_session=False),
    )
    if changed != 1:
        return False

    row = await _reload(session, authorization_id)
    if row is None:  # pragma: no cover - the UPDATE just matched this row
        return False

    await _audit(
        session,
        mission_id=row.mission_id,
        event_type=EventType.AUTHORIZATION_EXPIRED,
        payload={
            "authorization_id": str(row.authorization_id),
            "status": row.status,
            "expires_at": as_utc(row.expires_at).isoformat(),
        },
    )
    return True


# --------------------------------------------------------------------------- #
# Failure classification
# --------------------------------------------------------------------------- #
async def _classify_and_raise(
    session: AsyncSession,
    *,
    authorization_id: uuid.UUID,
    transaction: BoundTransaction | None,
    now: datetime,
    expected_status: AuthorizationStatus,
) -> None:
    """Explain a refused transition and record it, then raise.

    Called only AFTER the atomic UPDATE has already refused the transition, so
    nothing here can grant anything. The order below is by severity: a replay is
    the strongest signal, then a mutated binding, then expiry, then a merely
    wrong state.
    """
    row = await _reload(session, authorization_id)
    if row is None:
        raise AuthorizationNotFound(authorization_id, "no such authorization")

    status = AuthorizationStatus(row.status)

    if status == AuthorizationStatus.CONSUMED:
        await _audit(
            session,
            mission_id=row.mission_id,
            event_type=EventType.AUTHORIZATION_REPLAY_DETECTED,
            payload={
                "authorization_id": str(row.authorization_id),
                "status": row.status,
                "reason_code": ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value,
                "consumed_at": (
                    None if row.consumed_at is None else as_utc(row.consumed_at).isoformat()
                ),
            },
        )
        raise AuthorizationReplayDetected(
            authorization_id,
            "authorization was already consumed and cannot be reused",
        )

    if transaction is not None and not digests_match(row.transaction_digest, transaction):
        await _audit(
            session,
            mission_id=row.mission_id,
            event_type=EventType.TRANSACTION_BINDING_FAILURE,
            payload={
                "authorization_id": str(row.authorization_id),
                "status": row.status,
                "reason_code": ReasonCode.TRANSACTION_BINDING_FAILURE.value,
                "bound_digest_prefix": _digest_prefix(row.transaction_digest),
                "presented_digest_prefix": _digest_prefix(transaction.digest()),
            },
        )
        raise TransactionBindingFailure(
            authorization_id,
            "the presented transaction does not match the approved transaction",
        )

    if now >= as_utc(row.expires_at):
        # Demote the stale row so its recorded status matches reality. This is a
        # demotion; it can never make an authorization usable.
        await expire_if_stale(session, authorization_id=authorization_id, now=now)
        raise AuthorizationExpired(
            authorization_id,
            f"authorization expired at {as_utc(row.expires_at).isoformat()}",
        )

    raise AuthorizationNotActive(
        authorization_id,
        f"authorization is {status.value}, expected {expected_status.value}",
    )


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
async def load_authorization(
    session: AsyncSession, authorization_id: uuid.UUID
) -> AuthorizationRow | None:
    return await _reload(session, authorization_id)


async def authorization_for_mission(
    session: AsyncSession, mission_id: uuid.UUID
) -> AuthorizationRow | None:
    """The most recently issued authorization for a mission, if any."""
    result = await session.execute(
        select(AuthorizationRow)
        .where(AuthorizationRow.mission_id == mission_id)
        .order_by(AuthorizationRow.issued_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
