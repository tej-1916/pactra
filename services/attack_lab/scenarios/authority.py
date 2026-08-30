"""AUTHORITY — lower-authority data cannot modify higher-authority state.

    LOWER AUTHORITY DATA -> CANNOT MODIFY HIGHER AUTHORITY POLICY
    LLM OUTPUT           -> NEVER AUTHORIZATION
    DENIED CAPABILITY    -> PRIVILEGED EXECUTOR UNREACHABLE

Two different mechanisms are attacked here and they fail differently on purpose:

* The **authority lattice** adjudicates a merchant's *claim* about a protected
  policy field. The attack is data — a ``claims`` map on a merchant payload —
  and the defence is ``merge_keep_higher`` refusing a MERCHANT_DATA write to a
  USER_POLICY field. The escalation is recorded as a SECURITY_VIOLATION and the
  authoritative value is untouched.

* The **capability firewall** adjudicates a *caller's* claim about itself. The
  attack is a forged ``CapabilitySet``, and the defence is ``enforce_registered``
  re-resolving the principal against the server-owned registry and demanding
  equality. This is the check that has to be done that way: ``CapabilitySet`` is
  a plain schema, so validating a presented set against itself would make the
  guard self-certifying — it would approve any set that agreed with itself,
  which every forged set does.
"""

from __future__ import annotations

import uuid
from typing import Any

from packages.schemas.approval import ApprovalScheme
from packages.schemas.capability import Capability
from packages.schemas.domain import PolicyOutcome, ReasonCode
from packages.schemas.provenance import AuthorityLevel

from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import (
    audit_events,
    constraints,
    effect_delta,
    mission_snapshot,
    run_mission,
)
from services.attack_lab.scenarios.adversaries import (
    PolicyMutatingMerchant,
    forged_capability_set,
)
from services.security_kernel.capability import CapabilityDenied

# --------------------------------------------------------------------------- #
# 5. Authority escalation — merchant raises the user's hard limit
# --------------------------------------------------------------------------- #

#: The user's real ceiling. The merchant's offer sits above it and the merchant
#: simultaneously claims a ceiling of 999999. If the claim were honoured the
#: purchase would be permitted, so the DENY is not incidental to the attack.
HARD_LIMIT = 3000
MERCHANT_PRICE = 3499


async def _escalation_setup(context: Any) -> dict[str, Any]:
    return {"census": await context.census()}


async def _escalation_execute(context: Any, state: dict[str, Any]) -> Observation:
    limits = constraints(soft_budget_inr=2500, hard_limit_inr=HARD_LIMIT)
    mission_id = await run_mission(
        context,
        merchants=[PolicyMutatingMerchant(price=MERCHANT_PRICE)],
        mission_constraints=limits,
    )
    snapshot = await mission_snapshot(context, mission_id)
    events = await audit_events(context, mission_id)

    escalations = [
        event.payload
        for event in events
        if event.event_type == "SECURITY_VIOLATION"
        and event.payload.get("reason_code") == ReasonCode.AUTHORITY_ESCALATION.value
    ]
    attacked_fields = sorted({str(payload.get("field")) for payload in escalations})

    decision = snapshot["policy_decision"] or {}
    # The authoritative limit is what the decision was actually adjudicated
    # against — read from the recorded decision, not from the request we sent.
    limit_held = decision.get("hard_limit") == HARD_LIMIT
    denied = decision.get("decision") == PolicyOutcome.DENY.value
    reason_is_limit = ReasonCode.HARD_LIMIT_EXCEEDED.value in decision.get("reason_codes", [])

    after = await context.census()
    delta = effect_delta(state["census"], after)
    no_authorization = delta["authorizations"] == 0
    no_payment = delta["payment_intents"] == 0

    # `reason_is_limit` is required, not merely computed: a DENY for some other
    # reason would mean the hard ceiling was not what refused the purchase, and
    # this scenario exists to prove the ceiling held.
    blocked = (
        bool(escalations)
        and limit_held
        and denied
        and reason_is_limit
        and no_authorization
        and no_payment
    )
    return Observation(
        blocked=blocked,
        reason_code=(ReasonCode.AUTHORITY_ESCALATION.value if escalations else None),
        invariant_preserved=limit_held and no_authorization and no_payment,
        observed_effects={
            "escalation_attempts_recorded": len(escalations),
            "protected_fields_attacked": attacked_fields,
            "claimed_hard_limit": 999999,
            "hard_limit_used_by_policy": decision.get("hard_limit"),
            "policy_decision": decision.get("decision"),
            "policy_reason_codes": decision.get("reason_codes"),
            "denied_for_exceeding_the_hard_limit": reason_is_limit,
            "source_authority": sorted({str(p.get("source_authority")) for p in escalations}),
            "target_authority": sorted({str(p.get("target_authority")) for p in escalations}),
            "authorizations_created": delta["authorizations"],
            "payment_intents_created": delta["payment_intents"],
        },
        evidence=(
            f"merchant claimed hard_limit_inr=999999; policy adjudicated against "
            f"{decision.get('hard_limit')} and returned {decision.get('decision')}"
        ),
    )


