"""Deterministic policy engine.

This is plain Python — never an LLM prompt. Given validated constraints and the
best ranked offer, it returns ALLOW / REQUIRE_APPROVAL / DENY with explicit
reason codes. The engine enforces the hard ceiling as an absolute invariant:
anything above the hard limit is DENY, full stop.

The offer is the coupled ``ProvenancedOffer``; the engine reads merchant values
via `.value`, so it can never act on a value stripped of its provenance/taint.
"""

from __future__ import annotations

from packages.schemas.domain import (
    MissionConstraints,
    PolicyDecision,
    PolicyOutcome,
    ReasonCode,
)
from packages.schemas.kernel import ProvenancedOffer

# Version of this deterministic ruleset. Every decision is stamped with it and
# the stamp is bound into the transaction digest (Phase 3), so an approval taken
# under one policy version can never be consumed under another. Bump this
# whenever the rules below change in a way that could alter an outcome.
POLICY_VERSION = "policy-v1"


def evaluate(
    constraints: MissionConstraints,
    best: ProvenancedOffer | None,
    quantity: int,
) -> PolicyDecision:
    soft = constraints.soft_budget_inr
    hard = constraints.hard_limit_inr

    if best is None:
        return PolicyDecision(
            decision=PolicyOutcome.DENY,
            policy_version=POLICY_VERSION,
            reason_codes=[ReasonCode.NO_VALID_OFFERS],
            requested_amount=None,
            soft_budget=soft,
            hard_limit=hard,
            selected_offer_id=None,
        )

    amount = best.amount_inr.value * quantity
    reasons: list[ReasonCode] = []

    # Absolute ceiling: never negotiable.
    if amount > hard:
        return PolicyDecision(
            decision=PolicyOutcome.DENY,
            policy_version=POLICY_VERSION,
            reason_codes=[ReasonCode.HARD_LIMIT_EXCEEDED],
            requested_amount=amount,
            soft_budget=soft,
            hard_limit=hard,
            selected_offer_id=best.offer_id,
        )

    if amount > soft:
        reasons.append(ReasonCode.SOFT_BUDGET_EXCEEDED)
        outcome = PolicyOutcome.REQUIRE_APPROVAL
    else:
        reasons.append(ReasonCode.WITHIN_LIMITS)
        outcome = PolicyOutcome.ALLOW

    return PolicyDecision(
        decision=outcome,
        policy_version=POLICY_VERSION,
        reason_codes=reasons,
        requested_amount=amount,
        soft_budget=soft,
        hard_limit=hard,
        selected_offer_id=best.offer_id,
    )
