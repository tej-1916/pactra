"""BENIGN_CONTROL — legitimate flows that must NOT be refused.

WHY THESE EXIST
---------------
A false-positive rate cannot be computed from attack scenarios. Attacks only
answer "was hostile behaviour stopped"; nothing in that set can tell you whether
the system also stops behaviour it should permit. A kernel that denied every
request would score a perfect 100% block rate, and without controls nothing in
this harness would notice.

So these run the SAME real paths, through the SAME entry points, with the SAME
capability sets — and are scored in the opposite direction:

    expected_status = NOT_BLOCKED
    a control reported BLOCKED is a FALSE POSITIVE

``Observation.blocked`` keeps its meaning throughout — "the action was refused"
— so nothing in the runner has to special-case a control. Only the expectation
differs, which is why the direction is declared on the scenario rather than
inferred from the category at scoring time.

Controls never take a shortcut. There is no flag that skips policy, no
pre-seeded ACTIVE row, no bypass. If a control passes, it passes because the
kernel let it through.
"""

from __future__ import annotations

import uuid
from typing import Any

from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import MissionState, PolicyOutcome
from packages.schemas.payment import PaymentIntentState, WebhookEventType

from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA
from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    AttackStatus,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import (
    constraints,
    drain_worker,
    mission_snapshot,
    payment_intents_for,
    run_mission,
    worker_step,
)
from services.attack_lab.scenarios.webhook import _deliver
from services.audit_ledger.replay import replay_mission
from services.audit_ledger.verify import verify_mission_chain
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import FaultMode, webhook_body
from services.security_kernel.authorization import (
    activate_authorization,
    authorization_for_mission,
    consume_authorization,
)

EXECUTOR = payment_executor_capabilities()


#: Nothing needs establishing for a control that builds its own world.
async def _no_setup(context: Any) -> dict[str, Any]:
    return {"census": await context.census()}


def _control(
    *,
    scenario_id: str,
    name: str,
    description: str,
    invariants: tuple[str, ...],
    setup: Any,
    execute: Any,
    severity: Severity = Severity.MEDIUM,
) -> AttackScenario:
    return AttackScenario(
        id=scenario_id,
        name=name,
        category=AttackCategory.BENIGN_CONTROL,
        severity=severity,
        description=description,
        target_invariants=invariants,
        expected_status=AttackStatus.NOT_BLOCKED,
        expected_reason_code=None,
        setup=setup,
        execute=execute,
    )


# --------------------------------------------------------------------------- #
# C1. A transaction inside every limit
# --------------------------------------------------------------------------- #


async def _allowed_execute(context: Any, state: dict[str, Any]) -> Observation:
    # 4299 is MockMerchantA's best offer; a 4500 soft budget puts it inside
    # every limit, so ALLOW is the only correct outcome.
    mission_id = await run_mission(
        context,
        merchants=[MockMerchantA()],
        mission_constraints=constraints(soft_budget_inr=4500, hard_limit_inr=5000),
    )
    snapshot = await mission_snapshot(context, mission_id)
    decision = snapshot["policy_decision"] or {}
    authorization = snapshot["authorization"] or {}

    allowed = decision.get("decision") == PolicyOutcome.ALLOW.value
    reached_authorized = snapshot["state"] == MissionState.AUTHORIZED.value
    authorization_active = authorization.get("status") == AuthorizationStatus.ACTIVE.value
    bound_to_amount = authorization.get("bound_amount_inr") == decision.get("requested_amount")

    permitted = allowed and reached_authorized and authorization_active and bound_to_amount
    return Observation(
        # `blocked` keeps its meaning: the benign flow was refused.
        blocked=not permitted,
        reason_code=None if permitted else str(decision.get("reason_codes")),
        invariant_preserved=permitted,
        observed_effects={
            "policy_decision": decision.get("decision"),
            "policy_reason_codes": decision.get("reason_codes"),
            "requested_amount": decision.get("requested_amount"),
            "soft_budget": decision.get("soft_budget"),
            "hard_limit": decision.get("hard_limit"),
            "mission_state": snapshot["state"],
            "authorization_status": authorization.get("status"),
            "authorization_bound_amount": authorization.get("bound_amount_inr"),
            "security_violations": snapshot["security_violations"],
        },
        evidence="a transaction inside every limit was ALLOWed and reached AUTHORIZED",
    )


