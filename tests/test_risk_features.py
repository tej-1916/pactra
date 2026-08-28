"""Feature extraction: declared provenance, real sources, absent-is-not-zero."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from packages.schemas.domain import (
    CreateMissionRequest,
    EventType,
    MissionConstraints,
    ReasonCode,
)
from packages.schemas.merchant import MerchantRecord
from packages.schemas.provenance import TrustLevel
from services.agent_orchestrator.merchants.mock_merchants import (
    MockMerchantA,
    MockMerchantB,
    SpoofingMerchant,
)
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import append_event
from services.risk_engine.config import DEFAULT_RISK_CONFIG
from services.risk_engine.features import (
    FEATURE_SPECS,
    MissionNotFound,
    extract_features,
    extract_merchant_history_features,
    load_mission_facts,
)
from services.risk_engine.models import FeatureSource, FeatureUnavailableReason
from services.security_kernel.merchant_registry import MerchantRegistry
from tests.conftest import make_mission

pytestmark = pytest.mark.asyncio

CONFIG = DEFAULT_RISK_CONFIG
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _constraints(**overrides) -> MissionConstraints:
    base = dict(
        category="wireless_earbuds",
        soft_budget_inr=4000,
        hard_limit_inr=4500,
        min_rating=4.2,
        currency="INR",
    )
    base.update(overrides)
    return MissionConstraints(**base)


async def _mission(session, merchants=None, registry=None, **overrides):
    mission = await Orchestrator(merchants=merchants or [MockMerchantA()], registry=registry).run(
        session, CreateMissionRequest(quantity=1, constraints=_constraints(**overrides))
    )
    await session.commit()
    return mission.id


async def _facts_and_features(session, mission_id, registry=None):
    facts = await load_mission_facts(session, mission_id, config=CONFIG, registry=registry)
    features = extract_features(facts, config=CONFIG, now=NOW)
    features.update(await extract_merchant_history_features(session, facts))
    return facts, features


# --------------------------------------------------------------------------- #
# The provenance table is complete and honest
# --------------------------------------------------------------------------- #
async def test_every_extracted_feature_has_a_declared_source(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    for name in features:
        assert name in FEATURE_SPECS, f"{name} was extracted with no declared source"


async def test_no_feature_is_sourced_from_a_merchant_payload():
    """heuristic-v1 reads nothing merchant-controlled. Checked over the table."""
    offenders = [
        name
        for name, spec in FEATURE_SPECS.items()
        if spec.source is FeatureSource.MERCHANT_PAYLOAD
    ]
    assert offenders == [], offenders


async def test_every_declared_source_has_a_non_empty_detail():
    for name, spec in FEATURE_SPECS.items():
        assert spec.detail.strip(), f"{name} has no documented source detail"


async def test_no_extracted_feature_is_marked_untrusted_trust_level(session):
    """Every value is a server-written record; taint is carried by the
    ``derived_from_untrusted_evidence`` flag, not by pretending the row is
    untrusted."""
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    for feature in features.values():
        assert feature.trust is not TrustLevel.UNTRUSTED


async def test_security_derived_counts_preserve_untrusted_provenance(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    for name in (
        "merchant_identity_mismatch_events",
        "authorization_replay_attempts",
        "mission_authority_escalation_attempts",
    ):
        assert features[name].derived_from_untrusted_evidence is True


# --------------------------------------------------------------------------- #
# Merchant trust comes from the registry
# --------------------------------------------------------------------------- #
async def test_merchant_trust_is_read_from_the_registry(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    assert features["merchant_trust"].value == pytest.approx(0.9)
    assert features["merchant_trust"].source is FeatureSource.MERCHANT_REGISTRY


async def test_a_custom_registry_changes_trust_and_the_payload_cannot(session):
    """The registry is the only lever. A merchant has no field to pull."""
    registry = MerchantRegistry(
        {
            "merchant_a": MerchantRecord(
                merchant_id="merchant_a", display_name="Aurora", trust_score=0.2
            )
        }
    )
    mission_id = await _mission(session, registry=registry)
    _, features = await _facts_and_features(session, mission_id, registry=registry)
    assert features["merchant_trust"].value == pytest.approx(0.2)


async def test_an_unregistered_merchant_is_reported_unknown(session):
    registry = MerchantRegistry({})
    mission_id = await _mission(session, registry=registry)
    _, features = await _facts_and_features(session, mission_id, registry=registry)
    assert features["merchant_known"].value is False
    assert features["merchant_trust"].value == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Absent is not zero
# --------------------------------------------------------------------------- #
async def test_a_mission_with_no_payment_reports_attempts_unavailable(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    attempts = features["payment_attempts"]
    assert attempts.available is False
    assert attempts.value is None
    assert attempts.unavailable_reason is FeatureUnavailableReason.NO_PAYMENT_INTENT


async def test_a_merchant_with_no_payment_history_reports_ratio_unavailable(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    ratio = features["merchant_failed_payment_ratio"]
    assert ratio.available is False
    assert ratio.unavailable_reason is FeatureUnavailableReason.INSUFFICIENT_HISTORY


async def test_a_cold_start_merchant_reports_no_amount_anomaly(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    anomaly = features["amount_vs_merchant_median_ratio"]
    assert anomaly.available is False
    assert anomaly.value is None
    assert features["merchant_amount_observations"].value == 0


async def test_a_denied_mission_reports_no_authorization_features(session):
    # 4299 against a 3000 ceiling is HARD_LIMIT_EXCEEDED: DENY, no authorization.
    mission_id = await _mission(session, soft_budget_inr=2000, hard_limit_inr=3000)
    facts, features = await _facts_and_features(session, mission_id)
    assert facts.authorization is None
    assert features["authorization_lifetime_used_ratio"].available is False
    assert (
        features["authorization_lifetime_used_ratio"].unavailable_reason
        is FeatureUnavailableReason.NO_AUTHORIZATION
    )


# --------------------------------------------------------------------------- #
# Audit-derived counts read real events
# --------------------------------------------------------------------------- #
async def test_authority_escalation_attempts_are_counted_from_the_ledger(session):
    """MockMerchantB ships a claim against the user's hard limit."""
    mission_id = await _mission(session, merchants=[MockMerchantB()])
    _, features = await _facts_and_features(session, mission_id)
    assert features["mission_authority_escalation_attempts"].value >= 1


