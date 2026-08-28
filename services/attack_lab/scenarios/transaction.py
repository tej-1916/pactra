"""TRANSACTION — the binding, the one-time use, and the expiry window.

    HARD LIMIT EXCEEDED                -> PAYMENT IMPOSSIBLE
    TRANSACTION CHANGED AFTER APPROVAL -> AUTHORIZATION INVALID
    EXPIRED APPROVAL                   -> PAYMENT IMPOSSIBLE
    REPLAYED APPROVAL                  -> PAYMENT IMPOSSIBLE

WHY THE MUTATION ATTACK LOOKS ODD AT FIRST
------------------------------------------
``create_payment_intent`` takes no transaction: the executor rebuilds it from
the authorization's own server-held columns. There is no field through which a
caller could offer a mutated amount, so the HTTP-level attack does not exist to
run. The mutation attack therefore goes one layer down, straight at
``consume_authorization`` with a hand-built ``BoundTransaction`` — the strongest
position an attacker could ever reach, since it assumes they already have
in-process code execution. If the binding holds there, it holds above.

Every bound field is mutated, not just the amount. The digest covers nine, and a
binding proven for one field is a binding proven for one field.
"""

from __future__ import annotations

import uuid
from typing import Any

from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.domain import PolicyOutcome, ReasonCode
from packages.schemas.transaction import BOUND_FIELDS

from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import (
    constraints,
    effect_delta,
    mission_snapshot,
    payment_intents_for,
    run_mission,
)
from services.attack_lab.scenarios.adversaries import OverpricedMerchant
from services.security_kernel.authorization import (
    AuthorizationExpired,
    AuthorizationFailure,
    AuthorizationReplayDetected,
    TransactionBindingFailure,
    consume_authorization,
)

# --------------------------------------------------------------------------- #
# 8. Hard budget / policy bypass
# --------------------------------------------------------------------------- #


async def _budget_setup(context: Any) -> dict[str, Any]:
    return {"census": await context.census()}


async def _budget_execute(context: Any, state: dict[str, Any]) -> Observation:
    limits = constraints(soft_budget_inr=3000, hard_limit_inr=3500)
    # Above the ceiling AND claiming a raised ceiling at the same time, so the
    # DENY has to survive a simultaneous authority attack rather than only an
    # arithmetic one.
    mission_id = await run_mission(
        context, merchants=[OverpricedMerchant(price=9999)], mission_constraints=limits
    )
    snapshot = await mission_snapshot(context, mission_id)
    decision = snapshot["policy_decision"] or {}

    after = await context.census()
    delta = effect_delta(state["census"], after)

    denied = decision.get("decision") == PolicyOutcome.DENY.value
    reason_is_limit = ReasonCode.HARD_LIMIT_EXCEEDED.value in decision.get("reason_codes", [])
    no_authorization = delta["authorizations"] == 0
    no_payment = delta["payment_intents"] == 0
    cancelled = snapshot["state"] == "CANCELLED"

    blocked = denied and reason_is_limit and no_authorization and no_payment
    return Observation(
        blocked=blocked,
        reason_code=ReasonCode.HARD_LIMIT_EXCEEDED.value if reason_is_limit else None,
        invariant_preserved=no_authorization and no_payment,
        observed_effects={
            "hard_limit": decision.get("hard_limit"),
            "requested_amount": decision.get("requested_amount"),
            "policy_decision": decision.get("decision"),
            "policy_reason_codes": decision.get("reason_codes"),
            "authorizations_created": delta["authorizations"],
            "payment_intents_created": delta["payment_intents"],
            "mission_state": snapshot["state"],
            "mission_cancelled": cancelled,
        },
        evidence=(
            f"amount {decision.get('requested_amount')} above ceiling "
            f"{decision.get('hard_limit')}: DENY, and a DENY mints no authorization"
        ),
    )


HARD_BUDGET_BYPASS = AttackScenario(
    id="hard_budget_bypass",
    name="Hard budget / policy bypass",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description=(
        "A merchant offers a 9999 product against a 3500 hard ceiling while "
        "simultaneously claiming a raised ceiling. The decision must be DENY, "
        "and a DENY must produce no authorization and therefore no payment path."
    ),
    target_invariants=(
        "HARD LIMIT EXCEEDED -> PAYMENT IMPOSSIBLE",
        "NO VALID AUTHORIZATION -> NO PAYMENT",
    ),
    expected_reason_code=ReasonCode.HARD_LIMIT_EXCEEDED.value,
    critical=True,
    setup=_budget_setup,
    execute=_budget_execute,
)