CONTROL_ALLOWED_TRANSACTION = _control(
    scenario_id="control_allowed_transaction",
    name="Control: transaction inside every limit",
    description=(
        "An honest merchant offers 4299 against a 4500 soft budget and 5000 hard "
        "ceiling. The decision must be ALLOW, the mission must reach AUTHORIZED, "
        "and the authorization must be ACTIVE and bound to the adjudicated amount."
    ),
    invariants=("A COMPLIANT TRANSACTION -> PERMITTED",),
    setup=_no_setup,
    execute=_allowed_execute,
)


# --------------------------------------------------------------------------- #
# C2. Approval required, then granted by a human
# --------------------------------------------------------------------------- #


async def _approval_execute(context: Any, state: dict[str, Any]) -> Observation:
    # 4299 above a 4000 soft budget but under the 4500 ceiling: the approval path.
    mission_id = await run_mission(
        context,
        merchants=[MockMerchantA()],
        mission_constraints=constraints(soft_budget_inr=4000, hard_limit_inr=4500),
    )
    before = await mission_snapshot(context, mission_id)
    decision = before["policy_decision"] or {}

    requires_approval = decision.get("decision") == PolicyOutcome.REQUIRE_APPROVAL.value
    awaiting = before["state"] == MissionState.AWAITING_APPROVAL.value
    pending = (before["authorization"] or {}).get("status") == AuthorizationStatus.PENDING.value

    # The human approves — the real activation path, an atomic conditional UPDATE.
    approved = False
    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is not None:
            await activate_authorization(session, authorization_id=row.authorization_id)
            mission = await session.get(
                __import__("apps.api.db.models", fromlist=["Mission"]).Mission, mission_id
            )
            if mission is not None:
                mission.state = MissionState.AUTHORIZED.value
            await session.commit()
            approved = True

    after = await mission_snapshot(context, mission_id)
    now_active = (after["authorization"] or {}).get("status") == AuthorizationStatus.ACTIVE.value
    now_authorized = after["state"] == MissionState.AUTHORIZED.value

    permitted = (
        requires_approval and awaiting and pending and approved and now_active and now_authorized
    )
    return Observation(
        blocked=not permitted,
        reason_code=None if permitted else str(decision.get("reason_codes")),
        invariant_preserved=permitted,
        observed_effects={
            "policy_decision": decision.get("decision"),
            "policy_reason_codes": decision.get("reason_codes"),
            "mission_state_before_approval": before["state"],
            "authorization_status_before_approval": (before["authorization"] or {}).get("status"),
            "human_approval_applied": approved,
            "mission_state_after_approval": after["state"],
            "authorization_status_after_approval": (after["authorization"] or {}).get("status"),
        },
        evidence=(
            "an over-soft-budget transaction required approval, waited for it, and "
            "became ACTIVE only after a human granted it"
        ),
    )


CONTROL_REQUIRE_APPROVAL = _control(
    scenario_id="control_require_approval_transaction",
    name="Control: approval required, then granted",
    description=(
        "An offer above the soft budget but under the hard ceiling must produce "
        "REQUIRE_APPROVAL, leave the mission AWAITING_APPROVAL with a PENDING "
        "authorization, and reach AUTHORIZED only after a human approves."
    ),
    invariants=("APPROVAL REQUIRED -> HUMAN APPROVAL PERMITS THE TRANSACTION",),
    setup=_no_setup,
    execute=_approval_execute,
)


