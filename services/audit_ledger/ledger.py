"""Append-only audit ledger backed by the audit_events table.

Each append computes the next per-mission sequence, links to the previous
event's hash, and persists an immutable record. The (mission_id, sequence)
UNIQUE constraint enforces append-only ordering at the database level.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.db.models import AuditEventRow
from packages.schemas.domain import EventType, utcnow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.hashing import GENESIS_HASH, compute_event_hash


async def _last_event(session: AsyncSession, mission_id: uuid.UUID) -> AuditEventRow | None:
    result = await session.execute(
        select(AuditEventRow)
        .where(AuditEventRow.mission_id == mission_id)
        .order_by(AuditEventRow.sequence.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def append_event(
    session: AsyncSession,
    *,
    mission_id: uuid.UUID,
    event_type: EventType,
    actor: str,
    payload: dict[str, Any] | None = None,
) -> AuditEventRow:
    payload = payload or {}
    prev = await _last_event(session, mission_id)
    sequence = 0 if prev is None else prev.sequence + 1
    previous_hash = GENESIS_HASH if prev is None else prev.event_hash
    created_at = utcnow()

    event_hash = compute_event_hash(
        mission_id=str(mission_id),
        sequence=sequence,
        event_type=event_type.value,
        actor=actor,
        payload=payload,
        previous_hash=previous_hash,
        created_at=created_at,
    )

    row = AuditEventRow(
        event_id=uuid.uuid4(),
        mission_id=mission_id,
        sequence=sequence,
        event_type=event_type.value,
        actor=actor,
        payload=payload,
        previous_hash=previous_hash,
        event_hash=event_hash,
        created_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row


async def list_events(session: AsyncSession, mission_id: uuid.UUID) -> list[AuditEventRow]:
    result = await session.execute(
        select(AuditEventRow)
        .where(AuditEventRow.mission_id == mission_id)
        .order_by(AuditEventRow.sequence.asc())
    )
    return list(result.scalars().all())