# --------------------------------------------------------------------------- #
# 9. Transaction mutation after approval
# --------------------------------------------------------------------------- #

#: One or more different-but-valid values for every bound field. Exhaustive by
#: construction: ``_mutation_execute`` asserts this covers ``BOUND_FIELDS``, so a
#: field added to the digest without a mutator here fails the scenario rather
#: than silently shrinking what is proven.
FIELD_MUTATIONS: dict[str, list[Any]] = {
    "merchant_id": ["attacker-merchant", "merchant_b"],
    "product_id": ["P2"],
    "quantity": [2],
    "amount_inr": [4399, 1],
    "currency": ["USD"],
    "policy_version": ["policy-v2"],
    "offer_version": ["offer-v2"],
    "expires_at": ["+1h"],
    "nonce": ["b" * 64],
}


async def _mutation_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, transaction = await context.authorized_mission(amount_inr=3799)
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "transaction": transaction,
        "census": await context.census(),
    }


async def _mutation_execute(context: Any, state: dict[str, Any]) -> Observation:
    from datetime import timedelta

    authorization_id: uuid.UUID = state["authorization_id"]
    original = state["transaction"]

    missing = sorted(set(BOUND_FIELDS) - set(FIELD_MUTATIONS))
    attempts: list[dict[str, Any]] = []

    for field in BOUND_FIELDS:
        for raw_value in FIELD_MUTATIONS.get(field, []):
            value = original.expires_at + timedelta(hours=1) if raw_value == "+1h" else raw_value
            if value == getattr(original, field):
                continue
            mutated = original.model_copy(update={field: value})
            async with context.sessionmaker() as session:
                try:
                    await consume_authorization(
                        session,
                        authorization_id=authorization_id,
                        transaction=mutated,
                    )
                    await session.commit()
                    attempts.append({"field": field, "refused": False, "reason_code": None})
                except AuthorizationFailure as failure:
                    await session.rollback()
                    attempts.append(
                        {
                            "field": field,
                            "refused": True,
                            "reason_code": failure.reason_code,
                        }
                    )

    binding_failures = [
        a for a in attempts if a["reason_code"] == ReasonCode.TRANSACTION_BINDING_FAILURE.value
    ]
    all_refused = bool(attempts) and all(a["refused"] for a in attempts)
    # Every refusal must be the BINDING refusal specifically. A mutation refused
    # for some other reason would mean the digest was not what stopped it.
    all_binding = len(binding_failures) == len(attempts)

    status = await _status(context, authorization_id)
    unspent = status == AuthorizationStatus.ACTIVE.value

    after = await context.census()
    delta = effect_delta(state["census"], after)
    no_payment = delta["payment_intents"] == 0

    blocked = all_refused and all_binding and unspent and no_payment and not missing
    return Observation(
        blocked=blocked,
        reason_code=(ReasonCode.TRANSACTION_BINDING_FAILURE.value if binding_failures else None),
        invariant_preserved=unspent and no_payment,
        observed_effects={
            "bound_fields": list(BOUND_FIELDS),
            "bound_fields_without_a_mutator": missing,
            "mutations_attempted": len(attempts),
            "mutations_refused": sum(a["refused"] for a in attempts),
            "refused_with_binding_failure": len(binding_failures),
            "fields_that_went_through": [a["field"] for a in attempts if not a["refused"]],
            "authorization_status_after": status,
            "authorization_unspent": unspent,
            "payment_intents_created": delta["payment_intents"],
        },
        evidence=(
            f"all {len(attempts)} single-field mutations across {len(BOUND_FIELDS)} bound "
            "fields refused with TRANSACTION_BINDING_FAILURE; authorization still ACTIVE"
        ),
    )


async def _status(context: Any, authorization_id: uuid.UUID) -> str | None:
    from apps.api.db.models import AuthorizationRow

    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, authorization_id, populate_existing=True)
        return None if row is None else row.status