AUTHORITY_ESCALATION_SCENARIO = AttackScenario(
    id="authority_escalation",
    name="Authority escalation — merchant raises the user's hard limit",
    category=AttackCategory.AUTHORITY,
    severity=Severity.CRITICAL,
    description=(
        "A merchant (MERCHANT_DATA authority) claims hard_limit_inr = 999999 "
        "against a user policy (USER_POLICY authority) of 3000, while offering a "
        "3499 product. Honouring the claim would permit the purchase, so the DENY "
        "is load-bearing rather than incidental."
    ),
    target_invariants=(
        "LOWER AUTHORITY DATA -> CANNOT MODIFY HIGHER AUTHORITY POLICY",
        "HARD LIMIT EXCEEDED -> PAYMENT IMPOSSIBLE",
    ),
    expected_reason_code=ReasonCode.AUTHORITY_ESCALATION.value,
    critical=True,
    setup=_escalation_setup,
    execute=_escalation_execute,
)


# --------------------------------------------------------------------------- #
# 6. Policy mutation — the rest of the protected register
# --------------------------------------------------------------------------- #


async def _policy_mutation_setup(context: Any) -> dict[str, Any]:
    return {"census": await context.census()}


async def _policy_mutation_execute(context: Any, state: dict[str, Any]) -> Observation:
    # `merchant_b` is BLOCKED and the trust floor excludes it. Its claims try to
    # allow-list itself, empty the block-list, drop the trust floor and the
    # rating floor, and switch the currency. Every one of those widens the
    # ground it is judged on.
    limits = constraints(
        blocked_merchants=["merchant_b"],
        min_merchant_trust=0.9,
        min_rating=4.5,
    )
    mission_id = await run_mission(
        context, merchants=[PolicyMutatingMerchant()], mission_constraints=limits
    )
    snapshot = await mission_snapshot(context, mission_id)
    events = await audit_events(context, mission_id)

    escalations = [
        event.payload
        for event in events
        if event.event_type == "SECURITY_VIOLATION"
        and event.payload.get("reason_code") == ReasonCode.AUTHORITY_ESCALATION.value
    ]
    attacked_fields = sorted({str(payload.get("field")) for payload in escalations})

    # Every protected field the merchant claimed must appear as a refused
    # escalation. A claim silently ignored (rather than refused and recorded)
    # would leave no evidence that the lattice adjudicated it at all.
    claimed = set(PolicyMutatingMerchant().claims)
    covered = claimed.issubset(set(attacked_fields))

    offers = snapshot["offers"]
    reasons = {reason for offer in offers for reason in offer["rejection_reasons"]}
    still_blocked = ReasonCode.BLOCKED_MERCHANT.value in reasons
    trust_floor_held = ReasonCode.MERCHANT_TRUST_TOO_LOW.value in reasons
    all_rejected = bool(offers) and all(not offer["valid"] for offer in offers)

    after = await context.census()
    delta = effect_delta(state["census"], after)

    blocked = (
        bool(escalations)
        and covered
        and still_blocked
        and all_rejected
        and delta["authorizations"] == 0
    )
    return Observation(
        blocked=blocked,
        reason_code=ReasonCode.AUTHORITY_ESCALATION.value if escalations else None,
        invariant_preserved=blocked,
        observed_effects={
            "protected_fields_claimed": sorted(claimed),
            "protected_fields_refused": attacked_fields,
            "every_claim_refused": covered,
            "merchant_still_blocked": still_blocked,
            "trust_floor_still_enforced": trust_floor_held,
            "offer_rejection_reasons": sorted(reasons),
            "merchant_authority": AuthorityLevel.MERCHANT_DATA.name,
            "policy_authority": AuthorityLevel.USER_POLICY.name,
            "authorizations_created": delta["authorizations"],
        },
        evidence=(
            f"{len(attacked_fields)} protected policy fields claimed by a merchant, "
            "all refused; the block-list and trust floor still applied"
        ),
    )


