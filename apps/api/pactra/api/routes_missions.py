"""Mission API routes (Phase 1 + Phase 3 authorization + Phase 5 audit/replay).

The two Phase 5 routes are READ ONLY in the strong sense: they append no audit
event, mutate no mission, and repair nothing they find broken. A verification
endpoint that healed a chain would destroy the evidence it exists to surface,
and a replay endpoint that reconciled the mission row would make a derived
projection authoritative over the rows the kernel actually enforces against.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from packages.schemas.approval import ApprovalScheme, approval_message
from packages.schemas.audit import AuditVerificationResult, MissionReplayResult
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.domain import CreateMissionRequest, MissionState, as_utc, utcnow
from services.agent_orchestrator.orchestrator import Orchestrator
from services.agent_orchestrator.state_machine import assert_transition
from services.audit_ledger.ledger import list_events
from services.audit_ledger.replay import replay_mission
from services.audit_ledger.verify import verify_mission_chain
from services.security_kernel.authorization import (
    AuthorizationFailure,
    approve_authorization_with_signature,
    authorization_for_mission,
    rebuild_bound_transaction,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.models import AuthorizationRow, Mission, Offer, PolicyDecisionRow
from apps.api.db.session import get_session
from apps.api.pactra.config import get_settings
from apps.api.pactra.schemas_api import (
    ApprovalChallengeOut,
    ApprovalRequest,
    AuditEventOut,
    AuthorizationOut,
    BoundTransactionSummary,
    MissionOut,
    OfferOut,
    PolicyDecisionOut,
)

router = APIRouter(prefix="/api/v1", tags=["missions"])


def _offer_out(o: Offer) -> OfferOut:
    return OfferOut(
        offer_id=o.id,
        offer_version=o.offer_version,
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


def _authorization_out(row: AuthorizationRow) -> AuthorizationOut:
    """Project an authorization row for the API.

    Note what is NOT copied across: the nonce. It never leaves the kernel.
    """
    return AuthorizationOut(
        authorization_id=row.authorization_id,
        mission_id=row.mission_id,
        status=row.status,
        transaction_digest=row.transaction_digest,
        binding_version=row.binding_version,
        policy_version=row.policy_version,
        offer_version=row.offer_version,
        approval_scheme=row.approval_scheme,
        signing_key_id=row.signing_key_id,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
        bound_merchant_id=row.bound_merchant_id,
        bound_product_id=row.bound_product_id,
        bound_quantity=row.bound_quantity,
        bound_amount_inr=row.bound_amount_inr,
        bound_currency=row.bound_currency,
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
                policy_version=pd.policy_version,
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
    # SUCCESS_RESPONSE_IMPLIES_DURABLE_COMMIT. The whole mission — its offers,
    # policy decision, authorization and audit events — becomes durable in one
    # commit here, before the response body is built, so a caller that reads
    # the mission the instant it sees this 201 cannot race the write.
    await session.commit()
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


@router.get("/missions/{mission_id}/audit/verify", response_model=AuditVerificationResult)
async def verify_audit_chain(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AuditVerificationResult:
    """Recompute the mission's hash chain and report whether it is intact.

    READ ONLY. Nothing is rewritten — not `event_hash`, not `previous_hash`, not
    `sequence`, not `payload`. Tamper evidence is worthless if the verifier
    repairs what it is supposed to detect, so there is no repair path to reach.

    A valid chain answers `{"valid": true, "events_checked": N}`; a broken one
    adds `first_invalid_sequence` and a `reason_code` naming how it broke. An
    unknown mission is a 404, the same as every other mission route.
    """
    await _load_mission(session, mission_id)
    return await verify_mission_chain(session, mission_id)


@router.get("/missions/{mission_id}/replay", response_model=MissionReplayResult)
async def replay_mission_state(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> MissionReplayResult:
    """Reconstruct mission state from the event history alone.

    READ ONLY, and deliberately gated: the chain is verified first, and a chain
    that does not verify yields `trusted: false` with NO reconstructed state
    attached. Returning a projection alongside a warning flag would hand callers
    exactly the object they would read past the flag to reach.

    The response also carries a diagnostic `comparison` of the replayed state
    against the persisted rows. A mismatch is REPORTED and never repaired —
    replay is observability here, not recovery.
    """
    await _load_mission(session, mission_id)
    return await replay_mission(session, mission_id)


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


@router.get("/missions/{mission_id}/authorization", response_model=AuthorizationOut)
async def get_authorization(
    mission_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AuthorizationOut:
    """Read the mission's authorization artifact. Never includes the nonce."""
    await _load_mission(session, mission_id)
    row = await authorization_for_mission(session, mission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no authorization for this mission")
    return _authorization_out(row)


@router.post("/missions/{mission_id}/authorization/approve", response_model=AuthorizationOut)
async def approve_authorization(
    mission_id: uuid.UUID,
    request: ApprovalRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthorizationOut:
    """Verify a LOCAL CRYPTOGRAPHIC APPROVAL PROOF and atomically activate."""
    mission = await _load_mission(session, mission_id)
    row = await authorization_for_mission(session, mission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no authorization for this mission")

    if mission.state != MissionState.AWAITING_APPROVAL.value:
        raise HTTPException(
            status_code=409,
            detail={
                "reason_code": "MISSION_NOT_AWAITING_APPROVAL",
                "state": mission.state,
            },
        )

    try:
        activated = await approve_authorization_with_signature(
            session,
            mission_id=mission_id,
            authorization_id=row.authorization_id,
            signing_key_id=request.signing_key_id,
            signature_hex=request.signature,
        )
    except AuthorizationFailure as failure:
        # Security rejection events appended by the kernel must survive the
        # HTTP exception.  This request transaction has performed no privileged
        # mutation; committing here durably records only safe failure audit (and
        # an expiry demotion, where applicable).  The dependency's subsequent
        # rollback is therefore a no-op.
        await session.commit()
        raise HTTPException(
            status_code=409,
            detail={"reason_code": failure.reason_code, "detail": failure.detail},
        ) from failure

    assert_transition(MissionState(mission.state), MissionState.AUTHORIZED)
    mission.state = MissionState.AUTHORIZED.value
    await session.flush()
    # The verified proof, the ACTIVE authorization and the AUTHORIZED mission
    # commit together, before the caller is told the approval succeeded.
    await session.commit()
    return _authorization_out(activated)


@router.get(
    "/missions/{mission_id}/authorization/challenge",
    response_model=ApprovalChallengeOut,
)
async def get_approval_challenge(
    mission_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ApprovalChallengeOut:
    """Return canonical bytes and a readable summary for the external signer."""
    mission = await _load_mission(session, mission_id)
    row = await authorization_for_mission(session, mission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no authorization for this mission")
    if (
        mission.state != MissionState.AWAITING_APPROVAL.value
        or row.status != AuthorizationStatus.PENDING.value
        or row.approval_scheme != ApprovalScheme.USER_ED25519.value
    ):
        raise HTTPException(
            status_code=409,
            detail={"reason_code": "AUTHORIZATION_NOT_PENDING_USER_APPROVAL"},
        )
    if utcnow() >= as_utc(row.expires_at):
        raise HTTPException(
            status_code=409,
            detail={"reason_code": "AUTHORIZATION_EXPIRED"},
        )

    transaction = rebuild_bound_transaction(row)
    signing_key_id = get_settings().demo_approver_signing_key_id
    message = approval_message(
        authorization_id=row.authorization_id,
        mission_id=row.mission_id,
        binding_version=row.binding_version,
        transaction_digest=row.transaction_digest,
        signing_key_id=signing_key_id,
    )
    return ApprovalChallengeOut(
        authorization_id=row.authorization_id,
        mission_id=row.mission_id,
        binding_version=row.binding_version,
        transaction_digest=row.transaction_digest,
        signing_key_id=signing_key_id,
        approval_scheme=ApprovalScheme.USER_ED25519.value,
        approval_message_hex=message.hex(),
        transaction=BoundTransactionSummary(
            merchant=transaction.merchant_id,
            product=transaction.product_id,
            quantity=transaction.quantity,
            amount=transaction.amount_inr,
            currency=transaction.currency,
            expiry=transaction.expires_at,
        ),
    )
