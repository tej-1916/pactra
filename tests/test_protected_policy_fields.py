"""#9 Protected policy register beyond budgets.

Every security-sensitive user-policy field is held at USER_POLICY authority. A
merchant (MERCHANT_DATA) that claims any of them is escalating, so the claim is
refused and the authoritative value survives untouched.
"""

import pytest
from packages.schemas.domain import CreateMissionRequest, EventType, RawMerchantOffer
from packages.schemas.invariants import InvariantViolation
from packages.schemas.provenance import AuthorityLevel, untrusted
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from services.security_kernel.authority import AuthorityEscalation
from services.security_kernel.ingress import PROTECTED_POLICY_FIELDS, protected_policy_values
from services.security_kernel.policy_register import ProtectedPolicyRegister
from tests.conftest import make_constraints

EXPECTED_PROTECTED = {
    "soft_budget_inr",
    "hard_limit_inr",
    "currency",
    "min_rating",
    "allowed_merchants",
    "blocked_merchants",
    "min_merchant_trust",
}

# What a merchant would claim for each protected field to widen its own ground.
MERCHANT_CLAIMS = {
    "soft_budget_inr": 999999,
    "hard_limit_inr": 999999,
    "currency": "USD",
    "min_rating": 0.0,
    "allowed_merchants": ["evil"],
    "blocked_merchants": [],
    "min_merchant_trust": 0.0,
}


class ClaimingMerchant:
    """Adversarial merchant that claims every protected policy field at once."""

    merchant_id = "merchant_b"

    def quote(self, constraints, quantity):
        return [
            RawMerchantOffer(
                merchant_id=self.merchant_id,
                product_id="claim-01",
                title="Claiming Buds",
                price=1000,
                currency="INR",
                rating=4.5,
                in_stock=True,
                claims=dict(MERCHANT_CLAIMS),
            )
        ]


def test_protected_set_covers_all_security_sensitive_policy_fields():
    assert set(PROTECTED_POLICY_FIELDS) == EXPECTED_PROTECTED
    values = protected_policy_values(make_constraints())
    assert set(values) == EXPECTED_PROTECTED
    for field, bound in values.items():
        assert bound.authority == AuthorityLevel.USER_POLICY
        assert bound.tainted is False
        assert bound.source == f"user-policy:{field}"


@pytest.mark.parametrize("field", sorted(EXPECTED_PROTECTED))
def test_merchant_cannot_write_any_protected_field(field):
    c = make_constraints(
        allowed_merchants=["merchant_a"],
        blocked_merchants=["evil"],
        min_merchant_trust=0.5,
    )
    register = ProtectedPolicyRegister(protected_policy_values(c))
    original = register.get(field).value

    with pytest.raises(AuthorityEscalation) as exc:
        register.apply(field, untrusted(MERCHANT_CLAIMS[field], source="merchant:merchant_b"))

    assert exc.value.reason_code == "AUTHORITY_ESCALATION"
    assert exc.value.source == AuthorityLevel.MERCHANT_DATA
    assert exc.value.target == AuthorityLevel.USER_POLICY
    # The authoritative value is untouched.
    assert register.get(field).value == original


def test_unprotected_field_lookup_raises_invariant_error_not_keyerror():
    register = ProtectedPolicyRegister(protected_policy_values(make_constraints()))
    assert register.is_protected("payment_destination") is False
    with pytest.raises(InvariantViolation) as exc:
        register.get("payment_destination")
    assert exc.value.reason_code == "INVARIANT_VIOLATION"


@pytest.mark.asyncio
async def test_all_protected_claims_blocked_on_the_runtime_path(session):
    c = make_constraints(
        soft_budget_inr=4000,
        hard_limit_inr=4500,
        min_rating=4.2,
        allowed_merchants=["merchant_a", "merchant_b"],
        blocked_merchants=["evil"],
        min_merchant_trust=0.5,
    )
    req = CreateMissionRequest(quantity=1, constraints=c)
    mission = await Orchestrator(merchants=[ClaimingMerchant()]).run(session, req)

    events = await list_events(session, mission.id)
    violations = [e for e in events if e.event_type == EventType.SECURITY_VIOLATION.value]
    escalations = [e for e in violations if e.payload["reason_code"] == "AUTHORITY_ESCALATION"]

    # One blocked escalation per protected field.
    assert {e.payload["field"] for e in escalations} == EXPECTED_PROTECTED
    for e in escalations:
        assert e.payload["source_authority"] == "MERCHANT_DATA"
        assert e.payload["target_authority"] == "USER_POLICY"
        assert e.payload["attempted_value"] == MERCHANT_CLAIMS[e.payload["field"]]
        assert e.payload["merchant_id"] == "merchant_b"

    # Audit chain stays contiguous through all of them.
    assert [e.sequence for e in events] == list(range(len(events)))


@pytest.mark.asyncio
async def test_claimed_policy_never_reaches_the_decision(session):
    """The merchant claimed a 999999 hard limit and a USD currency; the recorded
    decision still uses the user's real policy."""
    from apps.api.db.models import PolicyDecisionRow
    from sqlalchemy import select

    c = make_constraints(soft_budget_inr=4000, hard_limit_inr=4500)
    mission = await Orchestrator(merchants=[ClaimingMerchant()]).run(
        session, CreateMissionRequest(quantity=1, constraints=c)
    )
    pd = (
        await session.execute(
            select(PolicyDecisionRow).where(PolicyDecisionRow.mission_id == mission.id)
        )
    ).scalar_one()
    assert pd.hard_limit == 4500
    assert pd.soft_budget == 4000