POLICY_MUTATION = AttackScenario(
    id="policy_mutation",
    name="Policy mutation — merchant rewrites the protected register",
    category=AttackCategory.AUTHORITY,
    severity=Severity.CRITICAL,
    description=(
        "A blocked, low-trust merchant claims allowed_merchants, "
        "blocked_merchants, min_merchant_trust, min_rating, currency and both "
        "budgets. Every claim must raise AUTHORITY_ESCALATION, leave the "
        "authoritative value untouched, and be recorded."
    ),
    target_invariants=(
        "LOWER AUTHORITY DATA -> CANNOT MODIFY HIGHER AUTHORITY POLICY",
        "MERCHANT CONTENT -> NEVER SYSTEM AUTHORITY",
    ),
    expected_reason_code=ReasonCode.AUTHORITY_ESCALATION.value,
    critical=True,
    setup=_policy_mutation_setup,
    execute=_policy_mutation_execute,
)


# --------------------------------------------------------------------------- #
# 7. Capability escalation — a forged CapabilitySet
# --------------------------------------------------------------------------- #


async def _capability_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, transaction = await context.authorized_mission()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "census": await context.census(),
    }


async def _capability_execute(context: Any, state: dict[str, Any]) -> Observation:
    from services.payment_executor.intents import create_payment_intent
    from services.security_kernel.authorization import issue_authorization

    mission_id: uuid.UUID = state["mission_id"]
    authorization_id: uuid.UUID = state["authorization_id"]

    attempts: list[dict[str, Any]] = []

    async def attempt(label: str, capability_set: Any, coroutine_factory: Any) -> None:
        async with context.sessionmaker() as session:
            try:
                await coroutine_factory(session, capability_set)
                await session.commit()
                attempts.append({"attempt": label, "denied": False, "reason_code": None})
            except CapabilityDenied as denied:
                await session.rollback()
                attempts.append(
                    {"attempt": label, "denied": True, "reason_code": denied.reason_code}
                )
            except Exception as other:  # noqa: BLE001 - a non-capability refusal is not a pass
                await session.rollback()
                attempts.append(
                    {
                        "attempt": label,
                        "denied": False,
                        "reason_code": type(other).__name__,
                    }
                )

    async def request_payment(session: Any, capability_set: Any) -> None:
        await create_payment_intent(
            session,
            capabilities=capability_set,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=f"attack-cap-{len(attempts)}",
            provider="fake",
        )

    async def mint_authorization(session: Any, capability_set: Any) -> None:
        await issue_authorization(
            session,
            capabilities=capability_set,
            mission_id=mission_id,
            transaction=context.bound_transaction(),
            approval_scheme=ApprovalScheme.POLICY_AUTO,
        )

    # (a) The buyer agent — what an LLM acts through — simply asserts the
    #     capability it is denied.
    await attempt(
        "buyer_agent_claims_payment_execute",
        forged_capability_set("buyer-agent", allow={Capability.PAYMENT_EXECUTE}),
        request_payment,
    )
    # (b) The buyer agent asserts the issuance capability: LLM OUTPUT -> NEVER
    #     AUTHORIZATION has to be structural, not conventional.
    await attempt(
        "buyer_agent_claims_authorization_issue",
        forged_capability_set("buyer-agent", allow={Capability.AUTHORIZATION_ISSUE}),
        mint_authorization,
    )
    # (c) An unregistered principal invents itself. Default-deny must apply.
    await attempt(
        "unknown_principal_claims_payment_execute",
        forged_capability_set("totally-legitimate-service", allow={Capability.PAYMENT_EXECUTE}),
        request_payment,
    )
    # (d) The REAL executor principal, with one extra capability bolted on. The
    #     presented set must EQUAL the registry's, so a superset is refused —
    #     this is what stops a caller widening a legitimate principal.
    await attempt(
        "executor_principal_with_extra_capability",
        forged_capability_set(
            "payment-executor",
            allow={
                Capability.PAYMENT_EXECUTE,
                Capability.PAYMENT_PROPOSE,
                Capability.POLICY_MODIFY,
            },
            deny={
                Capability.AUTHORIZATION_ISSUE,
                Capability.REFUND_EXECUTE,
                Capability.POLICY_MODIFY,
                Capability.MERCHANT_MODIFY,
            },
        ),
        request_payment,
    )
    # (e) The executor principal with its DENY list emptied — an attacker's most
    #     natural forgery, since deny is what stands between it and the rest.
    await attempt(
        "executor_principal_with_empty_deny",
        forged_capability_set(
            "payment-executor",
            allow={Capability.PAYMENT_EXECUTE, Capability.PAYMENT_PROPOSE},
            deny=set(),
        ),
        request_payment,
    )

    after = await context.census()
    delta = effect_delta(state["census"], after)
    authorization = await _authorization_status(context, authorization_id)

    all_denied = all(entry["denied"] for entry in attempts)
    nothing_created = delta["payment_intents"] == 0 and delta["authorizations"] == 0
    authorization_unspent = authorization == "ACTIVE"

    blocked = all_denied and nothing_created and authorization_unspent
    return Observation(
        blocked=blocked,
        reason_code=ReasonCode.CAPABILITY_DENIED.value if all_denied else None,
        invariant_preserved=nothing_created and authorization_unspent,
        observed_effects={
            "forged_capability_attempts": attempts,
            "all_denied": all_denied,
            "payment_intents_created": delta["payment_intents"],
            "authorizations_created": delta["authorizations"],
            "authorization_status_after": authorization,
        },
        evidence=(
            f"{len(attempts)} forged capability sets refused by re-resolution against "
            "the server-owned registry; no intent created, authorization unspent"
        ),
    )