TRANSACTION_MUTATION = AttackScenario(
    id="transaction_mutation",
    name="Transaction mutation after approval",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description=(
        "An authorization is issued and activated for merchant_a / P1 / 3799 / "
        "INR / qty 1. Every one of the nine bound fields is then mutated in turn "
        "and the mutated transaction is presented to consume_authorization. Each "
        "must be refused with TRANSACTION_BINDING_FAILURE, and the authorization "
        "must remain unspent."
    ),
    target_invariants=(
        "TRANSACTION CHANGED AFTER APPROVAL -> AUTHORIZATION INVALID",
        "NO VALID AUTHORIZATION -> NO PAYMENT",
    ),
    expected_reason_code=ReasonCode.TRANSACTION_BINDING_FAILURE.value,
    critical=True,
    setup=_mutation_setup,
    execute=_mutation_execute,
)


# --------------------------------------------------------------------------- #
# 10. Authorization replay
# --------------------------------------------------------------------------- #


async def _replay_setup(context: Any) -> dict[str, Any]:
    """Spend the authorization ONCE through the real payment path.

    Not by calling ``consume_authorization`` directly: the replay has to be
    replayed against a genuinely consumed authorization, and the way one gets
    consumed in production is a payment request.
    """
    from packages.schemas.capability import payment_executor_capabilities

    from services.payment_executor.intents import create_payment_intent

    mission_id, authorization_id, transaction = await context.authorized_mission()
    async with context.sessionmaker() as session:
        result = await create_payment_intent(
            session,
            capabilities=payment_executor_capabilities(),
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="attack-replay-first",
            provider="fake",
        )
        first_intent_id = result.intent.id
        await session.commit()

    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "transaction": transaction,
        "first_intent_id": first_intent_id,
        "census": await context.census(),
        "intents_before": len(await payment_intents_for(context, mission_id)),
    }


async def _replay_execute(context: Any, state: dict[str, Any]) -> Observation:
    from packages.schemas.capability import payment_executor_capabilities

    from services.payment_executor.intents import create_payment_intent

    mission_id: uuid.UUID = state["mission_id"]
    authorization_id: uuid.UUID = state["authorization_id"]

    outcomes: list[dict[str, Any]] = []

    # (a) Replay through the production path: a SECOND payment request naming
    #     the same authorization with a fresh idempotency key.
    async with context.sessionmaker() as session:
        try:
            await create_payment_intent(
                session,
                capabilities=payment_executor_capabilities(),
                mission_id=mission_id,
                authorization_id=authorization_id,
                idempotency_key="attack-replay-second",
                provider="fake",
            )
            await session.commit()
            outcomes.append({"path": "payment_request", "refused": False, "reason_code": None})
        except Exception as exc:  # noqa: BLE001 - the refusal's identity is the measurement
            await session.rollback()
            outcomes.append(
                {
                    "path": "payment_request",
                    "refused": True,
                    "reason_code": getattr(exc, "reason_code", type(exc).__name__),
                }
            )

    # (b) Replay one layer down, against the kernel primitive itself, with the
    #     exact original transaction. This is the strongest form of the attack.
    async with context.sessionmaker() as session:
        try:
            await consume_authorization(
                session,
                authorization_id=authorization_id,
                transaction=state["transaction"],
            )
            await session.commit()
            outcomes.append(
                {"path": "consume_authorization", "refused": False, "reason_code": None}
            )
        except AuthorizationReplayDetected as replay:
            await session.rollback()
            outcomes.append(
                {
                    "path": "consume_authorization",
                    "refused": True,
                    "reason_code": replay.reason_code,
                }
            )
        except AuthorizationFailure as other:
            await session.rollback()
            outcomes.append(
                {
                    "path": "consume_authorization",
                    "refused": True,
                    "reason_code": other.reason_code,
                }
            )

    intents = await payment_intents_for(context, mission_id)
    after = await context.census()
    delta = effect_delta(state["census"], after)

    all_refused = all(o["refused"] for o in outcomes)
    replay_code = ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value
    correct_code = any(o["reason_code"] == replay_code for o in outcomes)
    one_logical_payment = len(intents) == state["intents_before"] == 1
    # The metric key the replay-success rate is computed from: measured, not
    # asserted. True would mean a replayed approval produced a second payment.
    unauthorized_effect = (not all_refused) or len(intents) > 1

    blocked = all_refused and correct_code and one_logical_payment
    return Observation(
        blocked=blocked,
        reason_code=replay_code
        if correct_code
        else (outcomes[0]["reason_code"] if outcomes else None),
        invariant_preserved=one_logical_payment and delta["payment_intents"] == 0,
        observed_effects={
            "replay_attempts": outcomes,
            "unauthorized_effect": unauthorized_effect,
            "payment_intents_before": state["intents_before"],
            "payment_intents_after": len(intents),
            "logical_payments": len(intents),
            "provider_payments": len(context.provider.created_payments),
            "authorization_status_after": await _status(context, authorization_id),
            "census_delta": delta,
        },
        evidence=(
            "a consumed authorization was presented twice more and refused both times. "
            "The two refusals come from DIFFERENT controls, which is the point: the "
            "payment path is stopped by the mission-state precondition (the outer half) "
            "before it reaches the kernel, and the kernel primitive itself answers "
            "AUTHORIZATION_REPLAY_DETECTED (the inner half). "
            f"Payment intents unchanged at {len(intents)}"
        ),
    )


