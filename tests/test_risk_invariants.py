"""RISK SCORE != AUTHORITY. The eight Phase 7 invariants, each proved directly.

    1. risk score -> never authorization
    2. risk score -> never payment authority
    3. risk score -> never policy mutation
    4. LOW risk    -> cannot override DENY
    5. HIGH risk   -> cannot bypass the deterministic flow
    6. untrusted merchant data -> cannot self-assign trust
    7. caller-supplied risk score -> ignored
    8. feature source -> documented, trusted, or marked untrusted

Where an invariant can be proved structurally — a field that does not exist, an
import that cannot happen — it is proved that way, because behaviour can change
and a missing field cannot.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone

import pytest
from apps.api.db.models import (
    AuthorizationRow,
    Mission,
    OutboxEventRow,
    PaymentIntentRow,
    WebhookEventRow,
)
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import Capability, CapabilitySet
from packages.schemas.domain import (
    CreateMissionRequest,
    MissionConstraints,
    MissionState,
    PolicyOutcome,
)
from pydantic import ValidationError
from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
from services.agent_orchestrator.orchestrator import Orchestrator
from services.risk_engine import engine as engine_module
from services.risk_engine.config import DEFAULT_RISK_CONFIG, RiskConfig
from services.risk_engine.engine import assess_mission, record_assessment
from services.risk_engine.features import FEATURE_SPECS
from services.risk_engine.models import FeatureSource, RiskBand
from services.security_kernel.authorization import (
    AuthorizationReplayDetected,
    consume_authorization,
    rebuild_bound_transaction,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

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


async def _mission(session, registry=None, **overrides) -> uuid.UUID:
    mission = await Orchestrator(merchants=[MockMerchantA()], registry=registry).run(
        session, CreateMissionRequest(quantity=1, constraints=_constraints(**overrides))
    )
    await session.commit()
    return mission.id


async def _census(session) -> dict[str, int]:
    tables = {
        "missions": Mission,
        "authorizations": AuthorizationRow,
        "payment_intents": PaymentIntentRow,
        "outbox_events": OutboxEventRow,
        "webhook_events": WebhookEventRow,
    }
    return {
        name: int((await session.execute(select(func.count()).select_from(model))).scalar_one())
        for name, model in tables.items()
    }


# --------------------------------------------------------------------------- #
# 1. RISK SCORE -> NEVER AUTHORIZATION
# --------------------------------------------------------------------------- #
async def test_assessment_never_issues_an_authorization(session):
    mission = Mission(id=uuid.uuid4(), quantity=1, state="CREATED")
    session.add(mission)
    await session.commit()

    before = await _census(session)
    await assess_mission(session, mission.id, now=NOW)
    await session.commit()
    assert await _census(session) == before


async def test_assessment_never_activates_a_pending_authorization(session):
    mission_id = await _mission(session)
    row = (
        await session.execute(
            select(AuthorizationRow).where(AuthorizationRow.mission_id == mission_id)
        )
    ).scalar_one()
    assert row.status == AuthorizationStatus.PENDING.value

    await assess_mission(session, mission_id, now=NOW)
    await session.commit()

    reloaded = await session.get(AuthorizationRow, row.authorization_id, populate_existing=True)
    assert reloaded.status == AuthorizationStatus.PENDING.value


async def test_assessment_never_consumes_an_authorization(session):
    """The authorization must still be spendable afterwards.

    A stronger check than "status unchanged": it proves the one-time use was not
    quietly spent, by spending it successfully after the assessment.
    """
    mission_id = await _mission(session)
    row = (
        await session.execute(
            select(AuthorizationRow).where(AuthorizationRow.mission_id == mission_id)
        )
    ).scalar_one()
    from services.security_kernel.authorization import activate_authorization

    await activate_authorization(session, authorization_id=row.authorization_id)
    await session.commit()

    for _ in range(3):
        await assess_mission(session, mission_id, now=NOW)
    await session.commit()

    consumed = await consume_authorization(
        session,
        authorization_id=row.authorization_id,
        transaction=rebuild_bound_transaction(row),
    )
    assert consumed.status == AuthorizationStatus.CONSUMED.value


async def test_the_engine_exposes_no_authorization_function():
    """Structural: there is nothing on the module to call."""
    exported = set(dir(engine_module))
    for name in ("issue_authorization", "activate_authorization", "consume_authorization"):
        assert name not in exported


# --------------------------------------------------------------------------- #
# 2. RISK SCORE -> NEVER PAYMENT AUTHORITY
# --------------------------------------------------------------------------- #
async def test_assessment_creates_no_payment_intent_or_outbox_event(session):
    mission_id = await _mission(session)
    before = await _census(session)
    for _ in range(3):
        await assess_mission(session, mission_id, now=NOW)
    await session.commit()
    after = await _census(session)
    assert after["payment_intents"] == before["payment_intents"] == 0
    assert after["outbox_events"] == before["outbox_events"] == 0


async def test_the_engine_holds_no_capability_and_asks_for_none():
    """A risk engine that could present ``payment.execute`` would be reachable
    from the executor's boundary. It cannot, because it has no capability
    parameter at all."""
    signature = inspect.signature(assess_mission)
    assert "capabilities" not in signature.parameters
    assert not any(param.annotation is CapabilitySet for param in signature.parameters.values())


async def test_a_critical_assessment_still_creates_no_payment(session, sessionmaker):
    """The band that would be a DENY in a system that confused risk with policy."""
    from services.risk_engine.config import RiskConfig as _Config

    mission_id = await _mission(session)
    # Force CRITICAL by lowering saturation, not by claiming one: the point is
    # what a CRITICAL assessment CANNOT do, whatever produced it.
    hot = _Config(saturation_points=0.001)
    assessment = await assess_mission(session, mission_id, config=hot, now=NOW)
    assert assessment.band is RiskBand.CRITICAL

    before = await _census(session)
    await session.commit()
    assert await _census(session) == before


# --------------------------------------------------------------------------- #
# 3. RISK SCORE -> NEVER POLICY MUTATION
# --------------------------------------------------------------------------- #
async def test_assessment_leaves_the_policy_decision_untouched(session):
    from apps.api.db.models import PolicyDecisionRow

    mission_id = await _mission(session)
    before = (
        await session.execute(
            select(PolicyDecisionRow).where(PolicyDecisionRow.mission_id == mission_id)
        )
    ).scalar_one()
    snapshot = (
        before.decision,
        list(before.reason_codes),
        before.requested_amount,
        before.soft_budget,
        before.hard_limit,
        before.policy_version,
    )

    await assess_mission(session, mission_id, now=NOW)
    await session.commit()

    after = await session.get(PolicyDecisionRow, before.id, populate_existing=True)
    assert (
        after.decision,
        list(after.reason_codes),
        after.requested_amount,
        after.soft_budget,
        after.hard_limit,
        after.policy_version,
    ) == snapshot


async def test_assessment_leaves_the_user_constraints_untouched(session):
    from apps.api.db.models import MissionConstraintsRow

    mission_id = await _mission(session)
    row = (
        await session.execute(
            select(MissionConstraintsRow).where(MissionConstraintsRow.mission_id == mission_id)
        )
    ).scalar_one()
    snapshot = (
        row.soft_budget_inr,
        row.hard_limit_inr,
        row.min_rating,
        row.currency,
        row.min_merchant_trust,
    )

    await assess_mission(session, mission_id, now=NOW)
    await session.commit()

    reloaded = await session.get(MissionConstraintsRow, row.id, populate_existing=True)
    assert (
        reloaded.soft_budget_inr,
        reloaded.hard_limit_inr,
        reloaded.min_rating,
        reloaded.currency,
        reloaded.min_merchant_trust,
    ) == snapshot


async def test_assessment_does_not_move_the_mission_state(session):
    mission_id = await _mission(session)
    before = (await session.get(Mission, mission_id)).state
    await assess_mission(session, mission_id, now=NOW)
    await session.commit()
    after = (await session.get(Mission, mission_id, populate_existing=True)).state
    assert after == before == MissionState.AWAITING_APPROVAL.value


# --------------------------------------------------------------------------- #
# 4 & 5. Risk cannot override a decision, in either direction
# --------------------------------------------------------------------------- #
async def test_low_risk_cannot_turn_a_deny_into_anything_else(session):
    """A hard-limit violation is DENY regardless of how calm the score is."""
    mission_id = await _mission(session, soft_budget_inr=2000, hard_limit_inr=3000)
    assessment = await assess_mission(session, mission_id, now=NOW)

    assert assessment.policy_decision == PolicyOutcome.DENY.value
    assert assessment.recommendation.value not in {o.value for o in PolicyOutcome}

    mission = await session.get(Mission, mission_id, populate_existing=True)
    assert mission.state == MissionState.CANCELLED.value
    count = (
        await session.execute(
            select(func.count())
            .select_from(AuthorizationRow)
            .where(AuthorizationRow.mission_id == mission_id)
        )
    ).scalar_one()
    assert count == 0, "a DENY must issue no authorization, whatever the risk score says"


async def test_high_risk_does_not_block_a_permitted_transaction(session):
    """The other direction, and the one an advisory layer gets wrong.

    A HIGH assessment must leave an ALLOW mission exactly as it was: still
    AUTHORIZED, still holding an ACTIVE authorization, still spendable.
    """
    mission_id = await _mission(session, soft_budget_inr=4500, hard_limit_inr=4500)
    hot = RiskConfig(saturation_points=0.05)
    assessment = await assess_mission(session, mission_id, config=hot, now=NOW)
    assert assessment.band in (RiskBand.HIGH, RiskBand.CRITICAL)
    assert assessment.policy_decision == PolicyOutcome.ALLOW.value

    await session.commit()
    mission = await session.get(Mission, mission_id, populate_existing=True)
    assert mission.state == MissionState.AUTHORIZED.value

    row = (
        await session.execute(
            select(AuthorizationRow).where(AuthorizationRow.mission_id == mission_id)
        )
    ).scalar_one()
    assert row.status == AuthorizationStatus.ACTIVE.value
    consumed = await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=rebuild_bound_transaction(row)
    )
    assert consumed.status == AuthorizationStatus.CONSUMED.value


async def test_low_risk_does_not_make_a_replay_possible(session):
    """A calm score must not soften replay protection."""
    mission_id = await _mission(session, soft_budget_inr=4500, hard_limit_inr=4500)
    row = (
        await session.execute(
            select(AuthorizationRow).where(AuthorizationRow.mission_id == mission_id)
        )
    ).scalar_one()
    transaction = rebuild_bound_transaction(row)
    await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=transaction
    )
    await session.commit()

    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.band is RiskBand.LOW

    with pytest.raises(AuthorizationReplayDetected):
        await consume_authorization(
            session, authorization_id=row.authorization_id, transaction=transaction
        )


# --------------------------------------------------------------------------- #
# 6. Untrusted merchant data cannot self-assign trust
# --------------------------------------------------------------------------- #
async def test_merchant_trust_is_never_sourced_from_a_payload():
    spec = FEATURE_SPECS["merchant_trust"]
    assert spec.source is FeatureSource.MERCHANT_REGISTRY
    assert spec.source is not FeatureSource.MERCHANT_PAYLOAD


async def test_the_offer_schema_has_no_trust_field_to_forge():
    """Structural, and stronger than any runtime check."""
    from packages.schemas.domain import RawMerchantOffer

    assert "merchant_trust" not in RawMerchantOffer.model_fields
    assert "trust" not in RawMerchantOffer.model_fields


# --------------------------------------------------------------------------- #
# 7. A caller-supplied risk score has nowhere to arrive
# --------------------------------------------------------------------------- #
async def test_assess_mission_has_no_score_parameter():
    parameters = set(inspect.signature(assess_mission).parameters)
    for forbidden in ("score", "band", "recommendation", "risk_score", "weights", "threshold"):
        assert forbidden not in parameters


async def test_record_assessment_accepts_only_a_real_assessment(session):
    """A hand-built dict claiming a score cannot be recorded."""
    mission_id = await _mission(session)
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        await record_assessment(session, {"mission_id": mission_id, "score": 0.0})


async def test_a_forged_capability_cannot_change_the_scoring_rules(session):
    """Weights are module-owned; a capability set is not a lever on them.

    ``assess_mission`` takes no capability, so a caller holding a forged
    ``CapabilitySet`` — even one naming ``policy.modify`` — has nothing to
    present it to, and the config it scores against is unchanged.
    """
    forged = CapabilitySet(
        principal="buyer-agent",
        allow=frozenset({Capability.POLICY_MODIFY, Capability.PAYMENT_EXECUTE}),
    )
    mission_id = await _mission(session)
    baseline = await assess_mission(session, mission_id, now=NOW)

    assert "capabilities" not in inspect.signature(assess_mission).parameters
    with pytest.raises(TypeError):
        await assess_mission(session, mission_id, capabilities=forged, now=NOW)

    after = await assess_mission(session, mission_id, now=NOW)
    assert after.score == baseline.score
    assert DEFAULT_RISK_CONFIG.band_medium_at == RiskConfig().band_medium_at


# --------------------------------------------------------------------------- #
# 8. Every feature source is documented
# --------------------------------------------------------------------------- #
async def test_every_declared_feature_names_a_source_and_an_authority():
    for name, spec in FEATURE_SPECS.items():
        assert spec.source in FeatureSource, name
        assert spec.authority is not None, name
        assert spec.trust is not None, name
        assert len(spec.detail) > 20, f"{name}'s source detail is too thin to audit"


async def test_features_about_untrusted_behaviour_are_marked_as_such():
    """Provenance is preserved, not laundered by the record being ours."""
    must_be_marked = {
        "merchant_identity_mismatch_events",
        "merchant_authority_escalation_events",
        "authorization_replay_attempts",
        "transaction_binding_failures",
        "mission_authority_escalation_attempts",
        "provider_response_mismatch_events",
        "idempotency_conflict_events",
    }
    for name in must_be_marked:
        assert FEATURE_SPECS[name].derived_from_untrusted_evidence is True, name


async def test_registry_and_policy_features_are_not_marked_untrusted():
    for name in ("merchant_trust", "merchant_known", "amount_to_hard_limit_ratio"):
        assert FEATURE_SPECS[name].derived_from_untrusted_evidence is False, name
