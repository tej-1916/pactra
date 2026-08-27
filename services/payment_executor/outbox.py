"""Transactional outbox: enqueue, claim, complete, retry, dead-letter.

Why an outbox is here at all
----------------------------
The spec says to use one "only where it improves correctness". It does, at
exactly one place: between deciding to pay and calling the provider. Without it
the two are either the same step — which means calling a provider from inside an
open transaction that may still roll back — or two steps with nothing durable
between them, which means a crash loses the instruction entirely. The outbox row
is written in the SAME transaction as the payment intent, so after COMMIT the
instruction to call the provider is as durable as the decision to pay.

Claiming
--------
Two workers must never process one event concurrently. The mechanism is
dialect-appropriate rather than pretended-portable:

* **PostgreSQL** — ``SELECT ... FOR UPDATE SKIP LOCKED`` inside the claiming
  UPDATE. The row lock is held for the claiming transaction, and a concurrent
  worker skips the locked row instead of blocking on it.
* **SQLite and anything else** — an atomic conditional UPDATE whose WHERE clause
  restates everything the candidate SELECT observed (``status`` and
  ``available_at``). ``rowcount`` decides, exactly as in the Phase 3
  authorization consume. A worker that lost the race matched zero rows and
  claimed nothing.

Both give the same guarantee. Neither uses a read-then-write in Python.

The lease
---------
Claiming pushes ``available_at`` forward by a lease interval and sets the status
to IN_PROGRESS. A worker that dies mid-dispatch therefore leaves an event that
becomes claimable again once the lease lapses — crash recovery falls out of the
same field that schedules retries, instead of needing a separate reaper. The
cost is that a genuinely slow dispatch can be re-claimed while still running,
which is why every handler downstream is required to be idempotent regardless.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, cast

from apps.api.db.models import OutboxEventRow
from packages.schemas.domain import as_utc, utcnow
from packages.schemas.payment import OutboxEventType, OutboxStatus
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

#: How long a claim is honoured before the event may be re-claimed. Long enough
#: that a healthy provider call finishes inside it; short enough that a crashed
#: worker does not strand a payment.
DEFAULT_LEASE = timedelta(seconds=30)

#: Retry backoff, capped. Index is the attempt count already made.
_BACKOFF_SECONDS = (1, 2, 5, 15, 30, 60, 120, 300)

DEFAULT_MAX_ATTEMPTS = 8


def backoff_for(attempts: int) -> timedelta:
    """Delay before the next attempt, capped at the final step."""
    index = min(max(attempts - 1, 0), len(_BACKOFF_SECONDS) - 1)
    return timedelta(seconds=_BACKOFF_SECONDS[index])


async def enqueue_outbox_event(
    session: AsyncSession,
    *,
    payment_intent_id: uuid.UUID,
    event_type: OutboxEventType,
    payload: dict[str, Any] | None = None,
    available_at: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> OutboxEventRow:
    """Write an outbox row. MUST be called inside the caller's transaction.

    This function deliberately does not commit. Committing here would break the
    single property the outbox exists to provide: that the row becomes durable
    at the same instant as the state it describes, never before and never after.
    """
    row = OutboxEventRow(
        id=uuid.uuid4(),
        payment_intent_id=payment_intent_id,
        event_type=event_type.value,
        payload=payload or {},
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=max_attempts,
        available_at=as_utc(available_at or utcnow()),
    )
    session.add(row)
    await session.flush()
    return row


async def claim_next_event(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime | None = None,
    lease: timedelta = DEFAULT_LEASE,
) -> OutboxEventRow | None:
    """Atomically claim one due event, or return None.

    Due means: PENDING and scheduled, or IN_PROGRESS with an expired lease (the
    crashed-worker case). Returns the claimed row; the caller owns it until the
    lease lapses.
    """
    moment = as_utc(now or utcnow())
    lease_until = moment + lease

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        claimed_id = await _claim_postgres(
            session, worker_id=worker_id, now=moment, lease_until=lease_until
        )
    else:
        claimed_id = await _claim_conditional(
            session, worker_id=worker_id, now=moment, lease_until=lease_until
        )

    if claimed_id is None:
        return None
    return await session.get(OutboxEventRow, claimed_id, populate_existing=True)


def _due_predicate(moment: datetime):
    """Events a worker may take: scheduled PENDING, or IN_PROGRESS past lease."""
    return (
        OutboxEventRow.status.in_((OutboxStatus.PENDING.value, OutboxStatus.IN_PROGRESS.value))
    ) & (OutboxEventRow.available_at <= moment)


async def _claim_postgres(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_until: datetime,
) -> uuid.UUID | None:
    """PostgreSQL claim via ``FOR UPDATE SKIP LOCKED``.

    The subquery takes a row lock and any concurrent claimer skips that row
    rather than queueing behind it, so N workers claim N distinct events instead
    of serializing on the head of the queue.
    """
    candidate = (
        select(OutboxEventRow.id)
        .where(_due_predicate(now))
        .order_by(OutboxEventRow.available_at.asc(), OutboxEventRow.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    result = await session.execute(
        update(OutboxEventRow)
        .where(OutboxEventRow.id == candidate)
        .values(
            status=OutboxStatus.IN_PROGRESS.value,
            attempts=OutboxEventRow.attempts + 1,
            claimed_by=worker_id,
            available_at=lease_until,
        )
        .returning(OutboxEventRow.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none()


async def _claim_conditional(
    session: AsyncSession,
    *,
    worker_id: str,
    now: datetime,
    lease_until: datetime,
) -> uuid.UUID | None:
    """Portable claim: an atomic conditional UPDATE decided by ``rowcount``.

    The WHERE clause restates BOTH values the candidate SELECT observed. If
    another worker claimed the event in between, it moved at least one of them,
    the UPDATE matches nothing, and this worker claimed nothing — the same
    compare-and-set discipline the Phase 3 authorization consume uses.
    """
    candidate = (
        await session.execute(
            select(OutboxEventRow.id, OutboxEventRow.status, OutboxEventRow.available_at)
            .where(_due_predicate(now))
            .order_by(OutboxEventRow.available_at.asc(), OutboxEventRow.created_at.asc())
            .limit(1)
        )
    ).first()
    if candidate is None:
        return None

    event_id, seen_status, seen_available_at = candidate
    result = cast(
        CursorResult,
        await session.execute(
            update(OutboxEventRow)
            .where(
                OutboxEventRow.id == event_id,
                OutboxEventRow.status == seen_status,
                OutboxEventRow.available_at == seen_available_at,
            )
            .values(
                status=OutboxStatus.IN_PROGRESS.value,
                attempts=OutboxEventRow.attempts + 1,
                claimed_by=worker_id,
                available_at=lease_until,
            )
            .execution_options(synchronize_session=False)
        ),
    )
    return event_id if result.rowcount == 1 else None


async def complete_event(
    session: AsyncSession,
    *,
    event: OutboxEventRow,
    now: datetime | None = None,
) -> None:
    """Mark an event permanently done."""
    moment = as_utc(now or utcnow())
    event.status = OutboxStatus.PROCESSED.value
    event.processed_at = moment
    event.last_error = None
    await session.flush()


async def reschedule_event(
    session: AsyncSession,
    *,
    event: OutboxEventRow,
    reason: str,
    now: datetime | None = None,
    delay: timedelta | None = None,
) -> bool:
    """Return an event to the queue with backoff, or dead-letter it.

    Returns True if it will be retried, False if it was dead-lettered.

    Dead-lettering sets the outbox row to FAILED and stops the worker from
    spinning; it deliberately does NOT make the payment intent terminal. An
    exhausted retry budget means "automatic recovery gave up", which is not the
    same claim as "this payment definitively failed" — and recording the
    stronger claim would be recording something unverified.
    """
    moment = as_utc(now or utcnow())
    event.last_error = reason[:200]

    if event.attempts >= event.max_attempts:
        event.status = OutboxStatus.FAILED.value
        event.processed_at = moment
        await session.flush()
        return False

    event.status = OutboxStatus.PENDING.value
    event.available_at = moment + (delay if delay is not None else backoff_for(event.attempts))
    await session.flush()
    return True


async def pending_events_for(
    session: AsyncSession, payment_intent_id: uuid.UUID
) -> list[OutboxEventRow]:
    result = await session.execute(
        select(OutboxEventRow)
        .where(
            OutboxEventRow.payment_intent_id == payment_intent_id,
            OutboxEventRow.status.in_((OutboxStatus.PENDING.value, OutboxStatus.IN_PROGRESS.value)),
        )
        .order_by(OutboxEventRow.available_at.asc())
    )
    return list(result.scalars().all())