AUTHORIZATION_REPLAY = AttackScenario(
    id="authorization_replay",
    name="Authorization replay",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description=(
        "An authorization is consumed once by a real payment request, then "
        "replayed twice: through the payment path with a fresh idempotency key, "
        "and directly against consume_authorization with the exact original "
        "transaction. Both must be refused and no second logical payment may exist."
    ),
    target_invariants=(
        "REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE",
        "SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT",
    ),
    expected_reason_code=ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value,
    critical=True,
    setup=_replay_setup,
    execute=_replay_execute,
)


# --------------------------------------------------------------------------- #
# 11. Stale / expired authorization
# --------------------------------------------------------------------------- #


async def _stale_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, transaction, after_expiry = await context.expired_authorization()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "transaction": transaction,
        "after_expiry": after_expiry,
        "census": await context.census(),
    }


async def _stale_execute(context: Any, state: dict[str, Any]) -> Observation:
    authorization_id: uuid.UUID = state["authorization_id"]

    reason_code: str | None = None
    refused = False
    async with context.sessionmaker() as session:
        try:
            await consume_authorization(
                session,
                authorization_id=authorization_id,
                transaction=state["transaction"],
                now=state["after_expiry"],
            )
            await session.commit()
        except AuthorizationExpired as expired:
            await session.rollback()
            refused, reason_code = True, expired.reason_code
        except AuthorizationFailure as other:
            await session.rollback()
            refused, reason_code = True, other.reason_code

    intents = await payment_intents_for(context, state["mission_id"])
    after = await context.census()
    delta = effect_delta(state["census"], after)
    status = await _status(context, authorization_id)

    correct_code = reason_code == ReasonCode.AUTHORIZATION_EXPIRED.value
    no_payment = len(intents) == 0 and delta["payment_intents"] == 0

    blocked = refused and correct_code and no_payment
    return Observation(
        blocked=blocked,
        reason_code=reason_code,
        invariant_preserved=no_payment,
        observed_effects={
            "refused": refused,
            "expires_at_passed_by_seconds": 1,
            "authorization_status_after": status,
            # The kernel opportunistically demotes a stale row to EXPIRED inside
            # the SAME transaction that refuses the consume, so a caller that
            # rolls back on the refusal — which is what the HTTP layer does, and
            # what this scenario does — discards the demotion along with it. The
            # status column therefore still reads ACTIVE, and that is harmless:
            # the guard is the live `expires_at > :now` predicate in the WHERE
            # clause, evaluated on every attempt, never a cached status.
            "status_column_rolled_back_with_the_refusal": (
                status == AuthorizationStatus.ACTIVE.value
            ),
            "enforced_by": "expires_at > :now predicate, not the status column",
            "payment_intents_after": len(intents),
            "census_delta": delta,
        },
        evidence="consumption past expires_at refused; no PaymentIntent exists",
    )


