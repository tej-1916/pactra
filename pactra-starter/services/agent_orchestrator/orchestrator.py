"""Mission orchestrator — vertical slice through the security kernel.

Drives a mission deterministically through:
  CREATED -> INTENT_PARSED -> DISCOVERING -> OFFERS_RECEIVED
  -> OFFERS_NORMALIZED -> RANKED -> POLICY_CHECKED
  -> {AWAITING_APPROVAL | CANCELLED | (stays POLICY_CHECKED on ALLOW)}

Merchant identity is established by the transport before any payload is read,
and each merchant's response is carried as an ``AuthenticatedQuote`` so the
authenticated identity is never lost by flattening responses together. Merchant
responses themselves are untrusted: normalization tags every merchant-derived
value with provenance/taint, and an offer whose payload claims a different
merchant_id than the one that was authenticated is rejected and recorded as a
SECURITY_VIOLATION.

Before the buyer agent proposes a purchase, the capability firewall enforces
`payment.propose`; the privileged `payment.execute` capability is denied, so the
(future) executor is unreachable from here.

Every transition is validated by the state machine and recorded as an
append-only audit event. No LLM, no payment execution, no approval token yet.
"""

from __future__ import annotations

import uuid

from apps.api.db.models import (
    Mission,
    MissionConstraintsRow,
    Offer,
    PolicyDecisionRow,
)
from packages.schemas.capability import Capability
from packages.schemas.domain import (
    CreateMissionRequest,
    EventType,
    MissionState,
    PolicyOutcome,
    ReasonCode,
)
from packages.schemas.invariants import require
from packages.schemas.kernel import ProvenancedOffer
from packages.schemas.merchant import AuthenticatedQuote
from packages.schemas.provenance import untrusted
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_orchestrator.merchants.base import MerchantAgent
from services.agent_orchestrator.merchants.mock_merchants import default_merchants
from services.agent_orchestrator.merchants.transport import MerchantTransport
from services.agent_orchestrator.state_machine import assert_transition
from services.audit_ledger.ledger import append_event
from services.policy_engine import engine
from services.policy_engine.normalization import normalize_offers
from services.policy_engine.ranking import rank_offers
from services.security_kernel.authority import AuthorityEscalation
from services.security_kernel.capability import enforce
from services.security_kernel.capability_registry import capabilities_for
from services.security_kernel.ingress import protected_policy_values
from services.security_kernel.merchant_registry import MerchantRegistry
from services.security_kernel.policy_register import ProtectedPolicyRegister

ACTOR = "orchestrator"
BUYER_PRINCIPAL = "buyer-agent"