async def _authorization_status(context: Any, authorization_id: uuid.UUID) -> str | None:
    from apps.api.db.models import AuthorizationRow

    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, authorization_id, populate_existing=True)
        return None if row is None else row.status


CAPABILITY_ESCALATION = AttackScenario(
    id="capability_escalation",
    name="Capability escalation — forged CapabilitySet",
    category=AttackCategory.AUTHORITY,
    severity=Severity.CRITICAL,
    description=(
        "Five forged capability sets are presented at the two privileged "
        "boundaries: the buyer agent claiming payment.execute and "
        "authorization.issue, an invented principal, the real executor principal "
        "with an extra capability, and the executor with its deny list emptied. "
        "All must be refused by re-resolution against the server-owned registry."
    ),
    target_invariants=(
        "DENIED CAPABILITY -> PRIVILEGED EXECUTOR UNREACHABLE",
        "LLM OUTPUT -> NEVER AUTHORIZATION",
        "NO VALID AUTHORIZATION -> NO PAYMENT",
    ),
    expected_reason_code=ReasonCode.CAPABILITY_DENIED.value,
    critical=True,
    setup=_capability_setup,
    execute=_capability_execute,
)


SCENARIOS = (
    AUTHORITY_ESCALATION_SCENARIO,
    POLICY_MUTATION,
    CAPABILITY_ESCALATION,
)