async def test_a_clean_mission_counts_zero_escalations(session):
    mission_id = await _mission(session, merchants=[MockMerchantA()])
    _, features = await _facts_and_features(session, mission_id)
    assert features["mission_authority_escalation_attempts"].value == 0


async def test_identity_mismatch_is_attributed_to_the_authenticated_merchant(session):
    """Blaming the impersonated merchant would blame the victim."""
    registry = MerchantRegistry(
        {
            mid: MerchantRecord(merchant_id=mid, display_name=mid, trust_score=0.9)
            for mid in ("merchant_a", "evil")
        }
    )
    mission_id = await _mission(
        session,
        merchants=[SpoofingMerchant(claimed_merchant_id="merchant_a"), MockMerchantA()],
        registry=registry,
        min_rating=3.5,
    )
    facts, features = await _facts_and_features(session, mission_id, registry=registry)
    # The mission transacts with merchant_a; the violation names "evil".
    assert facts.merchant_id == "merchant_a"
    assert features["merchant_identity_mismatch_events"].value == 0


async def test_provider_response_mismatch_is_read_from_the_payload_reason_code(session):
    """PROVIDER_RESPONSE_MISMATCH is not its own event type; it is a reason code
    inside PAYMENT_PROVIDER_UNCERTAIN, so the feature has to read payloads."""
    mission_id = await _mission(session)
    await append_event(
        session,
        mission_id=mission_id,
        event_type=EventType.PAYMENT_PROVIDER_UNCERTAIN,
        actor="payment-executor",
        payload={"reason_code": ReasonCode.PROVIDER_RESPONSE_MISMATCH.value},
    )
    await session.commit()
    _, features = await _facts_and_features(session, mission_id)
    assert features["provider_response_mismatch_events"].value == 1


async def test_audit_chain_validity_is_measured_not_assumed(session):
    mission_id = await _mission(session)
    _, features = await _facts_and_features(session, mission_id)
    assert features["audit_chain_valid"].value is True


# --------------------------------------------------------------------------- #
# Time is a parameter, not a clock read
# --------------------------------------------------------------------------- #
async def test_authorization_age_is_computed_from_the_supplied_instant(session):
    mission_id = await _mission(session)
    facts = await load_mission_facts(session, mission_id, config=CONFIG)
    assert facts.authorization is not None
    issued = facts.authorization.issued_at
    expires = facts.authorization.expires_at
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
        expires = expires.replace(tzinfo=timezone.utc)
    midpoint = issued + (expires - issued) / 2

    features = extract_features(facts, config=CONFIG, now=midpoint)
    assert features["authorization_lifetime_used_ratio"].value == pytest.approx(0.5, abs=1e-6)

    later = extract_features(facts, config=CONFIG, now=issued + timedelta(seconds=1))
    assert later["authorization_lifetime_used_ratio"].value < 0.5


