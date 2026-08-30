"""The replay reducer: exhaustiveness, determinism, and the integrity gate.

Realistic end-to-end mission replays live in tests/test_replay_missions.py;
side-effect isolation lives in tests/test_replay_isolation.py. This file pins
the reducer's contract.
"""

import uuid

import pytest
from apps.api.db.models import AuditEventRow, Mission
from packages.schemas.audit import (
    AuditReasonCode,
    MissionProjection,
    ReplayReasonCode,
)
from packages.schemas.domain import EventType, MissionState
from services.audit_ledger.hashing import compute_event_hash
from services.audit_ledger.ledger import append_event, list_events
from services.audit_ledger.replay import (
    HANDLERS,
    ReplayRefused,
    reduce_events,
    replay_mission,
)
from sqlalchemy import update

pytestmark = pytest.mark.asyncio


async def _mission(session, state=MissionState.CREATED) -> Mission:
    mission = Mission(id=uuid.uuid4(), quantity=1, state=state.value)
    session.add(mission)
    await session.flush()
    return mission


async def _small_chain(session, mission) -> None:
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.MISSION_CREATED,
        actor="orchestrator",
        payload={"raw_query": "earbuds", "quantity": 1},
    )
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.INTENT_PARSED,
        actor="orchestrator",
        payload={"constraints": {"soft_budget_inr": 4000, "hard_limit_inr": 4500}},
    )
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.DISCOVERY_STARTED,
        actor="orchestrator",
        payload={},
    )


# --------------------------------------------------------------------------- #
# Exhaustiveness — the forward-safety contract
# --------------------------------------------------------------------------- #
async def test_every_event_type_has_a_reducer():
    """Adding an EventType without teaching replay what it means must FAIL HERE.

    This is what makes the fail-closed unknown-event policy honest: an event
    type this build declares is never "unknown", so refusing on unknown types
    cannot be triggered by our own omission — only by history written by a
    different build.
    """
    assert set(HANDLERS) == set(EventType), (
        "event types without a replay rule: "
        f"{sorted(t.value for t in set(EventType) - set(HANDLERS))}"
    )


async def test_unknown_event_type_is_refused_not_skipped(session):
    """An event type this build does not know stops the replay.

    Silently skipping it would produce a projection that LOOKS complete while
    omitting something that may be a security event — the single most
    misleading outcome available, so it is not an outcome this engine offers.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)

    # Rewrite an event type to something from a hypothetical future build, and
    # re-hash so the CHAIN still verifies. The refusal must come from the
    # reducer, not from the verifier catching a corrupted row.
    row = (await list_events(session, mission.id))[1]
    future_type = "MERCHANT_ATTESTATION_VERIFIED"
    rehashed = compute_event_hash(
        mission_id=str(row.mission_id),
        sequence=row.sequence,
        event_type=future_type,
        actor=row.actor,
        payload=row.payload,
        previous_hash=row.previous_hash,
        created_at=row.created_at,
    )
    await session.execute(
        update(AuditEventRow)
        .where(AuditEventRow.event_id == row.event_id)
        .values(event_type=future_type, event_hash=rehashed)
        .execution_options(synchronize_session=False)
    )
    session.expunge_all()

    result = await replay_mission(session, mission.id)
    # The chain itself broke at the NEXT event, whose previous_hash still commits
    # to the original — so this history is not merely unknown, it is altered.
    # Either refusal is correct; what must never happen is a trusted projection.
    assert result.trusted is False
    assert result.state is None


async def test_unknown_event_type_on_an_intact_chain_is_refused(session):
    """The same policy, isolated from any chain damage.

    The reducer is handed events directly, so the verifier is not involved and
    the ONLY reason to refuse is the unrecognized type.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    events = await list_events(session, mission.id)
    events[1].event_type = "MERCHANT_ATTESTATION_VERIFIED"

    with pytest.raises(ReplayRefused) as refusal:
        reduce_events(mission.id, events)
    assert refusal.value.reason_code is ReplayReasonCode.REPLAY_UNSUPPORTED_EVENT_TYPE
    assert refusal.value.sequence == 1
    assert refusal.value.event_type == "MERCHANT_ATTESTATION_VERIFIED"