STALE_AUTHORIZATION = AttackScenario(
    id="stale_authorization",
    name="Stale / expired authorization",
    category=AttackCategory.TRANSACTION,
    severity=Severity.HIGH,
    description=(
        "An authorization is issued and activated with a real 15-minute window, "
        "then presented one second after expires_at. The kernel's "
        "`expires_at > :now` predicate must refuse it; no PaymentIntent may exist."
    ),
    target_invariants=(
        "EXPIRED APPROVAL -> PAYMENT IMPOSSIBLE",
        "NO VALID AUTHORIZATION -> NO PAYMENT",
    ),
    expected_reason_code=ReasonCode.AUTHORIZATION_EXPIRED.value,
    critical=True,
    setup=_stale_setup,
    execute=_stale_execute,
)


# --------------------------------------------------------------------------- #
# 12/13. Version stamps inside the binding
# --------------------------------------------------------------------------- #


def _version_scenario(
    *, scenario_id: str, name: str, field: str, mutated_value: str, description: str
) -> AttackScenario:
    """Build a version-mutation scenario.

    ``policy_version`` and ``offer_version`` are both inside the digest, which is
    what stops an approval being carried across a policy change or an offer edit.
    The two attacks are structurally identical, so they are generated from one
    definition rather than copy-pasted — a copy is a place for the two to drift.
    """

    async def setup(context: Any) -> dict[str, Any]:
        mission_id, authorization_id, transaction = await context.authorized_mission()
        return {
            "mission_id": mission_id,
            "authorization_id": authorization_id,
            "transaction": transaction,
            "census": await context.census(),
        }

    async def execute(context: Any, state: dict[str, Any]) -> Observation:
        mutated = state["transaction"].model_copy(update={field: mutated_value})
        reason_code: str | None = None
        refused = False
        async with context.sessionmaker() as session:
            try:
                await consume_authorization(
                    session,
                    authorization_id=state["authorization_id"],
                    transaction=mutated,
                )
                await session.commit()
            except TransactionBindingFailure as failure:
                await session.rollback()
                refused, reason_code = True, failure.reason_code
            except AuthorizationFailure as other:
                await session.rollback()
                refused, reason_code = True, other.reason_code

        status = await _status(context, state["authorization_id"])
        after = await context.census()
        delta = effect_delta(state["census"], after)
        unspent = status == AuthorizationStatus.ACTIVE.value

        blocked = (
            refused
            and reason_code == ReasonCode.TRANSACTION_BINDING_FAILURE.value
            and unspent
            and delta["payment_intents"] == 0
        )
        return Observation(
            blocked=blocked,
            reason_code=reason_code,
            invariant_preserved=unspent and delta["payment_intents"] == 0,
            observed_effects={
                "mutated_field": field,
                "bound_value": getattr(state["transaction"], field),
                "presented_value": mutated_value,
                "refused": refused,
                "authorization_status_after": status,
                "payment_intents_created": delta["payment_intents"],
            },
            evidence=f"{field} is inside the transaction digest, so changing it invalidates it",
        )

    return AttackScenario(
        id=scenario_id,
        name=name,
        category=AttackCategory.TRANSACTION,
        severity=Severity.HIGH,
        description=description,
        target_invariants=("TRANSACTION CHANGED AFTER APPROVAL -> AUTHORIZATION INVALID",),
        expected_reason_code=ReasonCode.TRANSACTION_BINDING_FAILURE.value,
        setup=setup,
        execute=execute,
    )


POLICY_VERSION_MUTATION = _version_scenario(
    scenario_id="policy_version_mutation",
    name="Policy version mutation",
    field="policy_version",
    mutated_value="policy-v2",
    description=(
        "An authorization approved under policy-v1 is presented against a "
        "transaction stamped policy-v2. An approval must not survive a change to "
        "the ruleset that adjudicated it."
    ),
)

OFFER_VERSION_MUTATION = _version_scenario(
    scenario_id="offer_version_mutation",
    name="Offer version mutation",
    field="offer_version",
    mutated_value="edited-offer-fingerprint",
    description=(
        "An authorization bound to one offer fingerprint is presented against a "
        "transaction carrying a different one — the shape a merchant editing its "
        "offer after approval would take."
    ),
)


SCENARIOS = (
    HARD_BUDGET_BYPASS,
    TRANSACTION_MUTATION,
    AUTHORIZATION_REPLAY,
    STALE_AUTHORIZATION,
    POLICY_VERSION_MUTATION,
    OFFER_VERSION_MUTATION,
)
