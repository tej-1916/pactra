"""End-to-end assessment over real missions: determinism, cold start, recording."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from apps.api.db.models import AuditEventRow, Mission
from packages.schemas.capability import security_kernel_capabilities
from packages.schemas.domain import (
    CreateMissionRequest,
    EventType,
    MissionConstraints,
    PolicyOutcome,
)
from packages.schemas.merchant import MerchantRecord
from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA, MockMerchantB
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.verify import verify_mission_chain
from services.risk_engine.config import DEFAULT_RISK_CONFIG, ENGINE_VERSION, HEURISTIC_VERSION
from services.risk_engine.engine import ACTOR, assess_mission, record_assessment
from services.risk_engine.features import MissionNotFound
from services.risk_engine.models import RiskBand, RiskRecommendation
from services.security_kernel.authorization import generate_nonce, issue_authorization
from services.security_kernel.merchant_registry import MerchantRegistry
from sqlalchemy import select
from tests.conftest import approved_transaction

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
KERNEL = security_kernel_capabilities()


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


async def _mission(session, merchants=None, registry=None, **overrides) -> uuid.UUID:
    mission = await Orchestrator(merchants=merchants or [MockMerchantA()], registry=registry).run(
        session, CreateMissionRequest(quantity=1, constraints=_constraints(**overrides))
    )
    await session.commit()
    return mission.id


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
async def test_the_same_mission_at_the_same_instant_scores_identically(session):
    """Invariant #1 of the Phase 7 matrix, checked by equality rather than eye.

    Only ``assessment_id`` differs: it identifies THIS evaluation, not this
    result.
    """
    mission_id = await _mission(session)
    first = await assess_mission(session, mission_id, now=NOW)
    second = await assess_mission(session, mission_id, now=NOW)

    left = first.model_dump(mode="json")
    right = second.model_dump(mode="json")
    assert left.pop("assessment_id") != right.pop("assessment_id")
    assert left == right


async def test_the_score_is_always_within_the_declared_range(session):
    for constraints in ({}, {"soft_budget_inr": 100, "hard_limit_inr": 4400}):
        mission_id = await _mission(session, **constraints)
        assessment = await assess_mission(session, mission_id, now=NOW)
        assert 0.0 <= assessment.score <= 1.0


async def test_the_score_is_reproducible_from_the_published_arithmetic(session):
    """raw_points / saturation_points, clamped. A reader can re-derive it."""
    mission_id = await _mission(session, merchants=[MockMerchantB()])
    assessment = await assess_mission(session, mission_id, now=NOW)
    expected = min(1.0, assessment.raw_points / assessment.saturation_points)
    assert assessment.score == pytest.approx(expected)
    assert sum(f.contribution for f in assessment.factors) == pytest.approx(
        assessment.raw_points, abs=1e-12
    )


# --------------------------------------------------------------------------- #
# Versions and semantics
# --------------------------------------------------------------------------- #
async def test_every_assessment_carries_its_versions(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.engine_version == ENGINE_VERSION
    assert assessment.model_version == HEURISTIC_VERSION
    assert assessment.model_type == "DETERMINISTIC_HEURISTIC"
    assert assessment.score_semantics == "NORMALIZED_RISK_INDEX"
    assert assessment.advisory is True


async def test_the_band_and_recommendation_agree_with_the_config(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.band is DEFAULT_RISK_CONFIG.band_for(assessment.score)
    assert assessment.recommendation is DEFAULT_RISK_CONFIG.recommendation_for(assessment.band)


# --------------------------------------------------------------------------- #
# The advisory result sits beside the authoritative one
# --------------------------------------------------------------------------- #
async def test_the_deterministic_decision_is_carried_for_context(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.policy_decision == PolicyOutcome.REQUIRE_APPROVAL.value
    assert "SOFT_BUDGET_EXCEEDED" in assessment.policy_reason_codes


async def test_a_denied_mission_is_still_assessable_and_still_denied(session):
    mission_id = await _mission(session, soft_budget_inr=2000, hard_limit_inr=3000)
    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.policy_decision == PolicyOutcome.DENY.value
    assert "HARD_LIMIT_EXCEEDED" in assessment.policy_reason_codes
    assert assessment.transaction_digest_prefix is None


# --------------------------------------------------------------------------- #
# Cold start
# --------------------------------------------------------------------------- #
async def test_a_first_transaction_reports_cold_start_and_scores_no_anomaly(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    quality = assessment.data_quality
    assert quality.cold_start is True
    assert quality.history_available is False
    assert quality.history_observations == 0
    codes = {factor.code for factor in assessment.factors}
    assert "AMOUNT_ABOVE_MERCHANT_HISTORY_MEDIAN" not in codes


async def test_cold_start_is_disclosed_in_the_explanation(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    joined = "\n".join(assessment.explanation)
    assert "no prior observations" in joined
    assert "not evidence of risk" in joined


async def test_history_becomes_available_once_enough_observations_exist(session):
    for index in range(DEFAULT_RISK_CONFIG.min_history_observations + 1):
        mission = Mission(id=uuid.uuid4(), quantity=1, state="POLICY_CHECKED")
        session.add(mission)
        await session.flush()
        await issue_authorization(
            session,
            capabilities=KERNEL,
            mission_id=mission.id,
            transaction=approved_transaction(
                merchant_id="merchant_a",
                product_id=f"h-{index}",
                amount_inr=1000,
                nonce=generate_nonce(),
            ),
        )
    await session.commit()

    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.data_quality.history_available is True
    assert assessment.data_quality.cold_start is False
    codes = {factor.code for factor in assessment.factors}
    assert "AMOUNT_ABOVE_MERCHANT_HISTORY_MEDIAN" in codes


# --------------------------------------------------------------------------- #
# The registry, not the payload
# --------------------------------------------------------------------------- #
async def test_a_low_trust_registry_entry_raises_the_score(session):
    low = MerchantRegistry(
        {"merchant_a": MerchantRecord(merchant_id="merchant_a", display_name="A", trust_score=0.1)}
    )
    mission_id = await _mission(session, registry=low)
    with_low = await assess_mission(session, mission_id, registry=low, now=NOW)

    high = MerchantRegistry(
        {"merchant_a": MerchantRecord(merchant_id="merchant_a", display_name="A", trust_score=0.95)}
    )
    with_high = await assess_mission(session, mission_id, registry=high, now=NOW)
    assert with_low.score > with_high.score


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #
async def test_assessing_appends_no_event(session):
    mission_id = await _mission(session)
    before = len((await session.execute(select(AuditEventRow))).scalars().all())
    await assess_mission(session, mission_id, now=NOW)
    await session.commit()
    after = len((await session.execute(select(AuditEventRow))).scalars().all())
    assert after == before


async def test_recording_appends_exactly_one_event(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    before = len((await session.execute(select(AuditEventRow))).scalars().all())
    row = await record_assessment(session, assessment)
    await session.commit()
    after = len((await session.execute(select(AuditEventRow))).scalars().all())

    assert after == before + 1
    assert row.event_type == EventType.RISK_ASSESSED.value
    assert row.actor == ACTOR


async def test_the_recorded_payload_carries_codes_not_observations(session):
    mission_id = await _mission(session, merchants=[MockMerchantB()])
    assessment = await assess_mission(session, mission_id, now=NOW)
    row = await record_assessment(session, assessment)
    await session.commit()

    payload = row.payload
    assert payload["band"] == assessment.band.value
    assert payload["advisory"] is True
    assert set(payload["factor_codes"]) == {f.code for f in assessment.factors}
    assert "feature_values" not in payload
    assert "weight" not in repr(payload)


async def test_recording_keeps_the_audit_chain_verifiable(session):
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    await record_assessment(session, assessment)
    await session.commit()

    result = await verify_mission_chain(session, mission_id)
    assert result.valid is True


async def test_recording_is_deliberately_not_idempotent(session):
    """Two assessments at two moments are two facts."""
    mission_id = await _mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)
    await record_assessment(session, assessment)
    await record_assessment(session, assessment)
    await session.commit()

    rows = (
        (
            await session.execute(
                select(AuditEventRow).where(
                    AuditEventRow.event_type == EventType.RISK_ASSESSED.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #
async def test_an_unknown_mission_raises(session):
    with pytest.raises(MissionNotFound):
        await assess_mission(session, uuid.uuid4(), now=NOW)


async def test_a_bare_mission_scores_without_crashing(session):
    """No offers, no decision, no authorization, no payment."""
    mission = Mission(id=uuid.uuid4(), quantity=1, state="CREATED")
    session.add(mission)
    await session.commit()

    assessment = await assess_mission(session, mission.id, now=NOW)
    assert assessment.score == 0.0
    assert assessment.band is RiskBand.LOW
    assert assessment.recommendation is RiskRecommendation.PROCEED
    assert assessment.data_quality.features_unavailable > 0
