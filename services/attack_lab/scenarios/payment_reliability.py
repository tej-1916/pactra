"""PAYMENT_RELIABILITY — at most one logical payment, and one provider payment.

    SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT

The measurement everywhere in this module is a COUNT, not a status. "The retry
was handled correctly" is a claim; "the provider holds exactly one payment for
this idempotency key, and exactly one payment_intents row exists" is evidence.
``FakePaymentProvider.created_payments`` is keyed on the idempotency key, so the
count is answerable exactly.

The timeout-after-create scenario is the CRITICAL one, and it is the reason
``PROVIDER_PENDING`` exists. The provider records a payment and *then* the
response is lost. From PACTRA's side that is indistinguishable from a timeout
where nothing was created — so it must not be resolved by guessing in either
direction. Guess "failed" and the retry duplicates a real charge; guess
"succeeded" and PACTRA records money that never moved.

The duplicate-payment scenario deliberately uses a NON-IDEMPOTENT provider. With
a provider that deduplicates creates, a blind retry inside PACTRA would still
produce one payment and PACTRA's own bug would stay invisible — the fake would
be covering for it.
"""

from __future__ import annotations

import uuid
from typing import Any

from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import ReasonCode
from packages.schemas.payment import PaymentIntentState

from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import (
    drain_worker,
    effect_delta,
    payment_intents_for,
    worker_step,
)
from services.attack_lab.scenarios.adversaries import (
    MismatchingProvider,
    MisroutedProvider,
    NonIdempotentProvider,
)
from services.payment_executor.intents import (
    create_payment_intent,
)
from services.payment_executor.providers.fake import FaultMode

EXECUTOR = payment_executor_capabilities()


async def _request_payment(
    context: Any,
    *,
    mission_id: uuid.UUID,
    authorization_id: uuid.UUID,
    idempotency_key: str,
    provider: str = "fake",
) -> dict[str, Any]:
    """One payment request through the real, privileged entry point.

    Returns what happened rather than raising, so a scenario can attempt several
    and compare. The capability set comes from the server-owned registry; there
    is no argument through which a scenario could widen it.
    """
    async with context.sessionmaker() as session:
        try:
            result = await create_payment_intent(
                session,
                capabilities=EXECUTOR,
                mission_id=mission_id,
                authorization_id=authorization_id,
                idempotency_key=idempotency_key,
                provider=provider,
            )
            intent_id = result.intent.id
            created = result.created
            await session.commit()
            return {
                "accepted": True,
                "created": created,
                "intent_id": str(intent_id),
                "reason_code": None,
            }
        except Exception as exc:  # noqa: BLE001 - the refusal's identity is the measurement
            await session.rollback()
            return {
                "accepted": False,
                "created": False,
                "intent_id": None,
                "reason_code": getattr(exc, "reason_code", type(exc).__name__),
            }


# --------------------------------------------------------------------------- #
# 14. Idempotency conflict
# --------------------------------------------------------------------------- #


async def _conflict_setup(context: Any) -> dict[str, Any]:
    """Two independent authorized missions, A and B."""
    mission_a, authorization_a, _ = await context.authorized_mission(amount_inr=3799)
    mission_b, authorization_b, _ = await context.authorized_mission(
        amount_inr=2999, product_id="P2"
    )
    first = await _request_payment(
        context,
        mission_id=mission_a,
        authorization_id=authorization_a,
        idempotency_key="attack-shared-key",
    )
    return {
        "mission_a": mission_a,
        "mission_b": mission_b,
        "authorization_b": authorization_b,
        "first": first,
        "census": await context.census(),
    }


async def _conflict_execute(context: Any, state: dict[str, Any]) -> Observation:
    # The SAME key, a different transaction. Neither resolution is acceptable:
    # reusing mission A's intent would let a key minted for 3799 be presented
    # for 2999's mission, and creating a second would break the key's only
    # promise. The correct answer is refusal.
    second = await _request_payment(
        context,
        mission_id=state["mission_b"],
        authorization_id=state["authorization_b"],
        idempotency_key="attack-shared-key",
    )

    after = await context.census()
    delta = effect_delta(state["census"], after)
    intents_b = await payment_intents_for(context, state["mission_b"])
    intents_a = await payment_intents_for(context, state["mission_a"])

    refused = not second["accepted"]
    correct_code = second["reason_code"] == ReasonCode.IDEMPOTENCY_CONFLICT.value
    no_second_intent = delta["payment_intents"] == 0 and not intents_b
    # And it must not have silently handed back mission A's intent either.
    not_reused = second["intent_id"] != state["first"]["intent_id"]

    blocked = refused and correct_code and no_second_intent and not_reused
    return Observation(
        blocked=blocked,
        reason_code=second["reason_code"],
        invariant_preserved=no_second_intent and len(intents_a) == 1,
        observed_effects={
            "first_request": state["first"],
            "second_request": second,
            "payment_intents_created_by_attack": delta["payment_intents"],
            "mission_a_intents": len(intents_a),
            "mission_b_intents": len(intents_b),
            "logical_payments": len(intents_a) + len(intents_b),
            "reused_first_intent": not not_reused,
        },
        evidence=(
            "the same idempotency key presented for a materially different request "
            "was refused: neither reused nor duplicated"
        ),
    )