async def test_unparseable_payment_state_is_refused_as_malformed(session):
    """A known event type whose payload names a state this build has no meaning
    for. Guessing would be worse than refusing: the projection would report a
    payment position that never existed."""
    mission = await _mission(session)
    await _small_chain(session, mission)
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.PAYMENT_QUEUED,
        actor="payment-executor",
        payload={"payment_intent_id": str(uuid.uuid4()), "state": "HALF_SETTLED"},
    )
    events = await list_events(session, mission.id)

    with pytest.raises(ReplayRefused) as refusal:
        reduce_events(mission.id, events)
    assert refusal.value.reason_code is ReplayReasonCode.REPLAY_MALFORMED_EVENT
    assert refusal.value.sequence == 3


async def test_replay_reports_a_refusal_without_a_projection(session):
    """A refusal must not hand back a partial state object.

    A caller that receives `state` will use it; a flag beside it does not stop
    that. So the refusal path returns no state at all.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.PAYMENT_QUEUED,
        actor="payment-executor",
        payload={"state": "HALF_SETTLED"},
    )
    result = await replay_mission(session, mission.id)
    assert result.audit_valid is True
    assert result.trusted is False
    assert result.reason_code is ReplayReasonCode.REPLAY_MALFORMED_EVENT
    assert result.state is None
    assert result.comparison is None
    assert result.unsupported_events == [{"sequence": 3, "event_type": "PAYMENT_QUEUED"}]


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
async def test_replay_is_deterministic_over_100_runs(session):
    """Same events in, byte-identical projection out, 100 times.

    Compared as serialized JSON rather than as objects: equality on the model
    could be satisfied by a type that compares equal while serializing
    differently, and the serialized form is what an API caller actually sees.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.OFFERS_RECEIVED,
        actor="orchestrator",
        payload={"raw_offer_count": 4},
    )
    events = await list_events(session, mission.id)

    first = reduce_events(mission.id, events).model_dump_json()
    results = {reduce_events(mission.id, events).model_dump_json() for _ in range(100)}
    assert results == {first}


async def test_replay_is_independent_of_event_order_at_the_boundary(session):
    """Retrieval order cannot change the reconstruction: the reducer sorts by
    sequence, which is the ordering the hash chain itself commits to."""
    mission = await _mission(session)
    await _small_chain(session, mission)
    events = await list_events(session, mission.id)

    forward = reduce_events(mission.id, events)
    backward = reduce_events(mission.id, list(reversed(events)))
    assert forward == backward


