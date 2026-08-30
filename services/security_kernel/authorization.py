"""Authorization lifecycle: issue, prove, activate, consume, revoke, expire.

The artifact is server-issued, but activation has two explicit origins.
``POLICY_AUTO`` records a deterministic ALLOW and is not user approval.
``USER_ED25519`` requires a LOCAL CRYPTOGRAPHIC APPROVAL PROOF from the
pre-enrolled DEMO USER-CONTROLLED SIGNING KEY. ``LEGACY_SERVER`` exists only to
classify historical rows and always fails closed for payment.

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
audit payload or returned by the API. Successful user-approval audit events
carry the full transaction digest and safe proof metadata, but never the
signature or any private-key material.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import cast

from apps.api.db.models import AuthorizationRow, PolicyDecisionRow
from packages.schemas.approval import ApprovalScheme
from packages.schemas.authorization import Authorization, AuthorizationStatus
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, PolicyOutcome, ReasonCode, as_utc, utcnow
from packages.schemas.invariants import require
from packages.schemas.transaction import BINDING_VERSION, BoundTransaction
from sqlalchemy import CursorResult, Update, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import append_event
from services.security_kernel.approval import (
    ApprovalVerificationError,
    verify_user_ed25519_signature,
)
from services.security_kernel.binding import digests_match
from services.security_kernel.capability_registry import enforce_registered

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


class AuthorizationProofFailure(AuthorizationFailure):
    """A missing, invalid, untrusted, or wrongly classified approval proof."""

    def __init__(
        self,
        authorization_id: uuid.UUID | None,
        detail: str,
        *,
        reason_code: str,
    ) -> None:
        self.reason_code = reason_code
        super().__init__(authorization_id, detail)


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
        approval_scheme=ApprovalScheme(row.approval_scheme),
        signing_key_id=row.signing_key_id,
        approval_signature=row.approval_signature,
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


def rebuild_bound_transaction(row: AuthorizationRow) -> BoundTransaction:
    """Reconstruct the approved transaction from SERVER-HELD state alone.

    This exists so a payment request never has to carry a transaction, and
    therefore can never carry a forged one. Every input is a column the kernel
    wrote at issuance — the ``bound_*`` fields, both version stamps, the expiry,
    and the nonce, which is server-held entropy that has never left the kernel
    and is not obtainable by any caller.

    The reconstruction is verified, not assumed: the digest is recomputed and
    compared against the digest recorded at approval time. A mismatch means the
    stored row itself no longer describes what was approved (corruption, or a
    bound column written by some path that should not exist), and it raises
    rather than proceeding — a payment must never be executed against a
    transaction the kernel cannot re-derive.
    """
    transaction = BoundTransaction(
        merchant_id=row.bound_merchant_id,
        product_id=row.bound_product_id,
        quantity=row.bound_quantity,
        amount_inr=row.bound_amount_inr,
        currency=row.bound_currency,
        policy_version=row.policy_version,
        offer_version=row.offer_version,
        expires_at=as_utc(row.expires_at),
        nonce=row.nonce,
    )
    require(
        digests_match(row.transaction_digest, transaction),
        "authorization.rebuilt_transaction_matches_digest",
        f"authorization {row.authorization_id} does not re-derive to its recorded digest",
    )
    return transaction


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
async def issue_authorization(
    session: AsyncSession,
    *,
    capabilities: CapabilitySet,
    mission_id: uuid.UUID,
    transaction: BoundTransaction,
    approval_scheme: ApprovalScheme,
    issued_at: datetime | None = None,
) -> AuthorizationRow:
    """Mint a PENDING authorization bound to ``transaction``.

    Guarded by the ``authorization.issue`` capability, which the buyer-agent
    principal is explicitly denied. A compromised agent therefore cannot mint an
    authorization: enforcement happens before anything is written, so no row
    exists on a denied call.

    Enforcement goes through ``enforce_registered``, not the raw capability
    check. ``CapabilitySet`` is a plain schema, so untrusted code can construct
    one that simply *claims* ``authorization.issue``; checking that claim
    against itself would make the guard self-certifying. The registry is
    re-consulted for the named principal and the presented set must equal the
    server-owned one, so a forged grant is refused before the digest is even
    computed. This is what keeps **LLM OUTPUT -> NEVER AUTHORIZATION**
    structural rather than merely conventional.
    """
    enforce_registered(capabilities, Capability.AUTHORIZATION_ISSUE)
    require(
        approval_scheme != ApprovalScheme.LEGACY_SERVER,
        "authorization.new_scheme_is_not_legacy",
        "new authorizations cannot use the migration-only LEGACY_SERVER scheme",
    )

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
        approval_scheme=approval_scheme.value,
        signing_key_id=None,
        approval_signature=None,
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
            "approval_scheme": approval_scheme.value,
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
    """Atomically activate only a deterministic POLICY_AUTO authorization.

    USER_ED25519 has a separate proof-bearing transition and can never reach
    ACTIVE through this function.
    """
    moment = as_utc(now or utcnow())
    changed = await _apply_transition(
        session,
        update(AuthorizationRow)
        .where(
            AuthorizationRow.authorization_id == authorization_id,
            AuthorizationRow.approval_scheme == ApprovalScheme.POLICY_AUTO.value,
            AuthorizationRow.status == AuthorizationStatus.PENDING.value,
            AuthorizationRow.expires_at > moment,
            AuthorizationRow.signing_key_id.is_(None),
            AuthorizationRow.approval_signature.is_(None),
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
            "approval_scheme": ApprovalScheme.POLICY_AUTO.value,
        },
    )
    return row


async def _require_policy_scheme(
    session: AsyncSession,
    row: AuthorizationRow,
) -> None:
    """Cross-check stored origin against the deterministic policy decision."""
    result = await session.execute(
        select(PolicyDecisionRow.decision)
        .where(
            PolicyDecisionRow.mission_id == row.mission_id,
            PolicyDecisionRow.policy_version == row.policy_version,
        )
        .order_by(PolicyDecisionRow.created_at.desc())
        .limit(1)
    )
    decision = result.scalar_one_or_none()
    schemes_by_decision: dict[str, str] = {
        PolicyOutcome.ALLOW.value: ApprovalScheme.POLICY_AUTO.value,
        PolicyOutcome.REQUIRE_APPROVAL.value: ApprovalScheme.USER_ED25519.value,
    }
    expected = None if decision is None else schemes_by_decision.get(decision)
    if expected is None or row.approval_scheme != expected:
        raise AuthorizationProofFailure(
            row.authorization_id,
            "authorization approval scheme does not match its persisted policy decision",
            reason_code=ReasonCode.AUTHORIZATION_APPROVAL_SCHEME_INVALID.value,
        )


async def _audit_proof_failure(
    session: AsyncSession,
    *,
    row: AuthorizationRow,
    reason_code: str,
    signing_key_id: str | None,
) -> None:
    """Record safe failure metadata. Signature bytes are deliberately absent."""
    await _audit(
        session,
        mission_id=row.mission_id,
        event_type=EventType.SECURITY_VIOLATION,
        payload={
            "reason_code": reason_code,
            "authorization_id": str(row.authorization_id),
            "approval_scheme": row.approval_scheme,
            "signing_key_id": signing_key_id,
            "transaction_digest": row.transaction_digest,
            "proof_accepted": False,
        },
    )


def _verify_supplied_user_proof(
    row: AuthorizationRow,
    *,
    signing_key_id: str,
    signature_hex: str,
) -> None:
    try:
        verify_user_ed25519_signature(
            authorization_id=row.authorization_id,
            mission_id=row.mission_id,
            binding_version=row.binding_version,
            transaction_digest=row.transaction_digest,
            signing_key_id=signing_key_id,
            signature_hex=signature_hex,
        )
    except ApprovalVerificationError as failure:
        raise AuthorizationProofFailure(
            row.authorization_id,
            failure.detail,
            reason_code=failure.reason_code,
        ) from failure


async def approve_authorization_with_signature(
    session: AsyncSession,
    *,
    mission_id: uuid.UUID,
    authorization_id: uuid.UUID,
    signing_key_id: str,
    signature_hex: str,
    now: datetime | None = None,
) -> AuthorizationRow:
    """Verify a USER_ED25519 proof, then atomically move PENDING -> ACTIVE."""
    moment = as_utc(now or utcnow())
    result = await session.execute(
        select(AuthorizationRow)
        .where(AuthorizationRow.authorization_id == authorization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise AuthorizationNotFound(authorization_id, "no such authorization")
    if row.mission_id != mission_id:
        raise AuthorizationNotFound(authorization_id, "authorization does not belong to mission")
    if row.status != AuthorizationStatus.PENDING.value or moment >= as_utc(row.expires_at):
        await _classify_and_raise(
            session,
            authorization_id=authorization_id,
            transaction=None,
            now=moment,
            expected_status=AuthorizationStatus.PENDING,
        )
    if row.approval_scheme != ApprovalScheme.USER_ED25519.value:
        failure = AuthorizationProofFailure(
            authorization_id,
            "only USER_ED25519 authorizations accept a user signature",
            reason_code=ReasonCode.AUTHORIZATION_APPROVAL_SCHEME_INVALID.value,
        )
        await _audit_proof_failure(
            session,
            row=row,
            reason_code=failure.reason_code,
            signing_key_id=signing_key_id,
        )
        raise failure

    # Phase 3 binding remains authoritative and is reconstructed before the
    # proof can be accepted.  The approval message commits to its digest.
    rebuild_bound_transaction(row)
    if row.binding_version != BINDING_VERSION:
        raise TransactionBindingFailure(
            authorization_id,
            f"unsupported binding version {row.binding_version!r}",
        )
    try:
        await _require_policy_scheme(session, row)
        _verify_supplied_user_proof(
            row,
            signing_key_id=signing_key_id,
            signature_hex=signature_hex,
        )
    except AuthorizationProofFailure as failure:
        await _audit_proof_failure(
            session,
            row=row,
            reason_code=failure.reason_code,
            signing_key_id=signing_key_id,
        )
        raise

    changed = await _apply_transition(
        session,
        update(AuthorizationRow)
        .where(
            AuthorizationRow.authorization_id == authorization_id,
            AuthorizationRow.mission_id == mission_id,
            AuthorizationRow.approval_scheme == ApprovalScheme.USER_ED25519.value,
            AuthorizationRow.status == AuthorizationStatus.PENDING.value,
            AuthorizationRow.expires_at > moment,
            AuthorizationRow.binding_version == BINDING_VERSION,
            AuthorizationRow.transaction_digest == row.transaction_digest,
            AuthorizationRow.signing_key_id.is_(None),
            AuthorizationRow.approval_signature.is_(None),
        )
        .values(
            status=AuthorizationStatus.ACTIVE.value,
            signing_key_id=signing_key_id,
            approval_signature=signature_hex,
        )
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

    activated = await _reload(session, authorization_id)
    if activated is None:  # pragma: no cover - the UPDATE just matched this row
        raise AuthorizationNotFound(authorization_id, "authorization vanished after activation")
    await _audit(
        session,
        mission_id=activated.mission_id,
        event_type=EventType.AUTHORIZATION_ACTIVATED,
        payload={
            "authorization_id": str(activated.authorization_id),
            "status": activated.status,
            "approval_scheme": ApprovalScheme.USER_ED25519.value,
            "signing_key_id": signing_key_id,
            "transaction_digest": activated.transaction_digest,
        },
    )
    return activated


async def verify_authorization_for_payment(
    session: AsyncSession,
    *,
    row: AuthorizationRow,
    expected_status: AuthorizationStatus,
    now: datetime,
) -> BoundTransaction:
    """Rebuild, classify, and re-verify an authorization before payment work."""
    transaction = rebuild_bound_transaction(row)
    if row.binding_version != BINDING_VERSION:
        raise TransactionBindingFailure(
            row.authorization_id,
            f"unsupported binding version {row.binding_version!r}",
        )
    if row.status != expected_status.value:
        if expected_status == AuthorizationStatus.ACTIVE:
            await _classify_and_raise(
                session,
                authorization_id=row.authorization_id,
                transaction=transaction,
                now=now,
                expected_status=expected_status,
            )
        raise AuthorizationNotActive(
            row.authorization_id,
            f"authorization is {row.status}, expected {expected_status.value}",
        )
    if now >= as_utc(row.expires_at):
        if expected_status == AuthorizationStatus.ACTIVE:
            await expire_if_stale(session, authorization_id=row.authorization_id, now=now)
        raise AuthorizationExpired(
            row.authorization_id,
            f"authorization expired at {as_utc(row.expires_at).isoformat()}",
        )

    await _require_policy_scheme(session, row)
    if row.approval_scheme == ApprovalScheme.POLICY_AUTO.value:
        if row.signing_key_id is not None or row.approval_signature is not None:
            raise AuthorizationProofFailure(
                row.authorization_id,
                "POLICY_AUTO authorization unexpectedly carries proof metadata",
                reason_code=ReasonCode.AUTHORIZATION_APPROVAL_SCHEME_INVALID.value,
            )
        return transaction
    if row.approval_scheme != ApprovalScheme.USER_ED25519.value:
        raise AuthorizationProofFailure(
            row.authorization_id,
            "migration-only or unknown authorization origin cannot authorize payment",
            reason_code=ReasonCode.AUTHORIZATION_APPROVAL_SCHEME_INVALID.value,
        )
    if row.signing_key_id is None or row.approval_signature is None:
        raise AuthorizationProofFailure(
            row.authorization_id,
            "USER_ED25519 authorization is missing its durable proof",
            reason_code=ReasonCode.AUTHORIZATION_PROOF_MISSING.value,
        )
    _verify_supplied_user_proof(
        row,
        signing_key_id=row.signing_key_id,
        signature_hex=row.approval_signature,
    )
    return transaction


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
