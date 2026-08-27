import uuid

import pytest
from apps.api.db.models import AuditEventRow, Mission
from packages.schemas.domain import EventType, MissionState
from services.audit_ledger.hashing import GENESIS_HASH, compute_event_hash
from services.audit_ledger.ledger import append_event, list_events

pytestmark = pytest.mark.asyncio


async def _mk_mission(session) -> Mission:
    m = Mission(id=uuid.uuid4(), quantity=1, state=MissionState.CREATED.value)
    session.add(m)
    await session.flush()
    return m


async def test_sequence_is_monotonic_and_starts_at_zero(session):
    m = await _mk_mission(session)
    e0 = await append_event(
        session, mission_id=m.id, event_type=EventType.MISSION_CREATED, actor="t"
    )
    e1 = await append_event(session, mission_id=m.id, event_type=EventType.INTENT_PARSED, actor="t")
    assert e0.sequence == 0
    assert e1.sequence == 1
    assert e0.previous_hash == GENESIS_HASH
    assert e1.previous_hash == e0.event_hash


async def test_hash_chain_links_and_recomputes(session):
    m = await _mk_mission(session)
    e = await append_event(
        session, mission_id=m.id, event_type=EventType.MISSION_CREATED, actor="t", payload={"a": 1}
    )
    recomputed = compute_event_hash(
        mission_id=str(m.id),
        sequence=e.sequence,
        event_type=e.event_type,
        actor=e.actor,
        payload=e.payload,
        previous_hash=e.previous_hash,
        created_at=e.created_at,
    )
    assert recomputed == e.event_hash


async def test_duplicate_sequence_rejected_by_unique_constraint(session):
    from sqlalchemy.exc import IntegrityError

    m = await _mk_mission(session)
    await append_event(session, mission_id=m.id, event_type=EventType.MISSION_CREATED, actor="t")
    # Force a duplicate sequence to prove append-only integrity is enforced.
    dup = AuditEventRow(
        event_id=uuid.uuid4(),
        mission_id=m.id,
        sequence=0,
        event_type="X",
        actor="t",
        payload={},
        previous_hash=GENESIS_HASH,
        event_hash="deadbeef",
    )
    session.add(dup)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_list_events_ordered(session):
    m = await _mk_mission(session)
    for et in (EventType.MISSION_CREATED, EventType.INTENT_PARSED, EventType.DISCOVERY_STARTED):
        await append_event(session, mission_id=m.id, event_type=et, actor="t")
    rows = await list_events(session, m.id)
    assert [r.sequence for r in rows] == [0, 1, 2]