# --------------------------------------------------------------------------- #
# C3. A valid authorization is consumable exactly once
# --------------------------------------------------------------------------- #


async def _consume_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, transaction = await context.authorized_mission()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "transaction": transaction,
    }


async def _consume_execute(context: Any, state: dict[str, Any]) -> Observation:
    consumed = False
    reason: str | None = None
    async with context.sessionmaker() as session:
        try:
            await consume_authorization(
                session,
                authorization_id=state["authorization_id"],
                transaction=state["transaction"],
            )
            await session.commit()
            consumed = True
        except Exception as exc:  # noqa: BLE001 - a refusal here is the false positive
            await session.rollback()
            reason = getattr(exc, "reason_code", type(exc).__name__)

    from apps.api.db.models import AuthorizationRow

    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, state["authorization_id"], populate_existing=True)
        status = None if row is None else row.status
        consumed_at_set = bool(row is not None and row.consumed_at is not None)

    permitted = consumed and status == AuthorizationStatus.CONSUMED.value and consumed_at_set
    return Observation(
        blocked=not permitted,
        reason_code=reason,
        invariant_preserved=permitted,
        observed_effects={
            "consumed": consumed,
            "refusal_reason_code": reason,
            "authorization_status": status,
            "consumed_at_recorded": consumed_at_set,
        },
        evidence="a valid, unexpired, correctly-bound authorization was consumed once",
    )


CONTROL_VALID_CONSUMPTION = _control(
    scenario_id="control_valid_authorization_consumption",
    name="Control: valid authorization consumption",
    description=(
        "An ACTIVE, unexpired authorization presented with the exact transaction "
        "it is bound to must be consumed, moving to CONSUMED with a recorded "
        "consumption timestamp."
    ),
    invariants=("A VALID AUTHORIZATION -> CONSUMABLE EXACTLY ONCE",),
    setup=_consume_setup,
    execute=_consume_execute,
)


# --------------------------------------------------------------------------- #
# C4. A legitimate payment settles
# --------------------------------------------------------------------------- #


async def _payment_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, _ = await context.authorized_mission()
    return {"mission_id": mission_id, "authorization_id": authorization_id}


async def _payment_execute(context: Any, state: dict[str, Any]) -> Observation:
    key = "control-payment"
    accepted = False
    reason: str | None = None
    async with context.sessionmaker() as session:
        try:
            result = await create_payment_intent(
                session,
                capabilities=EXECUTOR,
                mission_id=state["mission_id"],
                authorization_id=state["authorization_id"],
                idempotency_key=key,
                provider="fake",
            )
            accepted = result.created
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            reason = getattr(exc, "reason_code", type(exc).__name__)

    await drain_worker(context)
    intents = await payment_intents_for(context, state["mission_id"])
    intent = intents[0] if intents else {}

    settled = intent.get("state") == PaymentIntentState.SUCCEEDED.value
    linked = bool(intent.get("provider_payment_id"))
    one_payment = len(intents) == 1 and context.provider.payment_count_for(key) == 1

    permitted = accepted and settled and linked and one_payment
    return Observation(
        blocked=not permitted,
        reason_code=reason,
        invariant_preserved=permitted,
        observed_effects={
            "request_accepted": accepted,
            "refusal_reason_code": reason,
            "final_state": intent.get("state"),
            "provider_payment_linked": linked,
            "logical_payments": len(intents),
            "provider_payments": context.provider.payment_count_for(key),
            "attempts": intent.get("attempts"),
        },
        evidence="an authorized mission's payment reached SUCCEEDED through the real worker",
    )


CONTROL_LEGITIMATE_PAYMENT = _control(
    scenario_id="control_legitimate_payment",
    name="Control: a legitimate payment settles",
    description=(
        "An authorized mission's payment request must be accepted, dispatched by "
        "the outbox worker, and settle SUCCEEDED with exactly one logical and one "
        "provider payment."
    ),
    invariants=("A VALID AUTHORIZATION -> A PAYMENT MAY PROCEED",),
    severity=Severity.HIGH,
    setup=_payment_setup,
    execute=_payment_execute,
)


