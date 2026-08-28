"""Advisory risk routes (Phase 7).

TWO ROUTES, AND THE DIFFERENCE BETWEEN THEM IS THE DESIGN
-----------------------------------------------------------
``GET  /missions/{id}/risk``          computes and returns. Writes NOTHING.
``POST /missions/{id}/risk/assess``   computes, returns, and records one
                                      ``RISK_ASSESSED`` audit event.

Recording is a separate verb because it is a separate act. A read that quietly
appended to a mission's hash chain would mean anyone inspecting a mission had
altered its history, and "how many times was this mission looked at" would
become part of the record replay has to reconstruct.

WHAT NEITHER ROUTE ACCEPTS
---------------------------
Neither has a request body. Not a score, not a band, not a recommendation, not a
threshold, not a weight, not a capability set, not a merchant trust value. This
is structural: there is no Pydantic model bound to either handler, so there is no
field through which a caller could offer one, and a caller-supplied
``{"score": 0.0}`` has nowhere to land — FastAPI ignores a body no handler
declares. ``tests/test_risk_api.py`` parses this module and asserts no handler
signature names ``config``, ``score``, or ``registry``.

Weights reach the engine only from ``services.risk_engine.config``, which is
frozen and module-owned. Neither handler passes a ``config``, so neither can be
made to score against anything but the server's own rules.

WHAT NEITHER ROUTE CAN CAUSE
-----------------------------
No payment, no authorization issuance, no authorization consumption, no policy
change, no mission state transition. ``assess_mission`` cannot reach the code
that does any of those (its import graph is asserted), and ``record_assessment``
appends one audit event and nothing else. A CRITICAL band changes no response
status and no mission: the route answers 200 with advice either way, because an
advisory layer that returned 403 would be enforcing.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from services.risk_engine.engine import assess_mission, record_assessment
from services.risk_engine.features import MissionNotFound
from services.risk_engine.models import RiskAssessment
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["risk"])


@router.get("/missions/{mission_id}/risk", response_model=RiskAssessment)
async def get_mission_risk(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> RiskAssessment:
    """Score a mission. READ ONLY — no row is written, no event is appended.

    Returns 200 with the assessment regardless of band. A HIGH or CRITICAL score
    is advice, and returning an error status for it would turn the advisory layer
    into a gate — the exact thing Phase 7 exists not to build. The authoritative
    outcome travels in ``policy_decision`` beside the advisory one so a client
    cannot mistake the second for the first.
    """
    try:
        return await assess_mission(session, mission_id)
    except MissionNotFound as missing:
        raise HTTPException(status_code=404, detail="mission not found") from missing


@router.post("/missions/{mission_id}/risk/assess", response_model=RiskAssessment, status_code=201)
async def assess_and_record(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> RiskAssessment:
    """Score a mission and record the verdict as a ``RISK_ASSESSED`` event.

    The one write the risk engine has. The payload carries the verdict, the
    factor CODES, and the versions — never raw feature values, never the weight
    table, never a full transaction digest.

    Recording an assessment grants nothing. Phase 5's replay reducer treats the
    event as inert: a mission replayed with it present reconstructs identically
    to one without it, so an advisory record cannot influence a reconstruction
    any more than it can influence a decision.

    201 rather than 200 because a resource was created — an audit event — and a
    caller that repeats the request creates a second one. This endpoint is
    deliberately NOT idempotent: two assessments of a mission at two moments are
    two facts, and collapsing them would lose the moment the second one noticed
    something the first did not.
    """
    try:
        assessment = await assess_mission(session, mission_id)
    except MissionNotFound as missing:
        raise HTTPException(status_code=404, detail="mission not found") from missing
    await record_assessment(session, assessment)
    return assessment