IDEMPOTENCY_CONFLICT = AttackScenario(
    id="idempotency_conflict",
    name="Idempotency key reused for a different transaction",
    category=AttackCategory.PAYMENT_RELIABILITY,
    severity=Severity.HIGH,
    description=(
        "One idempotency key is used for mission A's payment, then presented for "
        "mission B's entirely different payment. The request must be refused "
        "with IDEMPOTENCY_CONFLICT — not resolved by reusing A's intent, and not "
        "by creating a second."
    ),
    target_invariants=("SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT",),
    expected_reason_code=ReasonCode.IDEMPOTENCY_CONFLICT.value,
    critical=True,
    setup=_conflict_setup,
    execute=_conflict_execute,
)


# --------------------------------------------------------------------------- #
# 15. Duplicate payment
# --------------------------------------------------------------------------- #


async def _duplicate_setup(context: Any) -> dict[str, Any]:
    # A provider that creates a NEW payment on every create call, so a blind
    # retry inside PACTRA is immediately visible as a second provider payment
    # rather than being absorbed by provider-side idempotency.
    context.provider = NonIdempotentProvider()
    mission_id, authorization_id, _ = await context.authorized_mission()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "key": "attack-duplicate-key",
        "census": await context.census(),
    }


async def _duplicate_execute(context: Any, state: dict[str, Any]) -> Observation:
    key = state["key"]
    # Five repeated requests with the same key, plus repeated worker drains, so
    # both the request layer and the dispatch layer get their chance to double.
    requests = [
        await _request_payment(
            context,
            mission_id=state["mission_id"],
            authorization_id=state["authorization_id"],
            idempotency_key=key,
        )
        for _ in range(5)
    ]
    drained = await drain_worker(context)
    drained += await drain_worker(context)

    intents = await payment_intents_for(context, state["mission_id"])
    provider_payments = context.provider.payment_count_for(key)
    created_count = sum(bool(r["created"]) for r in requests)
    accepted_count = sum(bool(r["accepted"]) for r in requests)

    one_logical = len(intents) == 1
    one_provider = provider_payments <= 1
    one_creation = created_count == 1
    # Every repeat must be ACCEPTED and reported as not-created: an idempotent
    # retry is a legitimate operation, and erroring on it would be a different
    # bug wearing this test's passing grade.
    repeats_accepted = accepted_count == len(requests)

    blocked = one_logical and one_provider and one_creation and repeats_accepted
    return Observation(
        blocked=blocked,
        reason_code=None,
        invariant_preserved=one_logical and one_provider,
        observed_effects={
            "requests_issued": len(requests),
            "requests_accepted": accepted_count,
            "requests_that_created": created_count,
            "logical_payments": len(intents),
            "provider_payments": provider_payments,
            "provider_create_calls": len(context.provider.create_calls),
            "provider_is_idempotent": False,
            "worker_events_processed": len(drained),
            "final_state": intents[0]["state"] if intents else None,
        },
        evidence=(
            f"{len(requests)} same-key requests and two worker drains against a "
            f"deliberately NON-idempotent provider produced {len(intents)} logical "
            f"payment and {provider_payments} provider payment"
        ),
    )


DUPLICATE_PAYMENT = AttackScenario(
    id="duplicate_payment",
    name="Duplicate payment attempt",
    category=AttackCategory.PAYMENT_RELIABILITY,
    severity=Severity.CRITICAL,
    description=(
        "Five repeated payment requests share one idempotency key, and the outbox "
        "worker is drained twice, against a provider that creates a brand-new "
        "payment on every create call. Exactly one logical payment and at most "
        "one provider payment may exist."
    ),
    target_invariants=("SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT",),
    expected_reason_code=None,
    critical=True,
    setup=_duplicate_setup,
    execute=_duplicate_execute,
)


# --------------------------------------------------------------------------- #
# 16. Provider timeout AFTER create — the lost response
# --------------------------------------------------------------------------- #


