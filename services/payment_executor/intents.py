"""Payment intent creation — the atomicity and idempotency core of Phase 4.

This module answers one question correctly: *given a payment request, does a
new logical payment come into existence, and if so exactly once?*

The transaction shape
---------------------
Everything that must be true together is written in ONE database transaction,
inside a SAVEPOINT::

    BEGIN
      SELECT payment_intents WHERE idempotency_key = :k      -- fast path
        hit -> fingerprint equal ? REUSE : IDEMPOTENCY_CONFLICT (deny)
      SAVEPOINT sp
        INSERT payment_intents            (UNIQUE idempotency_key decides races)
        consume_authorization(...)        (Phase 3 atomic conditional UPDATE)
        INSERT audit_events               PAYMENT_INTENT_CREATED / PAYMENT_QUEUED
        INSERT outbox_events              PAYMENT_CREATE_REQUESTED
        mission AUTHORIZED -> PAYMENT_PENDING
      RELEASE sp
    COMMIT

Two ordering decisions carry the weight:

**The INSERT goes first, before the authorization is consumed.** A same-key race
is then refused by the unique index while the authorization is still untouched,
so the loser reports the accurate cause (a duplicate request) rather than the
misleading one (a replayed authorization), and no authorization is spent to
discover that.

**The SAVEPOINT wraps the INSERT *and* the consume together.** This is what
makes "if the transaction rolls back, authorization consumption rolls back too"
literally true. A loser that reaches the unique violation after consuming its
own authorization — possible when two requests share a key but hold different
authorizations — rolls back to the savepoint and gives the authorization back
unspent.

What the caller may NOT supply
------------------------------
The transaction. There is no parameter for it. The executor rebuilds the
``BoundTransaction`` from the authorization row's server-held columns and the
kernel-held nonce, and re-verifies the digest. A caller therefore cannot present
a mutated amount, merchant, or product — not because the value would be
rejected, but because there is no field through which to offer one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from apps.api.db.models import AuthorizationRow, Mission, PaymentIntentRow
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import EventType, MissionState, ReasonCode, as_utc, utcnow
from packages.schemas.payment import (
    OutboxEventType,
    PaymentIntentState,
    request_fingerprint,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_orchestrator.state_machine import can_transition
from services.audit_ledger.ledger import append_event
from services.payment_executor.outbox import enqueue_outbox_event
from services.payment_executor.state_machine import assert_payment_transition
from services.security_kernel.authorization import (
    AuthorizationNotFound,
    consume_authorization,
    verify_authorization_for_payment,
)
from services.security_kernel.capability_registry import enforce_registered

ACTOR = "payment-executor"

#: How much of the digest is safe to write into an audit payload. Same rule as
#: Phase 3: enough to correlate events, never a copy of the commitment.
DIGEST_LOG_PREFIX = 16


class PaymentRequestRejected(Exception):
    """A payment request that must not produce (or reuse) a payment intent."""

    reason_code: str = "PAYMENT_REQUEST_REJECTED"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.detail = detail


class IdempotencyConflict(PaymentRequestRejected):
    """The idempotency key was reused for a materially different request.

    Never resolved by reusing the original intent and never by creating a second
    one. Silently reusing would let a key minted for a small payment be
    presented for a large one; creating a second would break the key's only
    promise.
    """

    reason_code = ReasonCode.IDEMPOTENCY_CONFLICT.value


class MissionNotAuthorized(PaymentRequestRejected):
    """The mission is not in a state from which a payment may begin."""

    reason_code = ReasonCode.MISSION_NOT_AUTHORIZED.value


@dataclass(frozen=True)
class PaymentIntentResult:
    """The outcome of a payment request.

    ``created`` distinguishes "a new logical payment came into existence" from
    "you are looking at the one that already did". Callers use it to choose 201
    vs 200 — and tests use it to assert that a retry consumed nothing.
    """

    intent: PaymentIntentRow
    created: bool


def _digest_prefix(digest: str) -> str:
    return digest[:DIGEST_LOG_PREFIX]


async def find_by_idempotency_key(
    session: AsyncSession, idempotency_key: str
) -> PaymentIntentRow | None:
    result = await session.execute(
        select(PaymentIntentRow).where(PaymentIntentRow.idempotency_key == idempotency_key)
    )
    return result.scalar_one_or_none()


async def payment_intent_for_mission(
    session: AsyncSession, mission_id: uuid.UUID
) -> PaymentIntentRow | None:
    result = await session.execute(
        select(PaymentIntentRow)
        .where(PaymentIntentRow.mission_id == mission_id)
        .order_by(PaymentIntentRow.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_existing(
    session: AsyncSession,
    *,
    existing: PaymentIntentRow,
    fingerprint: str,
    idempotency_key: str,
) -> PaymentIntentResult:
    """Decide whether a held intent satisfies this request, or conflicts with it.

    Equality is over the whole fingerprint rather than a hand-picked pair of
    fields, so a field added to the request without being added to the
    fingerprint is a visible omission instead of a silent hole.
    """
    if existing.request_fingerprint == fingerprint:
        await append_event(
            session,
            mission_id=existing.mission_id,
            event_type=EventType.PAYMENT_INTENT_REUSED,
            actor=ACTOR,
            payload={
                "payment_intent_id": str(existing.id),
                "idempotency_key": idempotency_key,
                "state": existing.state,
                # No authorization was consumed on this path. Recorded
                # explicitly because it is the invariant a retry must preserve.
                "authorization_consumed": False,
            },
        )
        return PaymentIntentResult(intent=existing, created=False)

    await append_event(
        session,
        mission_id=existing.mission_id,
        event_type=EventType.IDEMPOTENCY_CONFLICT,
        actor=ACTOR,
        payload={
            "reason_code": ReasonCode.IDEMPOTENCY_CONFLICT.value,
            "idempotency_key": idempotency_key,
            "existing_payment_intent_id": str(existing.id),
            # Fingerprints, never the differing values themselves: the point is
            # that they differ, and the values may describe a second mission.
            "existing_fingerprint_prefix": _digest_prefix(existing.request_fingerprint),
            "presented_fingerprint_prefix": _digest_prefix(fingerprint),
        },
    )
    raise IdempotencyConflict(
        f"idempotency key '{idempotency_key}' was already used for a different payment request"
    )


async def create_payment_intent(
    session: AsyncSession,
    *,
    capabilities: CapabilitySet,
    mission_id: uuid.UUID,
    authorization_id: uuid.UUID,
    idempotency_key: str,
    provider: str,
    now: datetime | None = None,
) -> PaymentIntentResult:
    """Establish exactly one logical payment, or return the one that exists.

    PRIVILEGED. Guarded by ``payment.execute``, which only the
    ``payment-executor`` principal holds. Enforcement runs before any read or
    write, so a denied caller leaves no trace and consumes no authorization.

    The caller does not supply the transaction, the amount, the merchant, or the
    currency — all of it is derived from the authorization the kernel issued.
    """
    # FIRST. A denied principal must not even learn whether the authorization
    # exists, and must certainly not reach the consume path.
    enforce_registered(capabilities, Capability.PAYMENT_EXECUTE)

    moment = as_utc(now or utcnow())

    authorization = await session.get(AuthorizationRow, authorization_id, populate_existing=True)
    if authorization is None:
        raise AuthorizationNotFound(authorization_id, "no such authorization")
    if authorization.mission_id != mission_id:
        # Refusing this is what stops one mission's approval from paying for
        # another mission's basket.
        raise PaymentRequestRejected(
            f"authorization {authorization_id} does not belong to mission {mission_id}"
        )

    existing = await find_by_idempotency_key(session, idempotency_key)

    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise PaymentRequestRejected(f"mission {mission_id} does not exist")
    if existing is None and mission.state != MissionState.AUTHORIZED.value:
        # Checked before proof verification, but still before every write.  An
        # idempotent retry is allowed to observe PAYMENT_PENDING and return its
        # already-durable intent below.
        raise MissionNotAuthorized(
            f"mission {mission_id} is {mission.state}, expected {MissionState.AUTHORIZED.value}"
        )

    # Phase 3 reconstruction always precedes proof verification.  A retry of
    # this authorization is already CONSUMED; a conflicting key held by some
    # other payment must leave this authorization ACTIVE and unspent.
    transaction = await verify_authorization_for_payment(
        session,
        row=authorization,
        expected_status=(
            AuthorizationStatus.CONSUMED
            if existing is not None and existing.authorization_id == authorization_id
            else AuthorizationStatus.ACTIVE
        ),
        now=moment,
    )

    fingerprint = request_fingerprint(
        mission_id=mission_id,
        authorization_id=authorization_id,
        transaction_digest=authorization.transaction_digest,
        amount_inr=transaction.amount_inr,
        currency=transaction.currency,
        merchant_id=transaction.merchant_id,
        provider=provider,
    )

    # Fast path: this key already named a payment.
    if existing is not None:
        return await _resolve_existing(
            session,
            existing=existing,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
        )

    intent_id = uuid.uuid4()
    try:
        # SAVEPOINT. The insert and the authorization consume must survive or
        # fail together; nothing between them may be left half-applied.
        async with session.begin_nested():
            intent = PaymentIntentRow(
                id=intent_id,
                mission_id=mission_id,
                authorization_id=authorization_id,
                transaction_digest=authorization.transaction_digest,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                amount_inr=transaction.amount_inr,
                currency=transaction.currency,
                merchant_id=transaction.merchant_id,
                provider=provider,
                provider_payment_id=None,
                state=PaymentIntentState.CREATED.value,
                attempts=0,
            )
            session.add(intent)
            # Forces the UNIQUE(idempotency_key) / UNIQUE(authorization_id)
            # checks to fire HERE, before the authorization is spent.
            await session.flush()

            # Phase 3's atomic conditional UPDATE. Validates status, expiry and
            # transaction binding in one statement, and raises
            # AUTHORIZATION_REPLAY_DETECTED if another request already won.
            await consume_authorization(
                session,
                authorization_id=authorization_id,
                transaction=transaction,
                now=moment,
            )

            assert_payment_transition(PaymentIntentState.CREATED, PaymentIntentState.QUEUED)
            intent.state = PaymentIntentState.QUEUED.value

            await append_event(
                session,
                mission_id=mission_id,
                event_type=EventType.PAYMENT_INTENT_CREATED,
                actor=ACTOR,
                payload={
                    "payment_intent_id": str(intent_id),
                    "authorization_id": str(authorization_id),
                    "idempotency_key": idempotency_key,
                    "transaction_digest_prefix": _digest_prefix(authorization.transaction_digest),
                    "amount_inr": transaction.amount_inr,
                    "currency": transaction.currency,
                    "merchant_id": transaction.merchant_id,
                    "provider": provider,
                    # NOTE: the nonce is deliberately absent, as in Phase 3.
                },
            )
            await append_event(
                session,
                mission_id=mission_id,
                event_type=EventType.PAYMENT_QUEUED,
                actor=ACTOR,
                payload={
                    "payment_intent_id": str(intent_id),
                    "state": PaymentIntentState.QUEUED.value,
                },
            )

            # The outbox row is written INSIDE this transaction. That is the
            # whole reason the provider can be called safely later: the
            # instruction to call it is durable before any call happens.
            await enqueue_outbox_event(
                session,
                payment_intent_id=intent_id,
                event_type=OutboxEventType.PAYMENT_CREATE_REQUESTED,
                payload={"idempotency_key": idempotency_key},
                available_at=moment,
            )

            if can_transition(MissionState(mission.state), MissionState.PAYMENT_PENDING):
                mission.state = MissionState.PAYMENT_PENDING.value
            await session.flush()

    except IntegrityError:
        # Another request committed the same idempotency key (or the same
        # authorization) while this one was mid-flight. Rolling back to the
        # savepoint undoes BOTH this insert and this transaction's authorization
        # consumption, so the loser spends nothing.
        #
        # `begin_nested` has already emitted ROLLBACK TO SAVEPOINT by the time
        # the exception surfaces here; the surrounding transaction is intact and
        # can still read. Under READ COMMITTED the winner is now visible,
        # because the unique violation could only be raised once it committed.
        winner = await find_by_idempotency_key(session, idempotency_key)
        if winner is None:
            # The collision was not on the idempotency key — the only other
            # unique key reachable here is authorization_id, i.e. a second
            # request tried to pay with an authorization already spent by a
            # different logical payment. Surfaced, never silently absorbed.
            raise
        return await _resolve_existing(
            session,
            existing=winner,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
        )

    return PaymentIntentResult(intent=intent, created=True)