# --------------------------------------------------------------------------- #
# C5. A legitimate retry with the same key
# --------------------------------------------------------------------------- #


async def _retry_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, _ = await context.authorized_mission()
    key = "control-retry"
    async with context.sessionmaker() as session:
        result = await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        first_id = str(result.intent.id)
        await session.commit()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "key": key,
        "first_id": first_id,
    }


async def _retry_execute(context: Any, state: dict[str, Any]) -> Observation:
    # A client that did not see the response retries with the SAME key. This is
    # the header's whole purpose: it must be accepted and must not create a
    # second payment. Refusing it would be a false positive that breaks every
    # well-behaved client.
    retries: list[dict[str, Any]] = []
    for _ in range(3):
        async with context.sessionmaker() as session:
            try:
                result = await create_payment_intent(
                    session,
                    capabilities=EXECUTOR,
                    mission_id=state["mission_id"],
                    authorization_id=state["authorization_id"],
                    idempotency_key=state["key"],
                    provider="fake",
                )
                retries.append(
                    {
                        "accepted": True,
                        "created": result.created,
                        "same_intent": str(result.intent.id) == state["first_id"],
                        "reason_code": None,
                    }
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                retries.append(
                    {
                        "accepted": False,
                        "created": False,
                        "same_intent": False,
                        "reason_code": getattr(exc, "reason_code", type(exc).__name__),
                    }
                )

    intents = await payment_intents_for(context, state["mission_id"])

    all_accepted = all(r["accepted"] for r in retries)
    none_created = not any(r["created"] for r in retries)
    all_same_intent = all(r["same_intent"] for r in retries)
    one_payment = len(intents) == 1

    permitted = all_accepted and none_created and all_same_intent and one_payment
    return Observation(
        blocked=not permitted,
        reason_code=next((r["reason_code"] for r in retries if r["reason_code"]), None),
        invariant_preserved=one_payment,
        observed_effects={
            "retries": retries,
            "all_accepted": all_accepted,
            "none_created_a_second_payment": none_created,
            "all_returned_the_original_intent": all_same_intent,
            "logical_payments": len(intents),
        },
        evidence=(
            "three identical retries with the same idempotency key were accepted and "
            "each returned the original intent; no second payment was created"
        ),
    )


CONTROL_LEGITIMATE_RETRY = _control(
    scenario_id="control_legitimate_retry",
    name="Control: legitimate retry with the same idempotency key",
    description=(
        "A client that did not see the response retries the identical request "
        "three times. Each retry must be ACCEPTED, must return the original "
        "intent, and must not create a second payment. Refusing a well-formed "
        "retry is a false positive."
    ),
    invariants=("AN IDENTICAL RETRY -> ACCEPTED, AND STILL ONE LOGICAL PAYMENT",),
    severity=Severity.HIGH,
    setup=_retry_setup,
    execute=_retry_execute,
)


# --------------------------------------------------------------------------- #
# C6. A transient provider failure recovers
# --------------------------------------------------------------------------- #


async def _transient_setup(context: Any) -> dict[str, Any]:
    # The provider ANSWERED "not now" — nothing was created, so a retry is safe
    # and must actually happen. A system that gave up here would be too eager to
    # refuse, which is the failure mode controls exist to catch.
    context.provider.queue_faults(FaultMode.TRANSIENT_FAILURE, FaultMode.SUCCESS)
    mission_id, authorization_id, _ = await context.authorized_mission()
    key = "control-transient"
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await session.commit()
    return {"mission_id": mission_id, "key": key}


async def _transient_execute(context: Any, state: dict[str, Any]) -> Observation:
    first = await worker_step(context)
    after_failure = await payment_intents_for(context, state["mission_id"])
    retryable = (
        after_failure[0]["state"] == PaymentIntentState.FAILED_RETRYABLE.value
        if after_failure
        else False
    )

    # The retry is scheduled with backoff, so drive it explicitly rather than
    # waiting: the property under test is that recovery HAPPENS, not its timing.
    from apps.api.db.models import OutboxEventRow
    from packages.schemas.domain import utcnow
    from sqlalchemy import update as sql_update

    async with context.sessionmaker() as session:
        await session.execute(
            sql_update(OutboxEventRow)
            .values(available_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    await drain_worker(context)

    intents = await payment_intents_for(context, state["mission_id"])
    intent = intents[0] if intents else {}
    settled = intent.get("state") == PaymentIntentState.SUCCEEDED.value
    one_payment = len(intents) == 1 and context.provider.payment_count_for(state["key"]) == 1

    permitted = retryable and settled and one_payment
    return Observation(
        blocked=not permitted,
        reason_code=None if permitted else intent.get("last_reason_code"),
        invariant_preserved=one_payment,
        observed_effects={
            "first_outbox_event": first,
            "state_after_transient_failure": (after_failure[0]["state"] if after_failure else None),
            "became_retryable": retryable,
            "final_state": intent.get("state"),
            "logical_payments": len(intents),
            "provider_payments": context.provider.payment_count_for(state["key"]),
            "provider_create_calls": len(context.provider.create_calls),
            "attempts": intent.get("attempts"),
        },
        evidence=(
            "a provider that answered 'not now' made the payment retryable, and the "
            "retry settled it with one provider payment"
        ),
    )


CONTROL_TRANSIENT_RETRY = _control(
    scenario_id="control_transient_retry_recovers",
    name="Control: transient provider failure recovers",
    description=(
        "The provider answers 'not now' — it created nothing, so retrying is safe. "
        "The intent must become FAILED_RETRYABLE and the retry must settle it with "
        "exactly one provider payment. Giving up here would be over-refusal."
    ),
    invariants=("A TRANSIENT PROVIDER FAILURE -> SAFE, SUCCESSFUL RETRY",),
    severity=Severity.HIGH,
    setup=_transient_setup,
    execute=_transient_execute,
)


# --------------------------------------------------------------------------- #
# C7. A genuine webhook settles a pending payment
# --------------------------------------------------------------------------- #


async def _webhook_setup(context: Any) -> dict[str, Any]:
    context.provider.queue_faults(FaultMode.PENDING)
    mission_id, authorization_id, _ = await context.authorized_mission()
    key = "control-webhook"
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await session.commit()
    await drain_worker(context)
    intents = await payment_intents_for(context, mission_id)
    return {
        "mission_id": mission_id,
        "provider_payment_id": intents[0]["provider_payment_id"],
        "state_before": intents[0]["state"],
    }


async def _webhook_execute(context: Any, state: dict[str, Any]) -> Observation:
    body = webhook_body(
        event_id="control-webhook-event",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=state["provider_payment_id"] or "fake_pay_unknown",
    )
    # Signed with the provider's real secret — the one thing a forger cannot do.
    outcome = await _deliver(context, body=body, signature=context.provider.sign(body))

    intents = await payment_intents_for(context, state["mission_id"])
    final_state = intents[0]["state"] if intents else None

    accepted = bool(outcome["accepted"])
    applied = bool(outcome["applied"])
    settled = final_state == PaymentIntentState.SUCCEEDED.value

    permitted = accepted and applied and settled
    return Observation(
        blocked=not permitted,
        reason_code=outcome["reason_code"],
        invariant_preserved=permitted,
        observed_effects={
            "state_before_webhook": state["state_before"],
            "delivery": outcome,
            "state_after_webhook": final_state,
            "logical_payments": len(intents),
        },
        evidence="a correctly-signed, first-delivery webhook settled the pending payment",
    )


CONTROL_VALID_WEBHOOK = _control(
    scenario_id="control_valid_webhook",
    name="Control: a genuine webhook settles a payment",
    description=(
        "A correctly-signed, non-duplicate webhook for a genuinely pending payment "
        "must be accepted and APPLIED, moving the payment to SUCCEEDED. Rejecting "
        "it would be a false positive that breaks settlement."
    ),
    invariants=("A VERIFIED WEBHOOK -> A PERMITTED STATE TRANSITION",),
    severity=Severity.HIGH,
    setup=_webhook_setup,
    execute=_webhook_execute,
)


# --------------------------------------------------------------------------- #
# C8. Reconciliation resolves a genuinely pending payment
# --------------------------------------------------------------------------- #


async def _reconcile_setup(context: Any) -> dict[str, Any]:
    context.provider.queue_faults(FaultMode.PENDING)
    mission_id, authorization_id, _ = await context.authorized_mission()
    key = "control-reconcile"
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await session.commit()
    await worker_step(context)
    intents = await payment_intents_for(context, mission_id)
    return {
        "mission_id": mission_id,
        "key": key,
        "state_before": intents[0]["state"] if intents else None,
    }


async def _reconcile_execute(context: Any, state: dict[str, Any]) -> Observation:
    from packages.schemas.payment import ProviderPaymentStatus

    # The provider settles out of band, then reconciliation asks it what it holds.
    context.provider.settle(state["key"], ProviderPaymentStatus.SUCCEEDED)

    from apps.api.db.models import OutboxEventRow
    from packages.schemas.domain import utcnow
    from sqlalchemy import update as sql_update

    async with context.sessionmaker() as session:
        await session.execute(
            sql_update(OutboxEventRow)
            .values(available_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    await drain_worker(context)

    intents = await payment_intents_for(context, state["mission_id"])
    intent = intents[0] if intents else {}
    settled = intent.get("state") == PaymentIntentState.SUCCEEDED.value
    one_payment = len(intents) == 1 and context.provider.payment_count_for(state["key"]) == 1

    permitted = settled and one_payment
    return Observation(
        blocked=not permitted,
        reason_code=None if permitted else intent.get("last_reason_code"),
        invariant_preserved=one_payment,
        observed_effects={
            "state_before_reconciliation": state["state_before"],
            "final_state": intent.get("state"),
            "logical_payments": len(intents),
            "provider_payments": context.provider.payment_count_for(state["key"]),
            "provider_create_calls": len(context.provider.create_calls),
        },
        evidence=(
            "a genuinely pending payment was resolved by asking the provider what it "
            "held for the idempotency key; no second payment was created"
        ),
    )


CONTROL_VALID_RECONCILIATION = _control(
    scenario_id="control_valid_reconciliation",
    name="Control: reconciliation resolves a pending payment",
    description=(
        "A payment the provider accepted but had not settled is resolved by "
        "reconciliation once the provider settles out of band. It must reach "
        "SUCCEEDED without a second create call."
    ),
    invariants=("A PENDING PAYMENT -> RESOLVED BY RECONCILIATION, NOT BY GUESSING",),
    severity=Severity.HIGH,
    setup=_reconcile_setup,
    execute=_reconcile_execute,
)


# --------------------------------------------------------------------------- #
# C9 / C10. An untampered chain verifies, and replays
# --------------------------------------------------------------------------- #


async def _audit_setup(context: Any) -> dict[str, Any]:
    """A full, honest mission history including a real payment."""
    mission_id, authorization_id, _ = await context.authorized_mission()
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="control-audit",
            provider="fake",
        )
        await session.commit()
    await drain_worker(context)
    return {"mission_id": mission_id}


async def _audit_execute(context: Any, state: dict[str, Any]) -> Observation:
    mission_id: uuid.UUID = state["mission_id"]
    async with context.sessionmaker() as session:
        first = await verify_mission_chain(session, mission_id)
        # Verified twice, because a verifier that WROTE while checking would
        # produce a different verdict the second time.
        second = await verify_mission_chain(session, mission_id)

    valid = first.valid and second.valid
    stable = first.model_dump() == second.model_dump()
    checked = first.events_checked

    permitted = valid and stable and checked > 0
    return Observation(
        blocked=not permitted,
        reason_code=first.reason_code.value,
        invariant_preserved=permitted,
        observed_effects={
            "valid": first.valid,
            "events_checked": checked,
            "reason_code": first.reason_code.value,
            "repeat_verification_identical": stable,
            "first_invalid_sequence": first.first_invalid_sequence,
        },
        evidence=(
            f"an untampered {checked}-event chain verified, and verifying it twice "
            "produced an identical result"
        ),
    )


CONTROL_AUDIT_CHAIN_VERIFIES = _control(
    scenario_id="control_audit_chain_verifies",
    name="Control: an untampered audit chain verifies",
    description=(
        "A real mission history including an authorization and a settled payment "
        "must verify, and verifying it twice must give an identical result — a "
        "verifier that wrote while checking would not."
    ),
    invariants=("AN INTACT CHAIN -> VERIFICATION SUCCEEDS",),
    severity=Severity.HIGH,
    setup=_audit_setup,
    execute=_audit_execute,
)


async def _replay_execute(context: Any, state: dict[str, Any]) -> Observation:
    mission_id: uuid.UUID = state["mission_id"]
    async with context.sessionmaker() as session:
        result = await replay_mission(session, mission_id)
        repeat = await replay_mission(session, mission_id)

    trusted = result.trusted
    has_state = result.state is not None
    comparison = result.comparison
    matches = bool(comparison and comparison.matches)
    deterministic = result.model_dump(mode="json") == repeat.model_dump(mode="json")

    permitted = trusted and has_state and matches and deterministic
    return Observation(
        blocked=not permitted,
        reason_code=result.reason_code.value,
        invariant_preserved=permitted,
        observed_effects={
            "trusted": trusted,
            "reason_code": result.reason_code.value,
            "events_replayed": result.events_replayed,
            "replay_state": comparison.replay_state if comparison else None,
            "persisted_state": comparison.persisted_state if comparison else None,
            "state_matches_persisted": matches,
            "payment_matches": comparison.payment_matches if comparison else None,
            "authorization_matches": comparison.authorization_matches if comparison else None,
            "repeat_replay_byte_identical": deterministic,
        },
        evidence=(
            "an intact chain replayed to a trusted projection matching the persisted "
            "state, and replaying it again produced a byte-identical result"
        ),
    )


CONTROL_TRUSTED_REPLAY = _control(
    scenario_id="control_trusted_replay",
    name="Control: an intact chain replays to the persisted state",
    description=(
        "Replay of an untampered history must be trusted, must produce a "
        "projection, must match the persisted mission state, and must be "
        "deterministic across repeated calls."
    ),
    invariants=("AN INTACT CHAIN -> DETERMINISTIC, TRUSTED RECONSTRUCTION",),
    severity=Severity.HIGH,
    setup=_audit_setup,
    execute=_replay_execute,
)


SCENARIOS = (
    CONTROL_ALLOWED_TRANSACTION,
    CONTROL_REQUIRE_APPROVAL,
    CONTROL_VALID_CONSUMPTION,
    CONTROL_LEGITIMATE_PAYMENT,
    CONTROL_LEGITIMATE_RETRY,
    CONTROL_TRANSIENT_RETRY,
    CONTROL_VALID_WEBHOOK,
    CONTROL_VALID_RECONCILIATION,
    CONTROL_AUDIT_CHAIN_VERIFIES,
    CONTROL_TRUSTED_REPLAY,
)
