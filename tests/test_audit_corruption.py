"""Corruption detection — AUDIT EVENT MODIFIED -> VERIFICATION FAILURE.

Every test here writes a legitimate chain through the real ledger, then reaches
PAST the application and edits the database rows directly with UPDATE/DELETE.
That is the point: an attacker with database access does not go through
`append_event`, so a tamper-evidence test that mutates through the application
proves nothing about the case that matters.

Two rules hold throughout:

* the event is NEVER repaired before verification — the verifier has to find it
  broken, not find it fixed;
* verification NEVER writes — each test re-reads the row afterwards and asserts
  the tampered values are still exactly as the attacker left them. A verifier
  that silently recomputed a hash on read would pass every assertion above and
  still have destroyed the evidence.
"""

import uuid

import pytest
from apps.api.db.models import AuditEventRow, Mission
from packages.schemas.audit import AuditReasonCode
from packages.schemas.domain import EventType, MissionState
from services.audit_ledger.hashing import GENESIS_HASH
from services.audit_ledger.ledger import append_event, list_events
from services.audit_ledger.verify import verify_mission_chain
from sqlalchemy import delete, update

pytestmark = pytest.mark.asyncio

CHAIN_LENGTH = 8


async def _mission_with_chain(session, length: int = CHAIN_LENGTH):
    mission = Mission(id=uuid.uuid4(), quantity=1, state=MissionState.CREATED.value)
    session.add(mission)
    await session.flush()
    for index in range(length):
        await append_event(
            session,
            mission_id=mission.id,
            event_type=EventType.MISSION_CREATED if index == 0 else EventType.SECURITY_VIOLATION,
            actor="test",
            payload={"index": index, "reason_code": "AUTHORITY_ESCALATION"},
        )
    await session.flush()
    return mission


