"""RISK SCORE ≠ AUTHORITY — the full matrix, one test per cell.

The eight cells the Phase 7 audit names, each proved against a REAL mission
driven through the REAL kernel rather than against a mock:

    A  policy DENY  + risk LOW       -> still DENY
    B  policy DENY  + risk CRITICAL  -> still DENY
    C  policy ALLOW + risk LOW       -> still ALLOW, may recommend PROCEED
    D  policy ALLOW + risk CRITICAL  -> still ALLOW, recommends escalation only
    E  replayed authorization + risk LOW      -> payment still impossible
    F  replayed authorization + risk CRITICAL -> payment still impossible
    G  hard limit exceeded + risk LOW         -> payment still impossible
    H  hard limit exceeded + risk CRITICAL    -> payment still impossible

HOW THE CRITICAL CELLS ARE CONSTRUCTED, AND WHY IT IS HONEST
--------------------------------------------------------------
Cells B, D, F and H need a CRITICAL score on a mission the kernel already
adjudicated. Rather than hunting for a mission that happens to score CRITICAL —
which would make the test depend on the weight table and break whenever a weight
changed — they lower ``saturation_points`` so the same mission saturates.

That is legitimate because of what is under test. The question is never "does
this mission deserve CRITICAL"; it is "given a CRITICAL assessment, what changes
in the kernel". The answer must be *nothing*, whatever produced the CRITICAL. A
config the caller cannot supply in production is exactly the right instrument:
it manufactures the band without touching a single kernel input.

"PAYMENT STILL IMPOSSIBLE" IS PROVED BY ATTEMPTING THE PAYMENT
---------------------------------------------------------------
Cells E-H do not assert on a status string. They call the real
``create_payment_intent`` under the real ``payment-executor`` capability and
require it to be refused, then count the payment_intents table. A control that
is merely *described* as holding is not a control that was exercised.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from apps.api.db.models import AuthorizationRow, Mission, PaymentIntentRow
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import (
    CreateMissionRequest,
    MissionConstraints,
    MissionState,
    PolicyOutcome,
)
from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
from services.agent_orchestrator.orchestrator import Orchestrator
from services.payment_executor.intents import create_payment_intent
from services.risk_engine.config import RiskConfig
from services.risk_engine.engine import assess_mission
from services.risk_engine.models import RiskBand, RiskRecommendation
from services.security_kernel.authorization import (
    AuthorizationFailure,
    activate_authorization,
    authorization_for_mission,
    consume_authorization,
    rebuild_bound_transaction,
)
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
EXECUTOR = payment_executor_capabilities()

#: Manufactures CRITICAL without touching any kernel input. Not reachable from a
#: request: no route accepts a config (asserted in tests/test_risk_api.py).
FORCE_CRITICAL = RiskConfig(saturation_points=0.01)


def _constraints(**overrides) -> MissionConstraints:
    base = dict(
        category="wireless_earbuds",
        soft_budget_inr=4000,
        hard_limit_inr=4500,
        min_rating=3.5,
        currency="INR",
    )
    base.update(overrides)
    return MissionConstraints(**base)


async def _mission(session, **overrides) -> uuid.UUID:
    mission = await Orchestrator(merchants=[MockMerchantA()]).run(
        session, CreateMissionRequest(quantity=1, constraints=_constraints(**overrides))
    )
    await session.commit()
    return mission.id


async def _allowed_mission(session) -> uuid.UUID:
    """Best offer 4299 under a 4500 soft budget -> ALLOW, auto-activated."""
    return await _mission(session, soft_budget_inr=4500, hard_limit_inr=4500)


async def _denied_mission(session) -> uuid.UUID:
    """Best offer 4299 over a 3000 ceiling -> HARD_LIMIT_EXCEEDED -> DENY."""
    return await _mission(session, soft_budget_inr=2000, hard_limit_inr=3000)


async def _intent_count(session) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(PaymentIntentRow))).scalar_one()
    )


async def _authorization_count(session, mission_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(AuthorizationRow)
                .where(AuthorizationRow.mission_id == mission_id)
            )
        ).scalar_one()
    )


# --------------------------------------------------------------------------- #
# A / B — a DENY stays a DENY at both ends of the risk scale
# --------------------------------------------------------------------------- #
async def test_A_deny_with_low_risk_remains_deny(session):
    mission_id = await _denied_mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)

    assert assessment.band is RiskBand.LOW
    assert assessment.policy_decision == PolicyOutcome.DENY.value
    assert "HARD_LIMIT_EXCEEDED" in assessment.policy_reason_codes

    await session.commit()
    mission = await session.get(Mission, mission_id, populate_existing=True)
    assert mission.state == MissionState.CANCELLED.value
    assert await _authorization_count(session, mission_id) == 0


async def test_B_deny_with_critical_risk_remains_deny(session):
    mission_id = await _denied_mission(session)
    assessment = await assess_mission(session, mission_id, config=FORCE_CRITICAL, now=NOW)

    assert assessment.band is RiskBand.CRITICAL
    assert assessment.recommendation is RiskRecommendation.ESCALATE
    # The advisory verdict is the loudest available, and the authoritative one
    # is untouched beside it.
    assert assessment.policy_decision == PolicyOutcome.DENY.value

    await session.commit()
    mission = await session.get(Mission, mission_id, populate_existing=True)
    assert mission.state == MissionState.CANCELLED.value
    assert await _authorization_count(session, mission_id) == 0
    assert await _intent_count(session) == 0


# --------------------------------------------------------------------------- #
# C / D — an ALLOW stays an ALLOW at both ends
# --------------------------------------------------------------------------- #
async def test_C_allow_with_low_risk_remains_allow_and_may_proceed(session):
    mission_id = await _allowed_mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)

    assert assessment.band is RiskBand.LOW
    assert assessment.recommendation is RiskRecommendation.PROCEED
    assert assessment.policy_decision == PolicyOutcome.ALLOW.value

    await session.commit()
    mission = await session.get(Mission, mission_id, populate_existing=True)
    assert mission.state == MissionState.AUTHORIZED.value


async def test_D_allow_with_critical_risk_remains_allow_and_only_advises(session):
    """The cell an advisory layer most easily gets wrong.

    CRITICAL must not deny, must not revoke, must not expire the authorization,
    and must leave the transaction genuinely spendable — proved by spending it.
    """
    mission_id = await _allowed_mission(session)
    assessment = await assess_mission(session, mission_id, config=FORCE_CRITICAL, now=NOW)

    assert assessment.band is RiskBand.CRITICAL
    assert assessment.recommendation is RiskRecommendation.ESCALATE
    assert assessment.recommendation.value not in {o.value for o in PolicyOutcome}
    assert assessment.policy_decision == PolicyOutcome.ALLOW.value
    await session.commit()

    mission = await session.get(Mission, mission_id, populate_existing=True)
    assert mission.state == MissionState.AUTHORIZED.value

    row = await authorization_for_mission(session, mission_id)
    assert row.status == AuthorizationStatus.ACTIVE.value

    # Still spendable: the strongest statement that nothing was taken away.
    consumed = await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=rebuild_bound_transaction(row)
    )
    assert consumed.status == AuthorizationStatus.CONSUMED.value


# --------------------------------------------------------------------------- #
# E / F — a replayed authorization stays refused at both ends
# --------------------------------------------------------------------------- #
async def _consume_once(session, mission_id: uuid.UUID) -> AuthorizationRow:
    row = await authorization_for_mission(session, mission_id)
    if row.status == AuthorizationStatus.PENDING.value:
        await activate_authorization(session, authorization_id=row.authorization_id)
    await consume_authorization(
        session, authorization_id=row.authorization_id, transaction=rebuild_bound_transaction(row)
    )
    await session.commit()
    return row


async def _payment_is_refused(session, mission_id: uuid.UUID, authorization_id: uuid.UUID) -> bool:
    """Attempt the real payment path. True when it was refused AND nothing moved."""
    before = await _intent_count(session)
    refused = False
    try:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=f"authority-matrix-{uuid.uuid4()}",
            provider="fake",
        )
    except Exception:  # noqa: BLE001 - any refusal is a refusal; the census decides
        refused = True
        await session.rollback()
    return refused and await _intent_count(session) == before


async def test_E_replayed_authorization_with_low_risk_still_cannot_pay(session):
    mission_id = await _allowed_mission(session)
    row = await _consume_once(session, mission_id)

    assessment = await assess_mission(session, mission_id, now=NOW)
    assert assessment.band is RiskBand.LOW

    assert await _payment_is_refused(session, mission_id, row.authorization_id)


async def test_F_replayed_authorization_with_critical_risk_still_cannot_pay(session):
    mission_id = await _allowed_mission(session)
    row = await _consume_once(session, mission_id)

    assessment = await assess_mission(session, mission_id, config=FORCE_CRITICAL, now=NOW)
    assert assessment.band is RiskBand.CRITICAL

    assert await _payment_is_refused(session, mission_id, row.authorization_id)


async def test_replay_is_still_refused_after_repeated_assessment(session):
    """Assessing many times must not wear the control down."""
    mission_id = await _allowed_mission(session)
    row = await _consume_once(session, mission_id)
    for _ in range(5):
        await assess_mission(session, mission_id, now=NOW)
    await session.commit()

    with pytest.raises(AuthorizationFailure):
        await consume_authorization(
            session,
            authorization_id=row.authorization_id,
            transaction=rebuild_bound_transaction(row),
        )


# --------------------------------------------------------------------------- #
# G / H — a hard-limit violation stays impossible at both ends
# --------------------------------------------------------------------------- #
async def test_G_hard_limit_exceeded_with_low_risk_still_cannot_pay(session):
    mission_id = await _denied_mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)

    assert assessment.band is RiskBand.LOW
    assert assessment.policy_decision == PolicyOutcome.DENY.value
    # There is no authorization to present, so there is nothing to pay with.
    assert await _authorization_count(session, mission_id) == 0
    assert await _intent_count(session) == 0


async def test_H_hard_limit_exceeded_with_critical_risk_still_cannot_pay(session):
    mission_id = await _denied_mission(session)
    assessment = await assess_mission(session, mission_id, config=FORCE_CRITICAL, now=NOW)

    assert assessment.band is RiskBand.CRITICAL
    assert assessment.policy_decision == PolicyOutcome.DENY.value
    assert await _authorization_count(session, mission_id) == 0
    assert await _intent_count(session) == 0


# --------------------------------------------------------------------------- #
# HIGH RISK != MALICIOUS, and LOW RISK != SAFE
# --------------------------------------------------------------------------- #
async def test_a_benign_transaction_can_score_high_purely_from_infrastructure_trouble(
    session,
):
    """HIGH RISK != MALICIOUS, demonstrated without any hostile input.

    An honest but unregistered merchant plus real provider timeouts is enough to
    reach MEDIUM/HIGH. Nothing in this mission is an attack: no spoof, no
    escalation, no replay, no tamper. The advisory layer flags it because it is
    UNUSUAL, and the kernel permits it because it is LEGITIMATE — which is the
    whole reason the two layers are separate.

    Deliberately NOT added to the evaluation corpus as a BENIGN label: under this
    project's own label definition ("a reviewer would want to see this"), a
    transaction with an unregistered counterparty and repeated lost provider
    responses is one a reviewer WOULD want to see. Labelling it benign to keep
    the false-positive rate at zero would be exactly the label manipulation this
    audit exists to catch.
    """
    from services.risk_engine.scenarios import HonestMerchant
    from services.security_kernel.merchant_registry import MerchantRegistry

    empty_registry = MerchantRegistry({})
    mission = await Orchestrator(
        merchants=[HonestMerchant("unregistered_but_honest", price=4400)],
        registry=empty_registry,
    ).run(session, CreateMissionRequest(quantity=1, constraints=_constraints()))
    await session.commit()

    assessment = await assess_mission(session, mission.id, registry=empty_registry, now=NOW)

    # Not malicious: no security event of any kind was recorded.
    for feature in (
        "merchant_identity_mismatch_events",
        "merchant_authority_escalation_events",
        "authorization_replay_attempts",
        "transaction_binding_failures",
        "mission_authority_escalation_attempts",
    ):
        assert assessment.feature_values[feature].value == 0
    assert assessment.feature_values["audit_chain_valid"].value is True

    # ...and yet it is flagged, on reputation and headroom alone.
    assert assessment.score >= 0.25
    assert assessment.recommendation is not RiskRecommendation.PROCEED
    codes = {factor.code for factor in assessment.factors}
    assert "MERCHANT_UNKNOWN" in codes

    # The kernel permitted it, and still does.
    assert assessment.policy_decision in {
        PolicyOutcome.ALLOW.value,
        PolicyOutcome.REQUIRE_APPROVAL.value,
    }
    await session.commit()
    reloaded = await session.get(Mission, mission.id, populate_existing=True)
    assert reloaded.state != MissionState.CANCELLED.value


async def test_a_blocked_attack_can_score_low_and_is_still_blocked(session):
    """LOW RISK != SAFE, and the kernel does not consult the score.

    A hard-limit violation is the cleanest case: the deterministic engine refuses
    it outright, and precisely BECAUSE it refused so early there is no
    authorization, no payment and almost no history for the heuristic to read —
    so the advisory score is LOW.

    That inversion is the point. If the risk engine were load-bearing, a LOW
    score here would be a bypass. It is not, because the kernel had already
    decided before the engine was asked. The weights are deliberately NOT
    adjusted to force every refused attack to CRITICAL: doing so would make the
    score look like the control.
    """
    mission_id = await _denied_mission(session)
    assessment = await assess_mission(session, mission_id, now=NOW)

    assert assessment.band is RiskBand.LOW
    assert assessment.recommendation is RiskRecommendation.PROCEED
    # And the attack is refused anyway, by the layer that actually decides.
    assert assessment.policy_decision == PolicyOutcome.DENY.value
    assert await _authorization_count(session, mission_id) == 0
    assert await _intent_count(session) == 0
