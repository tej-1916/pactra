"""Mission API routes (Phase 1)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from packages.schemas.domain import CreateMissionRequest
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import Mission, Offer, PolicyDecisionRow
from apps.api.db.session import get_session
from apps.api.pactra.schemas_api import (
    AuditEventOut,
    MissionOut,
    OfferOut,
    PolicyDecisionOut,
)

router = APIRouter(prefix="/api/v1", tags=["missions"])


def _offer_out(o: Offer) -> OfferOut:
    return OfferOut(
        offer_id=o.id,
        merchant_id=o.merchant_id,
        merchant_name=o.merchant_name,
        merchant_trust=o.merchant_trust,
        product_id=o.product_id,
        title=o.title,
        amount_inr=o.amount_inr,
        currency=o.currency,
        rating=o.rating,
        in_stock=o.in_stock,
        valid=o.valid,
        rejection_reasons=list(o.rejection_reasons or []),
        rank=o.rank,
    )


async def _load_mission(session: AsyncSession, mission_id: uuid.UUID) -> Mission:
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="mission not found")
    return mission


async def _mission_out(session: AsyncSession, mission: Mission) -> MissionOut:
    offers = (
        (
            await session.execute(
                select(Offer).where(Offer.mission_id == mission.id).order_by(Offer.rank)
            )
        )
        .scalars()
        .all()
    )
    pd = (
        await session.execute(
            select(PolicyDecisionRow)
            .where(PolicyDecisionRow.mission_id == mission.id)
            .order_by(PolicyDecisionRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    return MissionOut(
        id=mission.id,
        state=mission.state,
        raw_query=mission.raw_query,
        quantity=mission.quantity,
        offers=[_offer_out(o) for o in offers],
        policy_decision=(
            PolicyDecisionOut(
                decision=pd.decision,
                reason_codes=list(pd.reason_codes or []),
                requested_amount=pd.requested_amount,
                soft_budget=pd.soft_budget,
                hard_limit=pd.hard_limit,
                selected_offer_id=pd.selected_offer_id,
            )
            if pd is not None
            else None
        ),
        created_at=mission.created_at,
    )


@router.post("/missions", response_model=MissionOut, status_code=201)
async def create_mission(
    request: CreateMissionRequest, session: AsyncSession = Depends(get_session)
) -> MissionOut:
    mission = await Orchestrator().run(session, request)
    return await _mission_out(session, mission)


@router.get("/missions/{mission_id}", response_model=MissionOut)
async def get_mission(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> MissionOut:
    mission = await _load_mission(session, mission_id)
    return await _mission_out(session, mission)


@router.get("/missions/{mission_id}/events", response_model=list[AuditEventOut])
async def get_events(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[AuditEventOut]:
    await _load_mission(session, mission_id)
    rows = await list_events(session, mission_id)
    return [
        AuditEventOut(
            event_id=r.event_id,
            sequence=r.sequence,
            event_type=r.event_type,
            actor=r.actor,
            payload=r.payload,
            previous_hash=r.previous_hash,
            event_hash=r.event_hash,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/offers/{mission_id}", response_model=list[OfferOut])
async def get_offers(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> list[OfferOut]:
    await _load_mission(session, mission_id)
    offers = (
        (
            await session.execute(
                select(Offer).where(Offer.mission_id == mission_id).order_by(Offer.rank)
            )
        )
        .scalars()
        .all()
    )
    return [_offer_out(o) for o in offers]
