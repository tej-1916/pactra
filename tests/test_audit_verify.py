"""Audit chain verification — the happy paths and the structural rules.

Corruption lives in tests/test_audit_corruption.py; this file establishes what
"valid" means, including the two cases that are easy to get wrong: an empty
chain and a chain whose rows arrive in the wrong order.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from apps.api.db.models import AuditEventRow, Mission
from packages.schemas.audit import AuditReasonCode
from packages.schemas.domain import EventType, MissionState
from services.audit_ledger.hashing import GENESIS_HASH, compute_event_hash
from services.audit_ledger.ledger import append_event, list_events
from services.audit_ledger.verify import verify_events, verify_mission_chain

pytestmark = pytest.mark.asyncio


async def _mission(session) -> Mission:
    mission = Mission(id=uuid.uuid4(), quantity=1, state=MissionState.CREATED.value)
    session.add(mission)
    await session.flush()
    return mission


async def _chain(session, mission, length: int) -> list[AuditEventRow]:
    types = [
        EventType.MISSION_CREATED,
        EventType.INTENT_PARSED,
        EventType.DISCOVERY_STARTED,
        EventType.OFFERS_RECEIVED,
        EventType.OFFERS_NORMALIZED,
    ]
    rows = []
    for index in range(length):
        rows.append(
            await append_event(
                session,
                mission_id=mission.id,
                event_type=types[index % len(types)],
                actor="test",
                payload={"index": index},
            )
        )
    return rows


async def test_empty_chain_is_valid_and_checks_zero_events(session):
    """A mission with no events has nothing to tamper with.

    Reported valid with zero events checked — which is NOT a claim that no
    events were deleted. A per-mission chain cannot establish that; the
    verifier's docstring says so and this test does not pretend otherwise.
    """
    mission = await _mission(session)
    result = await verify_mission_chain(session, mission.id)
    assert result.valid is True
    assert result.events_checked == 0
    assert result.reason_code is AuditReasonCode.AUDIT_VALID
    assert result.first_invalid_sequence is None


async def test_single_event_chain_verifies(session):
    mission = await _mission(session)
    await append_event(
        session, mission_id=mission.id, event_type=EventType.MISSION_CREATED, actor="t"
    )
    result = await verify_mission_chain(session, mission.id)
    assert result.valid is True
    assert result.events_checked == 1


async def test_multi_event_chain_verifies(session):
    mission = await _mission(session)
    await _chain(session, mission, 17)
    result = await verify_mission_chain(session, mission.id)
    assert result.valid is True
    assert result.events_checked == 17
    assert result.reason_code is AuditReasonCode.AUDIT_VALID


async def test_chain_verifies_after_a_session_boundary(sessionmaker):
    """The regression that motivated normalizing created_at inside the hash.

    SQLite has no timezone-aware type: the writer hashes an AWARE UTC value and
    a later session reads back a NAIVE one, whose isoformat drops the offset.
    Before the fix, every chain verified inside the writing session and failed
    the moment it was re-read — the exact conditions the /verify endpoint runs
    under.
    """
    async with sessionmaker() as writer:
        mission = await _mission(writer)
        mission_id = mission.id
        await _chain(writer, mission, 6)
        await writer.commit()

    async with sessionmaker() as reader:
        result = await verify_mission_chain(reader, mission_id)
    assert result.valid is True, result.detail
    assert result.events_checked == 6


async def test_float_and_unicode_payloads_survive_the_json_round_trip(sessionmaker):
    """Canonical serialization must be stable across a storage round trip.

    Floats, nulls, booleans, nested objects and non-ASCII strings all go into a
    payload, get written as JSON, and come back. If any of them re-serialized
    differently the recomputed hash would differ and this chain would read as
    tampered.
    """
    payload = {
        "rating": 4.2,
        "trust": 0.75,
        "absent": None,
        "flag": True,
        "count": 0,
        "title": "Aurora Buds — ₹3,799 «pro»",
        "nested": {"b": [1, 2, 3], "a": {"deep": "value"}},
    }
    async with sessionmaker() as writer:
        mission = await _mission(writer)
        mission_id = mission.id
        await append_event(
            writer,
            mission_id=mission.id,
            event_type=EventType.OFFERS_NORMALIZED,
            actor="test",
            payload=payload,
        )
        await writer.commit()

    async with sessionmaker() as reader:
        result = await verify_mission_chain(reader, mission_id)
        rows = await list_events(reader, mission_id)
    assert result.valid is True, result.detail
    assert rows[0].payload == payload


async def test_verification_is_independent_of_retrieval_order(session):
    """Sequence is inside the preimage, so a shuffled read verifies identically.

    The verifier re-sorts rather than trusting the caller's ORDER BY. A
    reordering at the retrieval boundary is therefore not a way to make a good
    chain look bad, nor a bad one look good.
    """
    mission = await _mission(session)
    rows = await _chain(session, mission, 9)

    shuffled = [rows[i] for i in (4, 0, 8, 2, 7, 1, 6, 3, 5)]
    assert [r.sequence for r in shuffled] != list(range(9))

    ordered_result = verify_events(mission.id, rows)
    shuffled_result = verify_events(mission.id, shuffled)
    assert ordered_result == shuffled_result
    assert shuffled_result.valid is True
    assert shuffled_result.events_checked == 9


async def test_verifier_uses_the_writers_hash_function(session):
    """No second implementation. The verifier's recomputation must equal what
    `compute_event_hash` produces for the same row, or the two could drift."""
    mission = await _mission(session)
    rows = await _chain(session, mission, 3)
    for row in rows:
        assert row.event_hash == compute_event_hash(
            mission_id=str(row.mission_id),
            sequence=row.sequence,
            event_type=row.event_type,
            actor=row.actor,
            payload=row.payload,
            previous_hash=row.previous_hash,
            created_at=row.created_at,
        )


async def test_aware_utc_hashing_is_unchanged_by_the_normalization():
    """The created_at fix must not have changed any historical hash.

    `as_utc` is identity on an already-aware UTC value — which is every value
    the writer has ever passed — so the preimage, and therefore every hash
    already in the database, is byte-identical. This pins that: the hash of a
    known aware input equals the hash of the same instant expressed naively.
    """
    aware = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
    naive = aware.replace(tzinfo=None)
    fields = dict(
        mission_id="11111111-1111-1111-1111-111111111111",
        sequence=0,
        event_type="MISSION_CREATED",
        actor="orchestrator",
        payload={"a": 1},
        previous_hash=GENESIS_HASH,
    )
    assert compute_event_hash(**fields, created_at=aware) == compute_event_hash(
        **fields, created_at=naive
    )
    # And a genuinely different instant still hashes differently, so the
    # normalization has not made created_at stop mattering.
    assert compute_event_hash(**fields, created_at=aware) != compute_event_hash(
        **fields, created_at=aware + timedelta(microseconds=1)
    )


async def test_two_missions_have_independent_chains(session):
    """Verification is per mission. One mission's events must not participate
    in another's chain, or a tamper in one could be masked by the other."""
    first = await _mission(session)
    second = await _mission(session)
    await _chain(session, first, 4)
    await _chain(session, second, 2)

    assert (await verify_mission_chain(session, first.id)).events_checked == 4
    assert (await verify_mission_chain(session, second.id)).events_checked == 2
    assert (await verify_mission_chain(session, first.id)).valid is True
    assert (await verify_mission_chain(session, second.id)).valid is True