async def test_reducer_reads_no_clock_and_generates_no_identifiers(session):
    """Every value in the projection traces to an event or to a default.

    Proven by construction: two reductions separated in wall-clock time and run
    over the same events must be identical, and no field may hold a value that
    is not in the events.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    events = await list_events(session, mission.id)

    projection = reduce_events(mission.id, events)
    assert projection == reduce_events(mission.id, events)
    assert projection.mission_id == mission.id
    assert projection.raw_query == "earbuds"
    assert projection.quantity == 1
    assert projection.soft_budget == 4000
    assert projection.hard_limit == 4500
    assert projection.mission_state == MissionState.DISCOVERING.value
    assert projection.events_replayed == 3
    # Nothing was invented for fields the events never mentioned.
    assert projection.policy_decision is None
    assert projection.selected_offer_id is None
    assert projection.authorization.authorization_id is None
    assert projection.payment.payment_intent_id is None


async def test_empty_event_stream_projects_an_empty_mission(session):
    mission = await _mission(session)
    projection = reduce_events(mission.id, [])
    assert projection == MissionProjection(mission_id=mission.id)
    assert projection.events_replayed == 0
    assert projection.mission_state is None


async def test_pre_c1_payment_transition_without_reason_key_preserves_prior_value(session):
    """Historical payloads omitted null instead of recording an explicit clear."""
    mission = await _mission(session)
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.PAYMENT_FAILED,
        actor="payment-executor",
        payload={
            "payment_intent_id": str(uuid.uuid4()),
            "state": "FAILED_RETRYABLE",
            "reason_code": "PROVIDER_TRANSIENT_FAILURE",
        },
    )
    await append_event(
        session,
        mission_id=mission.id,
        event_type=EventType.PAYMENT_SUCCEEDED,
        actor="payment-executor",
        payload={"state": "SUCCEEDED"},
    )

    projection = reduce_events(mission.id, await list_events(session, mission.id))

    assert projection.payment.state == "SUCCEEDED"
    assert projection.payment.last_reason_code == "PROVIDER_TRANSIENT_FAILURE"


# --------------------------------------------------------------------------- #
# The integrity gate
# --------------------------------------------------------------------------- #
async def test_corrupt_chain_is_rejected_before_any_replay(session):
    """A tampered chain yields no projection at all.

    This is the ordering that matters: verification runs first, and the reducer
    is never reached. A reconstruction built on evidence already known to be
    altered would be a confident-looking lie.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    await session.execute(
        update(AuditEventRow)
        .where(AuditEventRow.mission_id == mission.id, AuditEventRow.sequence == 1)
        .values(payload={"forged": True})
        .execution_options(synchronize_session=False)
    )
    session.expunge_all()

    result = await replay_mission(session, mission.id)
    assert result.audit_valid is False
    assert result.trusted is False
    assert result.reason_code is ReplayReasonCode.REPLAY_AUDIT_INVALID
    assert result.state is None
    assert result.comparison is None
    assert result.events_replayed == 0
    assert result.verification.reason_code is AuditReasonCode.AUDIT_EVENT_HASH_MISMATCH
    assert result.verification.first_invalid_sequence == 1


async def test_valid_chain_replays_and_is_marked_trusted(session):
    mission = await _mission(session)
    await _small_chain(session, mission)
    result = await replay_mission(session, mission.id)
    assert result.audit_valid is True
    assert result.trusted is True
    assert result.reason_code is ReplayReasonCode.REPLAY_OK
    assert result.events_replayed == 3
    assert result.state is not None
    assert result.verification.valid is True


# --------------------------------------------------------------------------- #
# Persisted-state comparison — reported, never repaired
# --------------------------------------------------------------------------- #
async def test_comparison_reports_a_match(session):
    mission = await _mission(session)
    await _small_chain(session, mission)
    mission.state = MissionState.DISCOVERING.value
    await session.flush()

    result = await replay_mission(session, mission.id)
    assert result.comparison is not None
    assert result.comparison.replay_state == MissionState.DISCOVERING.value
    assert result.comparison.persisted_state == MissionState.DISCOVERING.value
    assert result.comparison.matches is True


async def test_comparison_reports_a_mismatch_and_repairs_nothing(session):
    """Drift is surfaced, not corrected.

    The mission row is deliberately moved somewhere the events do not describe.
    Replay must SAY they disagree and leave the row exactly where it was — the
    row is what the kernel enforces against, and letting a projection rewrite it
    would invert that.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    mission.state = MissionState.COMPLETED.value
    await session.flush()

    result = await replay_mission(session, mission.id)
    assert result.comparison is not None
    assert result.comparison.replay_state == MissionState.DISCOVERING.value
    assert result.comparison.persisted_state == MissionState.COMPLETED.value
    assert result.comparison.matches is False

    await session.flush()
    unchanged = await session.get(Mission, mission.id)
    assert unchanged is not None
    assert unchanged.state == MissionState.COMPLETED.value
    # And no event was appended to explain or record the mismatch.
    assert len(await list_events(session, mission.id)) == 3


async def test_comparison_is_none_when_neither_side_has_a_payment(session):
    """Nothing to compare is reported as None, not as agreement.

    Claiming a match about a payment that does not exist on either side would
    be an assertion with no content behind it.
    """
    mission = await _mission(session)
    await _small_chain(session, mission)
    result = await replay_mission(session, mission.id)
    assert result.comparison is not None
    assert result.comparison.payment_matches is None
    assert result.comparison.authorization_matches is None
