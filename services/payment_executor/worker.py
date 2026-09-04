"""Outbox worker — claims durable events and drives them to the provider.

Deliberately NOT an HTTP route and NOT an agent tool. The provider is reachable
only from a worker consuming committed outbox rows, so there is no request an
agent (or an LLM controlling one) can make that results in a provider call
directly. The path from an agent to money runs through policy, authorization,
a durable intent, and this worker — never around them.

Claiming and handling use separate transactions. The claim is committed before
the provider call, so a crash leaves a durable IN_PROGRESS lease rather than
rolling the claim back to an indistinguishable PENDING event. For a provider
without idempotent create, handling commits a one-way fence before receipt
search or the only allowed create. Re-handling after lease expiry searches and
reconciles but cannot consume create permission twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from apps.api.db.models import OutboxEventRow, PaymentIntentRow
from packages.schemas.capability import CapabilitySet
from packages.schemas.domain import as_utc, utcnow
from packages.schemas.payment import OutboxEventType
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.payment_executor.executor import DispatchResult, dispatch_create
from services.payment_executor.outbox import (
    DEFAULT_LEASE,
    claim_next_event,
    reschedule_event,
)
from services.payment_executor.providers.base import PaymentProvider
from services.payment_executor.reconciliation import reconcile_intent
from services.security_kernel.capability_registry import capabilities_for

EXECUTOR_PRINCIPAL = "payment-executor"


@dataclass(frozen=True)
class WorkerOutcome:
    """What one worker turn did. ``event_id is None`` means the queue was idle."""

    event_id: uuid.UUID | None
    event_type: str | None
    result: DispatchResult | None


def executor_capabilities() -> CapabilitySet:
    """The trusted capability set for the executor principal.

    Fetched from the server-owned registry, never accepted from a caller — the
    same rule the rest of the kernel follows.
    """
    return capabilities_for(EXECUTOR_PRINCIPAL)


async def process_claimed_event(
    session: AsyncSession,
    *,
    provider: PaymentProvider,
    event: OutboxEventRow,
    capabilities: CapabilitySet | None = None,
    now: datetime | None = None,
) -> DispatchResult:
    """Route one already-claimed event to its handler."""
    caps = capabilities or executor_capabilities()
    moment = as_utc(now or utcnow())

    intent = await session.get(PaymentIntentRow, event.payment_intent_id, populate_existing=True)
    if intent is None:  # pragma: no cover - FK makes this unreachable
        raise ValueError(f"outbox event {event.id} references a missing payment intent")

    event_type = OutboxEventType(event.event_type)
    if event_type is OutboxEventType.PAYMENT_CREATE_REQUESTED:
        return await dispatch_create(
            session,
            capabilities=caps,
            provider=provider,
            intent=intent,
            event=event,
            now=moment,
        )
    return await reconcile_intent(
        session,
        capabilities=caps,
        provider=provider,
        intent=intent,
        event=event,
        now=moment,
    )


async def run_once(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    provider: PaymentProvider,
    worker_id: str = "worker-1",
    now: datetime | None = None,
    lease: timedelta = DEFAULT_LEASE,
) -> WorkerOutcome:
    """Claim and process at most one event across durable boundaries.

    An unexpected handler exception rolls back only handler state; the durable
    claim and its attempt increment remain. Non-idempotent create dispatch may
    also commit its one-way fence inside the handler transaction. A recovery
    transaction returns the event to the queue with backoff.
    """
    moment = as_utc(now or utcnow())

    async with sessionmaker() as claim_session:
        event = await claim_next_event(claim_session, worker_id=worker_id, now=moment, lease=lease)
        if event is None:
            await claim_session.commit()
            return WorkerOutcome(event_id=None, event_type=None, result=None)

        event_id, event_type = event.id, event.event_type
        await claim_session.commit()

    async with sessionmaker() as work_session:
        claimed = await work_session.get(OutboxEventRow, event_id, populate_existing=True)
        if claimed is None:  # pragma: no cover - the FK-backed row cannot vanish here
            raise ValueError(f"claimed outbox event {event_id} no longer exists")
        if claimed.claimed_by != worker_id:
            raise ValueError(
                f"worker {worker_id!r} does not own outbox event {event_id}; "
                f"claimed_by={claimed.claimed_by!r}"
            )

        try:
            result = await process_claimed_event(
                work_session, provider=provider, event=claimed, now=moment
            )
            await work_session.commit()
            return WorkerOutcome(event_id=event_id, event_type=event_type, result=result)
        except Exception as exc:  # noqa: BLE001 - the handler's failure is data
            await work_session.rollback()
            async with sessionmaker() as recovery:
                stale = await recovery.get(OutboxEventRow, event_id, populate_existing=True)
                if stale is not None:
                    # The claim transaction already persisted the attempt.
                    # Only the handler's local work was rolled back.
                    await reschedule_event(
                        recovery,
                        event=stale,
                        reason=f"{type(exc).__name__}: {exc}",
                        now=moment,
                    )
                await recovery.commit()
            raise


async def drain(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    provider: PaymentProvider,
    worker_id: str = "worker-1",
    max_events: int = 20,
    now: datetime | None = None,
) -> list[WorkerOutcome]:
    """Process due events until the queue is empty or ``max_events`` is reached.

    The cap is a guard, not a silent truncation: hitting it means events remain
    due, and the caller's own loop is expected to come back around.
    """
    outcomes: list[WorkerOutcome] = []
    for _ in range(max_events):
        outcome = await run_once(sessionmaker, provider=provider, worker_id=worker_id, now=now)
        if outcome.event_id is None:
            break
        outcomes.append(outcome)
    return outcomes
