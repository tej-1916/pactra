"""Shared plumbing for scenarios. Reads and drives; never relaxes a control.

Every function here either calls a real PACTRA entry point (``Orchestrator.run``,
``create_payment_intent``, ``drain``) or reads persisted state back out so a
scenario can compare a before-census to an after-census. Nothing constructs a
privileged object by hand, and nothing writes to a security column except the
audit-tamper helpers, which corrupt rows DIRECTLY — the way an attacker holding
database access would, and the way the Phase 5 corruption tests already do.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from apps.api.db.models import (
    AuditEventRow,
    AuthorizationRow,
    Mission,
    Offer,
    PaymentIntentRow,
    PolicyDecisionRow,
)
from packages.schemas.domain import CreateMissionRequest, MissionConstraints
from sqlalchemy import select

from services.agent_orchestrator.orchestrator import Orchestrator
from services.attack_lab.context import ScenarioContext
from services.audit_ledger.ledger import list_events
from services.payment_executor.worker import drain, run_once

#: Constraints the Phase 1 demo and the whole test suite already use, so a
#: scenario's starting conditions are the system's ordinary ones.
DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "category": "wireless_earbuds",
    "soft_budget_inr": 4000,
    "hard_limit_inr": 4500,
    "min_rating": 4.2,
    "currency": "INR",
}


def constraints(**overrides: Any) -> MissionConstraints:
    values = dict(DEFAULT_CONSTRAINTS)
    values.update(overrides)
    return MissionConstraints(**values)


async def run_mission(
    context: ScenarioContext,
    *,
    merchants: list[Any],
    mission_constraints: MissionConstraints | None = None,
    quantity: int = 1,
    raw_query: str | None = None,
) -> uuid.UUID:
    """Drive a full mission through the REAL orchestrator.

    Every kernel stage runs: transport identity, ingress provenance, the
    authority lattice over merchant claims, normalization, ranking, the
    deterministic policy engine, transaction binding, and authorization
    issuance. A scenario cannot skip a stage, because there is no argument that
    would let it.
    """
    async with context.sessionmaker() as session:
        mission = await Orchestrator(merchants=merchants).run(
            session,
            CreateMissionRequest(
                raw_query=raw_query,
                quantity=quantity,
                constraints=mission_constraints or constraints(),
            ),
        )
        mission_id = mission.id
        await session.commit()
    return mission_id


async def mission_snapshot(context: ScenarioContext, mission_id: uuid.UUID) -> dict[str, Any]:
    """Everything the mission left behind, as plain data.

    Used for the differential comparisons: two missions that differ only in
    untrusted text must produce equal snapshots, and equality over a dict is a
    stronger statement than equality over a handful of hand-picked fields.
    """
    async with context.sessionmaker() as session:
        mission = await session.get(Mission, mission_id)
        offers = list(
            (
                await session.execute(
                    select(Offer).where(Offer.mission_id == mission_id).order_by(Offer.rank)
                )
            )
            .scalars()
            .all()
        )
        decision = (
            await session.execute(
                select(PolicyDecisionRow)
                .where(PolicyDecisionRow.mission_id == mission_id)
                .order_by(PolicyDecisionRow.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        authorization = (
            await session.execute(
                select(AuthorizationRow)
                .where(AuthorizationRow.mission_id == mission_id)
                .order_by(AuthorizationRow.issued_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        events = await list_events(session, mission_id)

        return {
            "state": None if mission is None else mission.state,
            "offers": [
                {
                    "merchant_id": offer.merchant_id,
                    "claimed_merchant_id": (offer.raw or {}).get("claimed_merchant_id"),
                    "merchant_trust": offer.merchant_trust,
                    "product_id": offer.product_id,
                    "amount_inr": offer.amount_inr,
                    "currency": offer.currency,
                    "rating": offer.rating,
                    "valid": offer.valid,
                    "rejection_reasons": list(offer.rejection_reasons or []),
                    "rank": offer.rank,
                    "offer_version": offer.offer_version,
                }
                for offer in offers
            ],
            "policy_decision": (
                None
                if decision is None
                else {
                    "decision": decision.decision,
                    "policy_version": decision.policy_version,
                    "reason_codes": list(decision.reason_codes or []),
                    "requested_amount": decision.requested_amount,
                    "soft_budget": decision.soft_budget,
                    "hard_limit": decision.hard_limit,
                }
            ),
            "authorization": (
                None
                if authorization is None
                else {
                    "status": authorization.status,
                    "bound_amount_inr": authorization.bound_amount_inr,
                    "bound_merchant_id": authorization.bound_merchant_id,
                    "bound_product_id": authorization.bound_product_id,
                    "bound_currency": authorization.bound_currency,
                    "policy_version": authorization.policy_version,
                }
            ),
            "event_types": [event.event_type for event in events],
            "security_violations": [
                event.payload.get("reason_code")
                for event in events
                if event.event_type == "SECURITY_VIOLATION"
            ],
        }


async def audit_text(context: ScenarioContext, mission_id: uuid.UUID) -> str:
    """Every audit payload for a mission, serialized.

    Searched for the injection canary. This is the WEAKER of the two
    prompt-injection checks — it proves one particular string did not leak, not
    that untrusted text has no influence — so it is always paired with the
    differential comparison rather than standing alone.
    """
    async with context.sessionmaker() as session:
        events = await list_events(session, mission_id)
        return json.dumps(
            [
                {"type": event.event_type, "actor": event.actor, "payload": event.payload}
                for event in events
            ],
            default=str,
        )


async def persisted_offer_text(context: ScenarioContext, mission_id: uuid.UUID) -> str:
    """Every persisted offer row for a mission, serialized."""
    async with context.sessionmaker() as session:
        offers = (
            (await session.execute(select(Offer).where(Offer.mission_id == mission_id)))
            .scalars()
            .all()
        )
        return json.dumps(
            [
                {
                    "title": offer.title,
                    "merchant_name": offer.merchant_name,
                    "product_id": offer.product_id,
                    "raw": offer.raw,
                }
                for offer in offers
            ],
            default=str,
        )


async def authorization_row(
    context: ScenarioContext, authorization_id: uuid.UUID
) -> dict[str, Any] | None:
    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, authorization_id, populate_existing=True)
        if row is None:
            return None
        return {
            "status": row.status,
            "consumed_at": None if row.consumed_at is None else str(row.consumed_at),
            "bound_amount_inr": row.bound_amount_inr,
            "bound_merchant_id": row.bound_merchant_id,
        }


async def payment_intents_for(
    context: ScenarioContext, mission_id: uuid.UUID
) -> list[dict[str, Any]]:
    async with context.sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(PaymentIntentRow).where(PaymentIntentRow.mission_id == mission_id)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": str(row.id),
                "state": row.state,
                "provider": row.provider,
                "provider_payment_id": row.provider_payment_id,
                "amount_inr": row.amount_inr,
                "currency": row.currency,
                "attempts": row.attempts,
                "idempotency_key": row.idempotency_key,
                "last_reason_code": row.last_reason_code,
            }
            for row in rows
        ]


async def payment_intent_state(context: ScenarioContext, intent_id: uuid.UUID) -> str | None:
    async with context.sessionmaker() as session:
        row = await session.get(PaymentIntentRow, intent_id, populate_existing=True)
        return None if row is None else row.state


async def drain_worker(
    context: ScenarioContext, *, provider: Any = None, max_events: int = 20
) -> list[str]:
    """Run the REAL outbox worker until the queue is empty.

    The worker is a separate process in production; here it is the same
    coroutine that process runs. It is the only path to a provider, which is why
    a scenario that wants a provider call has to go through it rather than
    calling the adapter itself.
    """
    outcomes = await drain(
        context.sessionmaker,
        provider=provider or context.provider,
        worker_id="attack-lab-worker",
        max_events=max_events,
    )
    return [outcome.event_type or "" for outcome in outcomes if outcome.event_id is not None]


async def worker_step(context: ScenarioContext, *, provider: Any = None) -> str | None:
    """Process EXACTLY ONE outbox event, or return None if the queue is idle.

    ``drain`` keeps going until the queue empties, and several handlers enqueue
    a follow-up event as part of doing their job — a lost create response
    enqueues its own reconciliation. A scenario that wants to observe the
    INTERMEDIATE state (uncertainty, before reconciliation resolves it) has to
    step one event at a time, or the drain will have already resolved the thing
    it meant to look at.
    """
    outcome = await run_once(
        context.sessionmaker,
        provider=provider or context.provider,
        worker_id="attack-lab-worker",
    )
    return outcome.event_type


async def audit_events(context: ScenarioContext, mission_id: uuid.UUID) -> list[AuditEventRow]:
    async with context.sessionmaker() as session:
        return await list_events(session, mission_id)


def effect_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    """Per-table change between two censuses.

    Reported alongside every "the attack was blocked" claim. A delta of zero
    across payment intents, authorizations and provider payments is the evidence
    that nothing moved; the word "blocked" on its own is not.
    """
    return {key: after.get(key, 0) - value for key, value in before.items()}