async def _timeout_setup(context: Any) -> dict[str, Any]:
    # NON-idempotent on purpose. If a provider deduplicated creates, a PACTRA
    # blind retry after the lost response would still yield one payment and the
    # duplicate-charge bug would be hidden by the fake rather than absent.
    provider = NonIdempotentProvider()
    # The provider RECORDS the payment and THEN raises: the payment is real, the
    # response is not.
    provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE)
    context.provider = provider

    mission_id, authorization_id, _ = await context.authorized_mission()
    key = "attack-lost-response"
    request = await _request_payment(
        context,
        mission_id=mission_id,
        authorization_id=authorization_id,
        idempotency_key=key,
    )
    return {
        "mission_id": mission_id,
        "key": key,
        "request": request,
        "census": await context.census(),
    }


async def _timeout_execute(context: Any, state: dict[str, Any]) -> Observation:
    """Measure the lost-response recovery. Every condition below is REQUIRED.

    An earlier version of this scenario drove the worker with ``drain_worker``,
    which loops until the outbox is empty. Handling the lost response enqueues
    its OWN reconciliation event, immediately available — so one drain ran both
    turns and the scenario sampled the state after reconciliation had already
    resolved it. It read SUCCEEDED, concluded the uncertain state was never
    entered, and reported NOT_BLOCKED. The financial invariant had held
    perfectly the whole time; the harness was looking at the wrong moment.

    Stepping ONE event at a time is what makes the intermediate state
    observable. The lesson is kept rather than papered over: an attack lab that
    cannot see the state it is asserting about will invent findings.
    """
    key = state["key"]

    # --- turn 1: pre-create lookup, then the create whose response is lost ---
    first_event = await worker_step(context)
    after_timeout = await payment_intents_for(context, state["mission_id"])
    uncertain_state = after_timeout[0]["state"] if after_timeout else None
    became_uncertain = uncertain_state == PaymentIntentState.PROVIDER_PENDING.value
    # PACTRA must NOT have linked a provider payment yet: it has no evidence of
    # one. Linking here would be recording a fact it does not hold.
    linked_while_uncertain = bool(after_timeout and after_timeout[0]["provider_payment_id"])

    # The id of the payment the timed-out create actually produced. Captured now,
    # because the whole question at the end is whether PACTRA adopted THIS
    # payment or created a different one that merely happens to be the only one
    # left standing.
    original_ids = _provider_payment_ids(context.provider)
    provider_payments_after_timeout = context.provider.payment_count_for(key)
    create_calls_after_timeout = len(context.provider.create_calls)

    # --- recovery: reconciliation asks what the provider holds for the key ---
    for _ in range(4):
        await drain_worker(context)

    intents = await payment_intents_for(context, state["mission_id"])
    provider_payments = context.provider.payment_count_for(key)
    payments_ever_created = len(_provider_payment_ids(context.provider))
    create_calls = len(context.provider.create_calls)
    final_state = intents[0]["state"] if intents else None
    linked_id = intents[0]["provider_payment_id"] if intents else None

    # --- the required conditions, each measured, none assumed ---------------
    one_logical = len(intents) == 1
    one_provider = provider_payments == 1 and payments_ever_created == 1
    # A duplicate financial effect is more than one provider payment OR more
    # than one logical payment. Computed from counts, never from a status.
    duplicate_effect = payments_ever_created > 1 or len(intents) > 1
    # The strongest check available: the payment PACTRA settled against is the
    # one the timed-out create produced. One payment existing is not the same
    # claim as the ORIGINAL payment having been recovered.
    recovered_original_payment = bool(linked_id) and linked_id in original_ids
    settled = final_state == PaymentIntentState.SUCCEEDED.value

    blocked = (
        one_logical
        and one_provider
        and not duplicate_effect
        and recovered_original_payment
        and became_uncertain
        and not linked_while_uncertain
        and settled
    )
    return Observation(
        blocked=blocked,
        reason_code=(ReasonCode.PAYMENT_PROVIDER_TIMEOUT.value if became_uncertain else None),
        invariant_preserved=(
            one_logical and one_provider and not duplicate_effect and recovered_original_payment
        ),
        observed_effects={
            "first_outbox_event": first_event,
            "state_after_lost_response": uncertain_state,
            "entered_uncertain_state": became_uncertain,
            "linked_a_payment_while_uncertain": linked_while_uncertain,
            "provider_payments_after_timeout": provider_payments_after_timeout,
            "provider_create_calls_after_timeout": create_calls_after_timeout,
            "provider_payment_ids_after_timeout": sorted(original_ids),
            "final_state": final_state,
            "logical_payments": len(intents),
            "provider_payments": provider_payments,
            "provider_payments_ever_created": payments_ever_created,
            "provider_create_calls": create_calls,
            "provider_is_idempotent": False,
            "linked_provider_payment_id": linked_id,
            "recovered_original_payment": recovered_original_payment,
            "duplicate_effect": duplicate_effect,
            "attempts": intents[0]["attempts"] if intents else None,
        },
        evidence=(
            "the provider created the payment and the response was lost; PACTRA "
            f"went to PROVIDER_PENDING without linking anything, then reconciled onto "
            f"the ORIGINAL payment {linked_id!r} after {create_calls} create call(s), "
            f"leaving {payments_ever_created} provider payment and {len(intents)} "
            "logical payment"
        ),
    )