async def _tamper(session, mission_id: uuid.UUID, at_sequence: int, **values) -> None:
    """Edit a persisted event exactly as somebody with DB access would.

    `synchronize_session=False` plus `expunge_all` keeps the ORM identity map
    from serving a pre-tamper copy back to the verifier, which would make the
    test verify the row we meant to corrupt instead of the corrupted one.
    Expunge rather than expire: an expired attribute triggers a lazy refresh,
    which an AsyncSession cannot perform from synchronous attribute access.
    """
    await session.execute(
        update(AuditEventRow)
        .where(AuditEventRow.mission_id == mission_id, AuditEventRow.sequence == at_sequence)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    session.expunge_all()


async def _row(session, mission_id: uuid.UUID, sequence: int) -> AuditEventRow:
    rows = await list_events(session, mission_id)
    return next(row for row in rows if row.sequence == sequence)


# --------------------------------------------------------------------------- #
# 1. The control
# --------------------------------------------------------------------------- #
async def test_untouched_chain_verifies(session):
    mission = await _mission_with_chain(session)
    result = await verify_mission_chain(session, mission.id)
    assert result.valid is True
    assert result.events_checked == CHAIN_LENGTH
    assert result.reason_code is AuditReasonCode.AUDIT_VALID


# --------------------------------------------------------------------------- #
# 2. Payload mutation — the canonical "someone edited history" case
# --------------------------------------------------------------------------- #
async def test_payload_mutation_is_detected(session):
    mission = await _mission_with_chain(session)
    await _tamper(session, mission.id, 5, payload={"index": 5, "reason_code": "WITHIN_LIMITS"})

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH
    assert result.first_invalid_sequence == 5
    assert result.events_checked == 5
    assert result.expected_hash != result.actual_hash

    # The verifier repaired nothing: the forged payload is still in the row and
    # the stored hash is still the one that no longer matches it.
    row = await _row(session, mission.id, 5)
    assert row.payload["reason_code"] == "WITHIN_LIMITS"
    assert row.event_hash == result.actual_hash


async def test_actor_mutation_is_detected(session):
    """The actor is inside the preimage, so relabelling who did something is
    tampering — attributing a kernel refusal to a merchant would otherwise be
    free."""
    mission = await _mission_with_chain(session)
    await _tamper(session, mission.id, 2, actor="merchant_a")

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH
    assert result.first_invalid_sequence == 2


async def test_event_type_mutation_is_detected(session):
    mission = await _mission_with_chain(session)
    await _tamper(session, mission.id, 3, event_type=EventType.POLICY_DECISION.value)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH
    assert result.first_invalid_sequence == 3


# --------------------------------------------------------------------------- #
# 3. event_hash mutation
# --------------------------------------------------------------------------- #
async def test_event_hash_mutation_is_detected(session):
    """Rewriting the hash instead of the content does not help the attacker.

    It is caught at the event itself (its contents no longer hash to it), not
    merely at the next link — so truncating the read at that point still finds
    it.
    """
    mission = await _mission_with_chain(session)
    forged = "f" * 64
    await _tamper(session, mission.id, 4, event_hash=forged)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH
    assert result.first_invalid_sequence == 4
    assert result.actual_hash == forged

    row = await _row(session, mission.id, 4)
    assert row.event_hash == forged


async def test_recomputing_the_hash_after_a_payload_edit_still_fails(session):
    """The sophisticated attempt: edit the payload AND fix that event's own hash.

    The chain still breaks, one event later, because the NEXT event's
    previous_hash commits to the original. Repairing the whole tail would mean
    rewriting every subsequent event — which is exactly the cost a hash chain
    exists to impose.
    """
    from services.audit_ledger.hashing import compute_event_hash

    mission = await _mission_with_chain(session)
    victim = await _row(session, mission.id, 3)
    forged_payload = {"index": 3, "reason_code": "WITHIN_LIMITS"}
    consistent_hash = compute_event_hash(
        mission_id=str(victim.mission_id),
        sequence=victim.sequence,
        event_type=victim.event_type,
        actor=victim.actor,
        payload=forged_payload,
        previous_hash=victim.previous_hash,
        created_at=victim.created_at,
    )
    await _tamper(session, mission.id, 3, payload=forged_payload, event_hash=consistent_hash)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_PREVIOUS_HASH_MISMATCH
    assert result.first_invalid_sequence == 4
    assert result.events_checked == 4


# --------------------------------------------------------------------------- #
# 4. previous_hash mutation
# --------------------------------------------------------------------------- #
async def test_previous_hash_mutation_is_detected(session):
    mission = await _mission_with_chain(session)
    await _tamper(session, mission.id, 6, previous_hash="a" * 64)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_PREVIOUS_HASH_MISMATCH
    assert result.first_invalid_sequence == 6
    assert result.actual_hash == "a" * 64

    row = await _row(session, mission.id, 6)
    assert row.previous_hash == "a" * 64


# --------------------------------------------------------------------------- #
# 5. Sequence tampering
# --------------------------------------------------------------------------- #
async def test_sequence_renumbering_creates_a_detected_gap(session):
    """Pushing an event's sequence forward leaves a hole where it used to be."""
    mission = await _mission_with_chain(session)
    await _tamper(session, mission.id, 5, sequence=99)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_SEQUENCE_GAP
    # Position 5 in the sorted run is now the event numbered 6.
    assert result.first_invalid_sequence == 6
    assert result.events_checked == 5


async def test_deleting_a_middle_event_is_detected(session):
    """A removed middle event breaks the contiguous run AND the linkage.

    The sequence gap is reported because it is found first, and it is the more
    precise finding: it names the position that is missing rather than the
    survivor that no longer links.
    """
    mission = await _mission_with_chain(session)
    await session.execute(
        delete(AuditEventRow).where(
            AuditEventRow.mission_id == mission.id, AuditEventRow.sequence == 3
        )
    )
    session.expunge_all()

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_SEQUENCE_GAP
    assert result.first_invalid_sequence == 4
    assert result.events_checked == 3

    remaining = await list_events(session, mission.id)
    assert [row.sequence for row in remaining] == [0, 1, 2, 4, 5, 6, 7]


async def test_deleting_the_first_event_is_detected(session):
    """Removing event 0 leaves a chain whose head links to a hash nobody holds."""
    mission = await _mission_with_chain(session)
    await session.execute(
        delete(AuditEventRow).where(
            AuditEventRow.mission_id == mission.id, AuditEventRow.sequence == 0
        )
    )
    session.expunge_all()

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_SEQUENCE_GAP
    assert result.first_invalid_sequence == 1
    assert result.events_checked == 0


async def test_injecting_an_extra_event_is_detected(session):
    """An appended event cannot be forged without the chain head's hash.

    Here the attacker inserts a plausible event at the end with a made-up
    previous_hash. Sequence continuity holds, so the linkage check is what
    catches it.
    """
    mission = await _mission_with_chain(session)
    session.add(
        AuditEventRow(
            event_id=uuid.uuid4(),
            mission_id=mission.id,
            sequence=CHAIN_LENGTH,
            event_type=EventType.PAYMENT_SUCCEEDED.value,
            actor="attacker",
            payload={"state": "SUCCEEDED"},
            previous_hash="b" * 64,
            event_hash="c" * 64,
            created_at=(await _row(session, mission.id, 0)).created_at,
        )
    )
    await session.flush()
    session.expunge_all()

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_PREVIOUS_HASH_MISMATCH
    assert result.first_invalid_sequence == CHAIN_LENGTH


# --------------------------------------------------------------------------- #
# 6. Genesis
# --------------------------------------------------------------------------- #
async def test_corrupt_genesis_previous_hash_is_detected(session):
    mission = await _mission_with_chain(session)
    await _tamper(session, mission.id, 0, previous_hash="1" * 64)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_GENESIS_INVALID
    assert result.first_invalid_sequence == 0
    assert result.events_checked == 0
    assert result.expected_hash == GENESIS_HASH
    assert result.actual_hash == "1" * 64


async def test_genesis_check_precedes_the_hash_check(session):
    """A first event whose previous_hash is wrong is reported as a genesis
    failure, not as a hash mismatch — the more specific finding wins, because
    "this chain does not start correctly" tells an operator more than "byte
    somewhere differs"."""
    mission = await _mission_with_chain(session, length=1)
    await _tamper(session, mission.id, 0, previous_hash="e" * 64)
    result = await verify_mission_chain(session, mission.id)
    assert result.reason_code is AuditReasonCode.AUDIT_GENESIS_INVALID


# --------------------------------------------------------------------------- #
# 7. Structurally malformed rows
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "values,expected_detail_fragment",
    [
        ({"event_hash": "not-a-hash"}, "event_hash is not 64"),
        ({"previous_hash": "short"}, "previous_hash is not 64"),
        ({"event_hash": "F" * 64}, "event_hash is not 64"),
        ({"actor": ""}, "actor is empty"),
        ({"event_type": ""}, "event_type is empty"),
    ],
)
async def test_malformed_rows_are_rejected_before_hashing(
    session, values, expected_detail_fragment
):
    """A row that is not shaped like an audit event gets a structural verdict.

    Uppercase hex is included deliberately: `hexdigest()` emits lowercase, so an
    uppercased hash is already an edited column even though it decodes to the
    same bytes.
    """
    mission = await _mission_with_chain(session, length=4)
    await _tamper(session, mission.id, 2, **values)

    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_EVENT_MALFORMED
    assert expected_detail_fragment in (result.detail or "")


