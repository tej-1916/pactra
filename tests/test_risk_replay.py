"""A RISK_ASSESSED event must be inert in the deterministic replay.

The reducer's handler table is exhaustive by contract, so an advisory event
cannot be silently dropped from a reconstruction. This file proves the other
half: accounting for it must not let it MOVE anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from apps.api.db.models import AuditEventRow
from packages.schemas.domain import CreateMissionRequest, EventType, MissionConstraints
from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from services.audit_ledger.replay import HANDLERS, SECURITY_EVENT_TYPES, reduce_events
from services.audit_ledger.verify import verify_mission_chain
from services.risk_engine.engine import assess_mission, record_assessment

# No module-level asyncio mark: two tests here are pure, and
# `asyncio_mode = "auto"` already collects the async ones.
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


async def _mission(session) -> uuid.UUID:
    mission = await Orchestrator(merchants=[MockMerchantA()]).run(
        session,
        CreateMissionRequest(
            quantity=1,
            constraints=MissionConstraints(
                category="wireless_earbuds",
                soft_budget_inr=4000,
                hard_limit_inr=4500,
                min_rating=4.2,
                currency="INR",
            ),
        ),
    )
    await session.commit()
    return mission.id


def test_the_handler_table_is_still_exhaustive():
    """The contract that stops a new event type distorting a projection."""
    assert set(HANDLERS) == set(EventType)


def test_risk_assessed_is_not_a_security_event():
    """A risk assessment is an opinion. The security history is a list of
    refusals, and putting an opinion in it would blur the difference."""
    assert EventType.RISK_ASSESSED not in SECURITY_EVENT_TYPES


async def test_recording_an_assessment_changes_nothing_else_in_the_projection(session):
    """The core inertness proof: replay with and without, compared field by field."""
    mission_id = await _mission(session)
    before_events = await list_events(session, mission_id)
    before = reduce_events(mission_id, before_events)

    assessment = await assess_mission(session, mission_id, now=NOW)
    await record_assessment(session, assessment)
    await session.commit()

    after = reduce_events(mission_id, await list_events(session, mission_id))

    left = before.model_dump(mode="json")
    right = after.model_dump(mode="json")
    # The two fields the extra event is ALLOWED to change.
    assert right.pop("risk_assessments"), "the advisory record was dropped entirely"
    left.pop("risk_assessments")
    assert right.pop("events_replayed") == left.pop("events_replayed") + 1
    assert left == right


async def test_the_projection_reconstructs_the_advisory_verdict(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    await record_assessment(session, assessment)
    await session.commit()

    projection = reduce_events(mission_id, await list_events(session, mission_id))
    assert len(projection.risk_assessments) == 1
    replayed = projection.risk_assessments[0]
    assert replayed.band == assessment.band.value
    assert replayed.recommendation == assessment.recommendation.value
    assert replayed.score == pytest.approx(assessment.score, abs=1e-6)
    assert replayed.factor_codes == [f.code for f in assessment.factors]


async def test_the_projection_carries_no_feature_values(session):
    """The advisory record is a verdict, not a copy of the mission's contents."""
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    await record_assessment(session, assessment)
    await session.commit()

    projection = reduce_events(mission_id, await list_events(session, mission_id))
    blob = projection.risk_assessments[0].model_dump_json()
    assert "amount" not in blob
    assert "merchant" not in blob
    assert "weight" not in blob


async def test_a_malformed_advisory_payload_does_not_refuse_the_whole_replay(session):
    """Deliberate asymmetry with every enforcement reducer.

    A malformed SECURITY_VIOLATION means the security history cannot be
    reconstructed, and refusing is the only honest answer. An unreadable
    advisory note costs the projection nothing it was relying on — and refusing
    the replay for it would hand the advisory layer the power to break a
    reconstruction, which is exactly the authority it must not have.
    """
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    row = await record_assessment(session, assessment)
    await session.commit()

    events = await list_events(session, mission_id)
    for event in events:
        if event.event_id == row.event_id:
            event.payload = {"score": "not-a-number", "factor_codes": "not-a-list"}

    projection = reduce_events(mission_id, events)
    replayed = projection.risk_assessments[0]
    assert replayed.score is None
    assert replayed.factor_codes == []
    # And the rest of the mission still reconstructed.
    assert projection.policy_decision == "REQUIRE_APPROVAL"


async def test_many_assessments_do_not_disturb_the_reconstruction(session):
    mission_id = await _mission(session)
    baseline = reduce_events(mission_id, await list_events(session, mission_id))

    for _ in range(5):
        assessment = await assess_mission(session, mission_id, now=NOW)
        await record_assessment(session, assessment)
    await session.commit()

    projection = reduce_events(mission_id, await list_events(session, mission_id))
    assert len(projection.risk_assessments) == 5
    assert projection.mission_state == baseline.mission_state
    assert projection.authorization == baseline.authorization
    assert projection.payment == baseline.payment
    assert projection.security_events == baseline.security_events


async def test_the_chain_still_verifies_with_advisory_events_in_it(session):
    mission_id = await _mission(session)
    for _ in range(3):
        assessment = await assess_mission(session, mission_id, now=NOW)
        await record_assessment(session, assessment)
    await session.commit()

    result = await verify_mission_chain(session, mission_id)
    assert result.valid is True
    assert result.events_checked == len(await list_events(session, mission_id))


async def test_a_tampered_advisory_event_is_still_detected(session):
    """Inert in the reducer does not mean exempt from the hash chain."""
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    row = await record_assessment(session, assessment)
    await session.commit()

    stored = await session.get(AuditEventRow, row.event_id)
    stored.payload = {**stored.payload, "score": 0.0, "band": "LOW"}
    await session.commit()

    result = await verify_mission_chain(session, mission_id)
    assert result.valid is False
    assert result.reason_code.value == "AUDIT_EVENT_HASH_MISMATCH"