class Orchestrator:
    def __init__(
        self,
        merchants: list[MerchantAgent] | None = None,
        registry: MerchantRegistry | None = None,
    ) -> None:
        self.merchants: list[MerchantAgent] = merchants or default_merchants()
        # The transport owns merchant identity; the registry owns merchant trust.
        self.transport = MerchantTransport(registry)

    async def _transition(
        self,
        session: AsyncSession,
        mission: Mission,
        target: MissionState,
        event_type: EventType,
        actor: str = ACTOR,
        payload: dict | None = None,
    ) -> None:
        assert_transition(MissionState(mission.state), target)
        mission.state = target.value
        await session.flush()
        await append_event(
            session,
            mission_id=mission.id,
            event_type=event_type,
            actor=actor,
            payload=payload or {},
        )

    async def run(self, session: AsyncSession, request: CreateMissionRequest) -> Mission:
        c = request.constraints

        # CREATED
        mission = Mission(
            id=uuid.uuid4(),
            raw_query=request.raw_query,
            quantity=request.quantity,
            state=MissionState.CREATED.value,
        )
        session.add(mission)
        await session.flush()
        await append_event(
            session,
            mission_id=mission.id,
            event_type=EventType.MISSION_CREATED,
            actor=ACTOR,
            payload={"raw_query": request.raw_query, "quantity": request.quantity},
        )

        # INTENT_PARSED (constraints persisted)
        session.add(
            MissionConstraintsRow(
                mission_id=mission.id,
                category=c.category,
                soft_budget_inr=c.soft_budget_inr,
                hard_limit_inr=c.hard_limit_inr,
                min_rating=c.min_rating,
                currency=c.currency,
                allowed_merchants=c.allowed_merchants,
                blocked_merchants=c.blocked_merchants,
                min_merchant_trust=c.min_merchant_trust,
            )
        )
        await self._transition(
            session,
            mission,
            MissionState.INTENT_PARSED,
            EventType.INTENT_PARSED,
            payload={"constraints": c.model_dump(mode="json")},
        )

        # DISCOVERING. Identity is established by the transport from the
        # server-side adapter registration, before any merchant payload is read.
        contexts = [self.transport.connect(m) for m in self.merchants]
        await self._transition(
            session,
            mission,
            MissionState.DISCOVERING,
            EventType.DISCOVERY_STARTED,
            payload={
                "merchants": [
                    {
                        "merchant_id": ctx.merchant_id,
                        "auth_method": ctx.identity.auth_method.value,
                        "known": ctx.record.known,
                    }
                    for ctx in contexts
                ]
            },
        )

        # Query merchants (untrusted responses). Each response stays bound to the
        # authenticated merchant that produced it — responses are never flattened
        # into one anonymous list, which is what previously lost the identity.
        quotes: list[AuthenticatedQuote] = self.transport.collect(
            self.merchants, c, request.quantity
        )
        raw_offer_count = sum(len(q.offers) for q in quotes)

        await self._transition(
            session,
            mission,
            MissionState.OFFERS_RECEIVED,
            EventType.OFFERS_RECEIVED,
            payload={"raw_offer_count": raw_offer_count},
        )

        # RUNTIME AUTHORITY ENFORCEMENT.
        # User policy is held at USER_POLICY authority. Merchants may try
        # to influence it via `claims`; every claim is adjudicated through the
        # authority lattice. A merchant (MERCHANT_DATA) write to a protected field
        # raises AuthorityEscalation, the mutation is blocked, the authoritative
        # value is preserved, and a SECURITY_VIOLATION is recorded.
        protected = protected_policy_values(c)
        register = ProtectedPolicyRegister(protected)
        for quote in quotes:
            # The claim's source authority is bound to the AUTHENTICATED merchant,
            # so a merchant cannot attribute its claim to somebody else.
            claim_source = f"merchant:{quote.context.merchant_id}"
            for raw in quote.offers:
                for field, attempted in raw.claims.items():
                    if not register.is_protected(field):
                        continue
                    incoming = untrusted(attempted, source=claim_source)
                    try:
                        register.apply(field, incoming)
                    except AuthorityEscalation as esc:
                        await append_event(
                            session,
                            mission_id=mission.id,
                            event_type=EventType.SECURITY_VIOLATION,
                            actor="security-kernel",
                            payload={
                                "reason_code": esc.reason_code,
                                "field": esc.field,
                                "attempted_value": attempted,
                                "source_authority": esc.source.name,
                                "target_authority": esc.target.name,
                                "merchant_id": quote.context.merchant_id,
                                "claimed_merchant_id": raw.merchant_id,
                            },
                        )
        # Protected values are unchanged by merchant claims. This is an explicit
        # invariant, not an `assert`: assertions vanish under `python -O`.
        for field, original in protected.items():
            require(
                register.get(field).value == original.value,
                "policy.protected_value_immutable",
                f"protected policy field '{field}' was mutated by a lower authority",
            )

        # Normalize -> coupled ProvenancedOffer (description dropped at ingress).
        normalized: list[ProvenancedOffer] = normalize_offers(quotes, c)
        # Persist the DTO projection; the coupled representation stays in-kernel.
        for norm in normalized:
            dto = norm.to_normalized()
            session.add(
                Offer(
                    id=dto.offer_id,
                    mission_id=mission.id,
                    merchant_id=dto.merchant_id,
                    merchant_name=dto.merchant_name,
                    merchant_trust=dto.merchant_trust,
                    product_id=dto.product_id,
                    title=dto.title,
                    amount_inr=dto.amount_inr,
                    currency=dto.currency,
                    rating=dto.rating,
                    in_stock=dto.in_stock,
                    offered_at=dto.offered_at,
                    valid=dto.valid,
                    rejection_reasons=[r.value for r in dto.rejection_reasons],
                    rank=None,
                    raw={
                        "claimed_merchant_id": dto.claimed_merchant_id,
                        "provenance": {
                            k: v.model_dump(mode="json") for k, v in dto.provenance.items()
                        },
                    },
                )
            )

        # IDENTITY SPOOF DETECTION. An offer whose payload claimed a different
        # merchant_id than the transport authenticated is already rejected by
        # normalization; record it as a security violation in the audit chain.
        for norm in normalized:
            if not norm.identity_mismatch:
                continue
            await append_event(
                session,
                mission_id=mission.id,
                event_type=EventType.SECURITY_VIOLATION,
                actor="security-kernel",
                payload={
                    "reason_code": ReasonCode.MERCHANT_IDENTITY_MISMATCH.value,
                    "authenticated_merchant_id": norm.merchant_id.value,
                    "claimed_merchant_id": norm.claimed_merchant_id.value,
                    "offer_id": str(norm.offer_id),
                    "rejected": True,
                },
            )
            require(
                norm.valid is False,
                "offer.identity_mismatch_rejected",
                f"offer {norm.offer_id} spoofed an identity but was not rejected",
            )

        tainted_fields = sorted(
            {k for o in normalized for k, m in o.meta_map().items() if m.tainted}
        )
        await self._transition(
            session,
            mission,
            MissionState.OFFERS_NORMALIZED,
            EventType.OFFERS_NORMALIZED,
            payload={
                "valid": sum(o.valid for o in normalized),
                "invalid": sum(not o.valid for o in normalized),
                "tainted_merchant_fields": tainted_fields,
            },
        )

        # RANK (assigns rank to valid offers, persist ranks)
        ranked = rank_offers(normalized)
        rank_by_id = {o.offer_id: o.rank for o in ranked}
        for norm in normalized:
            if norm.offer_id in rank_by_id:
                offer_row = await session.get(Offer, norm.offer_id)
                if offer_row is not None:
                    offer_row.rank = rank_by_id[norm.offer_id]
        await session.flush()
        await self._transition(
            session,
            mission,
            MissionState.RANKED,
            EventType.OFFERS_RANKED,
            payload={
                "ranked": [
                    {
                        "offer_id": str(o.offer_id),
                        "rank": o.rank,
                        "amount_inr": o.amount_inr.value,
                    }
                    for o in ranked
                ]
            },
        )

        # Buyer agent proposes the best offer. Capabilities come from the trusted
        # registry (never from the request). The firewall permits
        # `payment.propose`; the privileged `payment.execute` is denied, so the
        # executor stays unreachable here.
        buyer_caps = capabilities_for(BUYER_PRINCIPAL)
        best = ranked[0] if ranked else None
        if best is not None:
            enforce(buyer_caps, Capability.PAYMENT_PROPOSE)

        # POLICY (deterministic — never an LLM)
        decision = engine.evaluate(c, best, request.quantity)
        session.add(
            PolicyDecisionRow(
                mission_id=mission.id,
                decision=decision.decision.value,
                reason_codes=[r.value for r in decision.reason_codes],
                requested_amount=decision.requested_amount,
                soft_budget=decision.soft_budget,
                hard_limit=decision.hard_limit,
                selected_offer_id=decision.selected_offer_id,
            )
        )
        await self._transition(
            session,
            mission,
            MissionState.POLICY_CHECKED,
            EventType.POLICY_DECISION,
            actor="policy-engine",
            payload=decision.model_dump(mode="json"),
        )

        # Branch on decision
        if decision.decision == PolicyOutcome.REQUIRE_APPROVAL:
            await self._transition(
                session,
                mission,
                MissionState.AWAITING_APPROVAL,
                EventType.APPROVAL_REQUESTED,
                payload={"requested_amount": decision.requested_amount},
            )
        elif decision.decision == PolicyOutcome.DENY:
            await self._transition(
                session,
                mission,
                MissionState.CANCELLED,
                EventType.MISSION_DENIED,
                actor="policy-engine",
                payload={"reason_codes": [r.value for r in decision.reason_codes]},
            )
        # ALLOW: mission stays at POLICY_CHECKED, ready for authorization
        # (transaction binding + approval land in Phase 3). No payment here.

        await session.flush()
        return mission
