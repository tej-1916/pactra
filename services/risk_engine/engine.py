"""Engine entry points: assess (read-only) and record (explicit, opt-in).

TWO FUNCTIONS, AND THE SPLIT IS THE POINT
------------------------------------------
``assess_mission`` reads. ``record_assessment`` writes one audit event. They are
separate functions because an advisory layer that wrote to the ledger merely by
being consulted would make "was the risk engine asked?" a fact the deterministic
replay has to reconstruct, and would let a read path acquire a side effect by
default. Recording is something a caller chooses, names, and is accountable for.

WHY THE RISK ENGINE IS NOT WIRED INTO THE ORCHESTRATOR
-------------------------------------------------------
Phase 7 deliberately does NOT insert an assessment into the automatic mission
path, and this is a decision rather than an omission.

The mission path writes a hash-chained audit history that Phase 5's deterministic
replay reconstructs and compares against persisted state. Emitting a
``RISK_ASSESSED`` event on every mission would put an advisory artifact inside
that history permanently — every mission's event sequence would change, the
Phase 6 differential scenarios would be comparing sequences containing it, and
the enforcement path would have gained a step whose only output is advice. The
brief's own rule is that risk must never be a barrier before payment; the
cleanest way to guarantee that is for the payment path not to call it.

So the engine is invoked on demand — ``GET /missions/{id}/risk`` computes and
records nothing, ``POST /missions/{id}/risk/assess`` computes and records
explicitly. The consequence is real and is listed as remaining debt: a mission
that nobody asks about has no assessment. That is a smaller cost than an
advisory layer with standing write access to the audit chain.

WHAT ``assess_mission`` CANNOT DO
----------------------------------
It has no parameter for a score, a band, a recommendation, an authorization, or
a policy outcome, so a caller cannot supply one. It cannot reach
``services.payment_executor``, the merchant adapters, or the authorization write
path — ``tests/test_risk_isolation.py`` parses this module's import graph and
fails if it ever can. It issues only ``SELECT``s, proved additionally by
landmines and a row census in the same test.

DETERMINISM
-----------
``now`` is a parameter, not a call to the clock, so identical state at an
identical instant yields an identical score, band, recommendation, and factor
list. ``assessment_id`` is fresh per evaluation on purpose: it identifies THIS
evaluation, not this result. Two evaluations of unchanged state agree on
everything that carries meaning and differ only in the id that says they were
two evaluations.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from apps.api.db.models import AuditEventRow
from packages.schemas.domain import EventType, utcnow
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import append_event
from services.risk_engine.config import (
    DEFAULT_RISK_CONFIG,
    ENGINE_VERSION,
    HEURISTIC_VERSION,
    MODEL_TYPE_HEURISTIC,
    RiskConfig,
)
from services.risk_engine.explain import build_explanation, count_availability
from services.risk_engine.features import (
    MissionFacts,
    MissionNotFound,
    extract_features,
    extract_merchant_history_features,
    load_mission_facts,
)
from services.risk_engine.heuristic import normalize, score
from services.risk_engine.models import DataQuality, RiskAssessment
from services.security_kernel.merchant_registry import MerchantRegistry

#: Actor recorded on a ``RISK_ASSESSED`` audit event. A distinct principal name
#: so the ledger shows at a glance that the advisory layer wrote this and the
#: security kernel did not.
ACTOR = "risk-engine"

#: How much of the transaction digest travels on an assessment. Same rule as
#: Phase 3/4 audit payloads: enough to correlate across a mission, never a copy
#: of the commitment itself.
DIGEST_PREFIX = 16

#: What ``history_scope`` says on every assessment. Pinned to "merchant" because
#: that is the only population PACTRA can baseline — there is no user identity in
#: the data model, so no per-user scope exists to select.
HISTORY_SCOPE = "authenticated_merchant"

__all__ = ["MissionNotFound", "assess_mission", "record_assessment"]


async def assess_mission(
    session: AsyncSession,
    mission_id: uuid.UUID,
    *,
    config: RiskConfig | None = None,
    registry: MerchantRegistry | None = None,
    now: datetime | None = None,
) -> RiskAssessment:
    """Score one mission. READ ONLY — no row is written, nothing is consumed.

    ``config`` exists for tests and the evaluation harness. No HTTP route passes
    one and no route accepts one, which ``tests/test_risk_api.py`` asserts by
    parsing the route module: server-owned weights that a request could replace
    would not be server-owned.
    """
    settings = config or DEFAULT_RISK_CONFIG
    moment = now or utcnow()

    facts: MissionFacts = await load_mission_facts(
        session, mission_id, config=settings, registry=registry
    )
    features = extract_features(facts, config=settings, now=moment)
    features.update(await extract_merchant_history_features(session, facts))

    factors, raw_points = score(features, config=settings)
    normalized = normalize(raw_points, config=settings)
    band = settings.band_for(normalized)
    recommendation = settings.recommendation_for(band)

    available, unavailable = count_availability(features)
    history = facts.history
    quality = DataQuality(
        history_available=bool(history and history.available),
        history_observations=history.amount_observations if history else 0,
        history_scope=HISTORY_SCOPE,
        cold_start=bool(history is None or history.cold_start),
        features_available=available,
        features_unavailable=unavailable,
        audit_chain_verified=facts.audit_chain_valid,
    )

    decision = facts.policy_decision
    return RiskAssessment(
        mission_id=mission_id,
        transaction_digest_prefix=(
            None
            if facts.authorization is None
            else facts.authorization.transaction_digest[:DIGEST_PREFIX]
        ),
        score=normalized,
        raw_points=raw_points,
        saturation_points=settings.saturation_points,
        band=band,
        recommendation=recommendation,
        feature_values=features,
        factors=factors,
        explanation=build_explanation(
            score=normalized,
            band=band,
            recommendation=recommendation,
            factors=factors,
            quality=quality,
            policy_decision=None if decision is None else decision.decision,
        ),
        evaluated_at=moment,
        engine_version=ENGINE_VERSION,
        model_type=MODEL_TYPE_HEURISTIC,
        model_version=HEURISTIC_VERSION,
        data_quality=quality,
        policy_decision=None if decision is None else decision.decision,
        policy_reason_codes=[] if decision is None else list(decision.reason_codes or []),
    )


async def record_assessment(session: AsyncSession, assessment: RiskAssessment) -> AuditEventRow:
    """Append one ``RISK_ASSESSED`` event. The engine's ONLY write, ever.

    The payload comes from ``RiskAssessment.audit_payload()`` — verdict, factor
    CODES, versions, and data-quality flags. Deliberately absent: raw feature
    values, the merchant payload, the full transaction digest, and the weight
    table. A ledger reader learns what the engine concluded and which controls it
    read; it does not learn enough to reconstruct the mission's contents, and it
    learns nothing about how to move a future score.

    Appending an event does not make the assessment authoritative. Phase 5's
    replay reducer treats ``RISK_ASSESSED`` as inert: it advances no mission
    state, touches no authorization, and moves no payment. A test asserts a
    replay with the event present is identical to one without it, so the advisory
    layer cannot influence a reconstruction any more than it influences a
    decision.
    """
    return await append_event(
        session,
        mission_id=assessment.mission_id,
        event_type=EventType.RISK_ASSESSED,
        actor=ACTOR,
        payload=assessment.audit_payload(),
    )