async def test_negative_sequence_is_malformed(session):
    mission = await _mission_with_chain(session, length=3)
    await _tamper(session, mission.id, 1, sequence=-1)
    result = await verify_mission_chain(session, mission.id)
    assert result.valid is False
    assert result.reason_code is AuditReasonCode.AUDIT_EVENT_MALFORMED


# --------------------------------------------------------------------------- #
# 8. The verifier itself must never write
# --------------------------------------------------------------------------- #
async def test_verification_leaves_the_database_untouched(sessionmaker):
    """Read a corrupt chain twice across separate sessions with a commit in
    between. If verification had healed anything, the second run would pass."""
    async with sessionmaker() as writer:
        mission = await _mission_with_chain(writer)
        mission_id = mission.id
        await _tamper(writer, mission_id, 4, payload={"tampered": True})
        await writer.commit()

    async with sessionmaker() as first:
        first_result = await verify_mission_chain(first, mission_id)
        # A commit here would persist anything the verifier had staged.
        await first.commit()

    async with sessionmaker() as second:
        second_result = await verify_mission_chain(second, mission_id)
        rows = await list_events(second, mission_id)

    assert first_result.valid is False
    assert second_result == first_result
    assert rows[4].payload == {"tampered": True}
    assert len(rows) == CHAIN_LENGTH


async def test_no_new_audit_event_is_written_by_verification(session):
    """Verification is not itself an auditable action here. It must not append
    to the very chain it is inspecting — that would change the head hash and
    make each verification invalidate the next one's expectations."""
    mission = await _mission_with_chain(session)
    before = await list_events(session, mission.id)
    await verify_mission_chain(session, mission.id)
    await session.flush()
    after = await list_events(session, mission.id)
    assert len(after) == len(before)
    assert [row.event_hash for row in after] == [row.event_hash for row in before]