def _provider_payment_ids(provider: Any) -> set[str]:
    """Every provider payment id the provider has EVER created.

    ``created_payments`` is keyed on the idempotency key, so a provider that
    replaced one payment with another under the same key would still show one
    entry. ``NonIdempotentProvider.all_created`` keeps the full history, which
    is the only view in which a second create is visible. Falls back to the
    keyed map for providers that do not track history, so the helper is total.
    """
    history = getattr(provider, "all_created", None)
    if history is not None:
        return {payment.provider_payment_id for payment in history}
    return {payment.provider_payment_id for payment in provider.created_payments.values()}


PROVIDER_TIMEOUT_AFTER_CREATE = AttackScenario(
    id="provider_timeout_after_create",
    name="Provider timeout after the payment was created",
    category=AttackCategory.PAYMENT_RELIABILITY,
    severity=Severity.CRITICAL,
    description=(
        "The provider records a payment and then the response is lost. PACTRA "
        "must enter PROVIDER_PENDING rather than guessing, then reconcile onto "
        "the payment that already exists. Exactly one provider payment and one "
        "logical payment, against a deliberately non-idempotent provider."
    ),
    target_invariants=(
        "SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT",
        "A LOST PROVIDER RESPONSE -> UNCERTAINTY, NEVER A GUESSED OUTCOME",
        "RECOVERY -> ADOPTS THE ORIGINAL PAYMENT, NEVER A REPLACEMENT",
    ),
    expected_reason_code=ReasonCode.PAYMENT_PROVIDER_TIMEOUT.value,
    critical=True,
    setup=_timeout_setup,
    execute=_timeout_execute,
)


# --------------------------------------------------------------------------- #
# 17/18. Provider response mismatch
# --------------------------------------------------------------------------- #


def _mismatch_scenario(
    *, scenario_id: str, name: str, override: dict[str, Any], description: str
) -> AttackScenario:
    """A provider that answers 200 OK describing a DIFFERENT transaction."""

    async def setup(context: Any) -> dict[str, Any]:
        context.provider = MismatchingProvider(override=override)
        mission_id, authorization_id, _ = await context.authorized_mission(amount_inr=3799)
        request = await _request_payment(
            context,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="attack-mismatch",
        )
        return {"mission_id": mission_id, "request": request, "census": await context.census()}

    async def execute(context: Any, state: dict[str, Any]) -> Observation:
        await drain_worker(context)
        intents = await payment_intents_for(context, state["mission_id"])
        intent = intents[0] if intents else {}

        state_value = intent.get("state")
        # The three things that must NOT have happened.
        not_settled = state_value != PaymentIntentState.SUCCEEDED.value
        not_linked = intent.get("provider_payment_id") is None
        stayed_uncertain = state_value == PaymentIntentState.PROVIDER_PENDING.value
        amount_intact = intent.get("amount_inr") == 3799
        reason = intent.get("last_reason_code")

        blocked = not_settled and not_linked and stayed_uncertain and amount_intact
        return Observation(
            blocked=blocked,
            reason_code=reason,
            invariant_preserved=not_settled and not_linked and amount_intact,
            observed_effects={
                "provider_response_override": {k: str(v) for k, v in override.items()},
                "intent_state": state_value,
                "provider_payment_linked": not not_linked,
                "settled": not not_settled,
                "intent_amount_inr": intent.get("amount_inr"),
                "intent_currency": intent.get("currency"),
                "last_reason_code": reason,
                "logical_payments": len(intents),
            },
            evidence=(
                "a mismatched provider response was refused before linking and before "
                "any terminal transition; the intent stayed uncertain"
            ),
        )

    return AttackScenario(
        id=scenario_id,
        name=name,
        category=AttackCategory.PAYMENT_RELIABILITY,
        severity=Severity.HIGH,
        description=description,
        target_invariants=(
            "A PROVIDER RESPONSE -> MAY REPORT STATE, NEVER REDEFINE THE TRANSACTION",
        ),
        expected_reason_code=ReasonCode.PROVIDER_RESPONSE_MISMATCH.value,
        setup=setup,
        execute=execute,
    )


