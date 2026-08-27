"""#1 Runtime authority enforcement: a merchant claim that tries to raise the
user's hard limit is blocked on the real mission path, not just in a unit test.
MockMerchantB submits claims={'hard_limit_inr': 100000}."""

import pytest
from apps.api.db.models import PolicyDecisionRow
from packages.schemas.domain import CreateMissionRequest, EventType
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from sqlalchemy import select
from tests.conftest import make_constraints

pytestmark = pytest.mark.asyncio


async def test_merchant_budget_claim_blocked_on_runtime_path(session):
    req = CreateMissionRequest(
        quantity=1,
        constraints=make_constraints(soft_budget_inr=4000, hard_limit_inr=4500),
    )
    mission = await Orchestrator().run(session, req)

    # A SECURITY_VIOLATION was recorded with AUTHORITY_ESCALATION.
    events = await list_events(session, mission.id)
    violations = [e for e in events if e.event_type == EventType.SECURITY_VIOLATION.value]
    assert len(violations) == 1
    payload = violations[0].payload
    assert payload["reason_code"] == "AUTHORITY_ESCALATION"
    assert payload["field"] == "hard_limit_inr"
    assert payload["attempted_value"] == 100000
    assert payload["source_authority"] == "MERCHANT_DATA"
    assert payload["target_authority"] == "USER_POLICY"

    # The protected user policy was NOT mutated: the recorded decision still uses
    # the user's hard limit, not the merchant's forged 100000.
    pd = (
        await session.execute(
            select(PolicyDecisionRow).where(PolicyDecisionRow.mission_id == mission.id)
        )
    ).scalar_one()
    assert pd.hard_limit == 4500

    # The violation is part of the tamper-evident chain (contiguous sequence).
    assert [e.sequence for e in events] == list(range(len(events)))
