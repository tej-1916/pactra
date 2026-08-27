import pytest
from apps.api.db.models import Offer
from packages.schemas.domain import CreateMissionRequest, EventType, MissionState
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from sqlalchemy import select
from tests.conftest import make_constraints

pytestmark = pytest.mark.asyncio


async def test_full_slice_require_approval_path(session):
    req = CreateMissionRequest(
        raw_query="Find earbuds under 4000, min rating 4.2",
        quantity=1,
        constraints=make_constraints(),
    )
    mission = await Orchestrator().run(session, req)
    assert mission.state == MissionState.AWAITING_APPROVAL.value

    events = await list_events(session, mission.id)
    # Every transition produced an event, sequence contiguous from 0.
    assert [e.sequence for e in events] == list(range(len(events)))
    types = [e.event_type for e in events]
    assert types[0] == EventType.MISSION_CREATED.value
    assert EventType.POLICY_DECISION.value in types
    assert EventType.APPROVAL_REQUESTED.value in types
    # Hash chain integrity across the whole mission
    prev = "0" * 64
    for e in events:
        assert e.previous_hash == prev
        prev = e.event_hash


async def test_deny_path_cancels_mission(session):
    req = CreateMissionRequest(
        quantity=1,
        constraints=make_constraints(min_rating=5.0),  # no valid offers
    )
    mission = await Orchestrator().run(session, req)
    assert mission.state == MissionState.CANCELLED.value
    events = await list_events(session, mission.id)
    assert EventType.MISSION_DENIED.value in [e.event_type for e in events]


async def test_allow_path_reaches_authorized(session):
    """Phase 3 supersedes the Phase 2 behaviour here.

    Under Phase 2 an ALLOW decision left the mission parked at POLICY_CHECKED
    because no authorization existed yet. Phase 3 implements the authorization
    artifact, so an ALLOW — policy requiring no human approval — now binds the
    transaction, mints the artifact, activates it, and reaches AUTHORIZED. No
    Phase 2 security invariant is relaxed by this: the change is the arrival of
    the missing step, not the removal of a check.
    """
    req = CreateMissionRequest(
        quantity=1,
        constraints=make_constraints(soft_budget_inr=5000, hard_limit_inr=6000),
    )
    mission = await Orchestrator().run(session, req)
    assert mission.state == MissionState.AUTHORIZED.value

    events = await list_events(session, mission.id)
    types = [e.event_type for e in events]
    assert EventType.AUTHORIZATION_CREATED.value in types
    assert EventType.AUTHORIZATION_ACTIVATED.value in types
    # The hash chain still covers the new authorization events.
    assert [e.sequence for e in events] == list(range(len(events)))


async def test_offers_persisted_with_ranks(session):
    req = CreateMissionRequest(quantity=1, constraints=make_constraints())
    mission = await Orchestrator().run(session, req)
    offers = (
        (await session.execute(select(Offer).where(Offer.mission_id == mission.id))).scalars().all()
    )
    assert len(offers) == 4  # 2 merchants x 2 products
    valid = [o for o in offers if o.valid]
    assert all(o.rank is not None for o in valid)
    # invalid (low-rating) offers get no rank
    assert all(o.rank is None for o in offers if not o.valid)