async def test_extraction_without_an_instant_reports_age_unavailable(session):
    """No clock is read; no instant means no age, never a fabricated one."""
    mission_id = await _mission(session)
    facts = await load_mission_facts(session, mission_id, config=CONFIG)
    features = extract_features(facts, config=CONFIG, now=None)
    assert features["authorization_age_seconds"].available is False


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #
async def test_an_unknown_mission_raises_rather_than_scoring_zero(session):
    """A LOW score for a mission that does not exist is the wrong default."""
    with pytest.raises(MissionNotFound):
        await load_mission_facts(session, uuid.uuid4(), config=CONFIG)


async def test_a_mission_with_no_offers_reports_no_selected_merchant(session):
    mission = await make_mission(session)
    await session.commit()
    facts, features = await _facts_and_features(session, mission.id)
    assert facts.merchant_id is None
    assert features["merchant_trust"].available is False
    assert (
        features["merchant_identity_mismatch_events"].unavailable_reason
        is FeatureUnavailableReason.NO_SELECTED_MERCHANT
    )


async def test_extraction_writes_nothing(session, sessionmaker):
    """A read path that dirties a session commits on somebody else's behalf."""
    mission_id = await _mission(session)
    facts = await load_mission_facts(session, mission_id, config=CONFIG)
    extract_features(facts, config=CONFIG, now=NOW)
    await extract_merchant_history_features(session, facts)
    assert list(session.new) == []
    assert list(session.dirty) == []
    assert list(session.deleted) == []


# --------------------------------------------------------------------------- #
# Untrusted-evidence provenance, traced end to end
# --------------------------------------------------------------------------- #
async def test_untrusted_provenance_survives_the_whole_chain(session):
    """merchant payload -> kernel refusal -> trusted event -> feature -> factor
    -> explanation, with the untrusted ORIGIN intact at every hop.

    The temptation this guards against is subtle and one-directional: the record
    the kernel writes is trustworthy, so it is easy to treat the behaviour it
    DESCRIBES as trustworthy too. Laundering the provenance that way would undo
    at the risk layer exactly what Phases 2-3 spend their effort preserving
    everywhere else.
    """
    from services.risk_engine.engine import assess_mission

    # 1. Untrusted input: MockMerchantB claims hard_limit_inr = 100000.
    mission_id = await _mission(session, merchants=[MockMerchantB()])

    # 2. The kernel refused it and wrote a SECURITY_VIOLATION about it.
    events = await load_mission_facts(session, mission_id, config=CONFIG)
    violations = [
        event
        for event in events.events
        if event.event_type == EventType.SECURITY_VIOLATION.value
        and (event.payload or {}).get("reason_code") == ReasonCode.AUTHORITY_ESCALATION.value
    ]
    assert violations, "the fixture did not produce an authority-escalation violation"
    assert violations[0].actor == "security-kernel", "the record must be kernel-written"

    # 3. The feature derived from it counts the violation...
    assessment = await assess_mission(session, mission_id, now=NOW)
    feature = assessment.feature_values["mission_authority_escalation_attempts"]
    assert feature.value >= 1
    # ...and is itself sourced from the trusted ledger...
    assert feature.source is FeatureSource.AUDIT_LEDGER
    assert feature.trust is TrustLevel.TRUSTED
    # ...while still declaring that what it describes was untrusted.
    assert feature.derived_from_untrusted_evidence is True

    # 4. The factor built from it carries the flag forward.
    factor = next(
        f for f in assessment.factors if f.code == "MISSION_AUTHORITY_ESCALATION_ATTEMPTS"
    )
    assert factor.derived_from_untrusted_evidence is True

    # 5. And the explanation says so in words a reader will see.
    joined = "\n".join(assessment.explanation)
    assert "the record is trusted, the behaviour it describes was not" in joined


async def test_every_security_derived_feature_is_flagged_and_no_other_is(session):
    """The exact set of eight, asserted as a set rather than sampled.

    Pinning the whole set both ways means a new security-derived feature that
    forgets the flag fails here, and so does a registry/policy feature that
    acquires it by copy-paste.
    """
    expected = {
        "merchant_identity_mismatch_events",
        "merchant_authority_escalation_events",
        "authorization_replay_attempts",
        "transaction_binding_failures",
        "mission_authority_escalation_attempts",
        "provider_response_mismatch_events",
        "idempotency_conflict_events",
        "webhook_anomaly_events",
    }
    actual = {name for name, spec in FEATURE_SPECS.items() if spec.derived_from_untrusted_evidence}
    assert actual == expected


async def test_no_feature_can_be_caller_controlled(session):
    """Every declared source is a server-written row or a server-owned table.

    ``CAN_BE_CALLER_CONTROLLED`` must be NO for all of them: a caller reaches the
    risk engine only through two endpoints that declare no body and no query
    parameter, and every source below is written by the kernel, not by a request.
    """
    caller_reachable = {FeatureSource.MERCHANT_PAYLOAD}
    for name, spec in FEATURE_SPECS.items():
        assert spec.source not in caller_reachable, name