PROVIDER_AMOUNT_MISMATCH = _mismatch_scenario(
    scenario_id="provider_amount_mismatch",
    name="Provider response with the wrong amount",
    override={"amount_inr": 99999},
    description=(
        "The provider returns 200 OK for a payment of 99999 against an intent for "
        "3799. The response must be refused before the provider payment is linked "
        "and before any terminal transition, leaving the intent uncertain."
    ),
)

PROVIDER_CURRENCY_MISMATCH = _mismatch_scenario(
    scenario_id="provider_currency_mismatch",
    name="Provider response with the wrong currency",
    override={"currency": "USD"},
    description=(
        "The provider returns 200 OK describing a USD payment against an INR "
        "intent. Same refusal: report state, never redefine the transaction."
    ),
)

PROVIDER_KEY_MISMATCH = _mismatch_scenario(
    scenario_id="provider_idempotency_key_mismatch",
    name="Provider response naming a different idempotency key",
    override={"idempotency_key": "somebody-elses-key"},
    description=(
        "While no provider payment is linked, the idempotency key is the ONLY "
        "thing tying a response to this intent. A response naming a different key "
        "must be refused — a payment with a coincidentally equal amount and "
        "currency must never be adopted as ours."
    ),
)


# --------------------------------------------------------------------------- #
# 19. Wrong provider adapter
# --------------------------------------------------------------------------- #


async def _misroute_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, _ = await context.authorized_mission()
    request = await _request_payment(
        context,
        mission_id=mission_id,
        authorization_id=authorization_id,
        idempotency_key="attack-misroute",
    )
    return {"mission_id": mission_id, "request": request, "census": await context.census()}


async def _misroute_execute(context: Any, state: dict[str, Any]) -> Observation:
    # The intent says `fake`; the worker is handed an adapter calling itself
    # something else. The refusal must land BEFORE either provider method runs —
    # a mismatch caught after a payment was created is a duplicate, not a defence.
    misrouted = MisroutedProvider()
    errors: list[str] = []
    try:
        await drain_worker(context, provider=misrouted)
    except Exception as exc:  # noqa: BLE001 - the worker surfaces the refusal
        errors.append(getattr(exc, "reason_code", type(exc).__name__))

    intents = await payment_intents_for(context, state["mission_id"])
    intent = intents[0] if intents else {}

    provider_untouched = not misrouted.reached
    nothing_created = len(misrouted.created_payments) == 0
    not_settled = intent.get("state") != PaymentIntentState.SUCCEEDED.value
    not_linked = intent.get("provider_payment_id") is None
    refused = bool(errors)

    blocked = refused and provider_untouched and nothing_created and not_settled and not_linked
    return Observation(
        blocked=blocked,
        reason_code=errors[0] if errors else None,
        invariant_preserved=nothing_created and not_linked,
        observed_effects={
            "intent_provider": intent.get("provider"),
            "adapter_name": misrouted.name,
            "adapter_methods_reached": misrouted.reached,
            "adapter_payments_created": len(misrouted.created_payments),
            "refusals": errors,
            "intent_state": intent.get("state"),
            "provider_payment_linked": not not_linked,
            "logical_payments": len(intents),
        },
        evidence=(
            "an adapter whose name does not match the intent's provider was refused "
            "before either provider method was called"
        ),
    )


WRONG_PROVIDER_ADAPTER = AttackScenario(
    id="wrong_provider_adapter",
    name="Wrong provider adapter",
    category=AttackCategory.PAYMENT_RELIABILITY,
    severity=Severity.HIGH,
    description=(
        "The outbox worker is handed an adapter whose name does not match the "
        "intent's recorded provider. The routing must be refused before "
        "create_payment or get_payment is called, so no payment is created at the "
        "wrong rail."
    ),
    target_invariants=("A PROVIDER RESPONSE -> MAY REPORT STATE, NEVER REDEFINE THE TRANSACTION",),
    expected_reason_code=ReasonCode.PROVIDER_RESPONSE_MISMATCH.value,
    setup=_misroute_setup,
    execute=_misroute_execute,
)


SCENARIOS = (
    IDEMPOTENCY_CONFLICT,
    DUPLICATE_PAYMENT,
    PROVIDER_TIMEOUT_AFTER_CREATE,
    PROVIDER_AMOUNT_MISMATCH,
    PROVIDER_CURRENCY_MISMATCH,
    PROVIDER_KEY_MISMATCH,
    WRONG_PROVIDER_ADAPTER,
)
