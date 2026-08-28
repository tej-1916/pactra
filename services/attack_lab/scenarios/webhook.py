"""WEBHOOK — a delivery is a pointer, never a restatement of the transaction.

Three refusals, three different mechanisms, and it matters that they are
different:

* **Forged signature** — refused by the MAC over the RAW bytes before the body
  is parsed as meaning. The handler's only input type is a
  ``VerifiedWebhookEvent``, which the provider's verifier alone can produce, so
  "we forgot to check the signature" is not a mistake the code can make.
* **Duplicate delivery** — refused by ``UNIQUE(provider, provider_event_id)``,
  not by a prior SELECT. Two deliveries racing both reach the insert; the index
  decides.
* **Out-of-order / delayed delivery** — refused by the payment state machine.
  Terminal states have no outgoing transitions, so a late ``payment.failed``
  after a settled success cannot regress anything. The provider's own sequence
  number is recorded for audit and is never the authority.

Every scenario measures the payment state before and after, because a webhook
that was "rejected" while still moving the payment would be no defence at all.
"""

from __future__ import annotations

from typing import Any

from apps.api.db.models import WebhookEventRow
from packages.schemas.domain import ReasonCode
from packages.schemas.payment import PaymentIntentState, WebhookEventType
from sqlalchemy import func, select

from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import (
    drain_worker,
    payment_intents_for,
)
from services.payment_executor.providers.fake import FaultMode, webhook_body
from services.payment_executor.webhooks import WebhookRejected, handle_webhook


async def _webhook_event_count(context: Any) -> int:
    async with context.sessionmaker() as session:
        return int(
            (await session.execute(select(func.count()).select_from(WebhookEventRow))).scalar_one()
        )


async def _deliver(context: Any, *, body: bytes, signature: str) -> dict[str, Any]:
    """One webhook delivery through the real handler. Never raises to the caller."""
    async with context.sessionmaker() as session:
        try:
            outcome = await handle_webhook(
                session, provider=context.provider, body=body, signature=signature
            )
            await session.commit()
            return {
                "accepted": outcome.accepted,
                "applied": outcome.applied,
                "reason_code": outcome.reason_code,
                "state": outcome.state.value if outcome.state else None,
            }
        except WebhookRejected as rejected:
            await session.rollback()
            return {
                "accepted": False,
                "applied": False,
                "reason_code": rejected.reason_code,
                "state": None,
            }


async def _settled_payment(context: Any, *, fault: FaultMode = FaultMode.SUCCESS) -> dict[str, Any]:
    """An authorized mission whose payment has been driven to a provider result."""
    from packages.schemas.capability import payment_executor_capabilities

    from services.payment_executor.intents import create_payment_intent

    context.provider.queue_faults(fault)
    mission_id, authorization_id, _ = await context.authorized_mission()
    key = "attack-webhook"
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=payment_executor_capabilities(),
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await session.commit()
    await drain_worker(context)

    intents = await payment_intents_for(context, mission_id)
    intent = intents[0]
    return {
        "mission_id": mission_id,
        "key": key,
        "provider_payment_id": intent["provider_payment_id"],
        "state_before": intent["state"],
        "webhook_events_before": await _webhook_event_count(context),
    }


# --------------------------------------------------------------------------- #
# 20. Forged webhook
# --------------------------------------------------------------------------- #


async def _forgery_setup(context: Any) -> dict[str, Any]:
    return await _settled_payment(context, fault=FaultMode.PENDING)


async def _forgery_execute(context: Any, state: dict[str, Any]) -> Observation:
    body = webhook_body(
        event_id="attack-forged-1",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=state["provider_payment_id"] or "fake_pay_unknown",
    )

    # Four forgeries, because a signature check can be wrong in more than one
    # way: absent, wrong, well-shaped-but-wrong, and a valid signature over
    # DIFFERENT bytes (the classic sign-then-swap).
    genuine_for_other_bytes = context.provider.sign(b'{"event_id":"other"}')
    attempts = {
        "empty_signature": "",
        "arbitrary_signature": "deadbeef",
        "hash_shaped_signature": "0" * 64,
        "valid_signature_over_different_bytes": genuine_for_other_bytes,
    }
    results = {
        label: await _deliver(context, body=body, signature=signature)
        for label, signature in attempts.items()
    }

    intents = await payment_intents_for(context, state["mission_id"])
    state_after = intents[0]["state"] if intents else None
    events_after = await _webhook_event_count(context)

    all_rejected = all(
        r["reason_code"] == ReasonCode.WEBHOOK_SIGNATURE_INVALID.value for r in results.values()
    )
    none_applied = not any(r["applied"] for r in results.values())
    state_unchanged = state_after == state["state_before"]
    # A rejected delivery is deliberately NOT recorded: the ledger is
    # mission-scoped and the only thing naming a mission in a forged delivery is
    # the body whose MAC just failed.
    nothing_stored = events_after == state["webhook_events_before"]

    blocked = all_rejected and none_applied and state_unchanged and nothing_stored
    return Observation(
        blocked=blocked,
        reason_code=ReasonCode.WEBHOOK_SIGNATURE_INVALID.value if all_rejected else None,
        invariant_preserved=state_unchanged and none_applied,
        observed_effects={
            "forgeries_attempted": list(attempts),
            "results": results,
            "payment_state_before": state["state_before"],
            "payment_state_after": state_after,
            "webhook_rows_before": state["webhook_events_before"],
            "webhook_rows_after": events_after,
        },
        evidence=(
            "four forged signatures refused by the MAC over the raw body; the payment "
            "state is unchanged and no webhook row was written"
        ),
    )


WEBHOOK_FORGERY = AttackScenario(
    id="webhook_forgery",
    name="Forged webhook signature",
    category=AttackCategory.WEBHOOK,
    severity=Severity.CRITICAL,
    description=(
        "Four forged deliveries — no signature, an arbitrary one, a hash-shaped "
        "one, and a genuine signature over different bytes — are sent for a real "
        "pending payment. Each must be refused before the body is read as state, "
        "with no payment mutation and no stored webhook row."
    ),
    target_invariants=(
        "AN UNVERIFIED WEBHOOK -> NEVER PAYMENT STATE",
        "A WEBHOOK -> SUPPLIES A POINTER, NEVER A TRANSACTION",
    ),
    expected_reason_code=ReasonCode.WEBHOOK_SIGNATURE_INVALID.value,
    critical=True,
    setup=_forgery_setup,
    execute=_forgery_execute,
)


# --------------------------------------------------------------------------- #
# 21. Duplicate webhook (webhook replay)
# --------------------------------------------------------------------------- #


async def _duplicate_setup(context: Any) -> dict[str, Any]:
    state = await _settled_payment(context, fault=FaultMode.PENDING)
    body = webhook_body(
        event_id="attack-replayed-event",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=state["provider_payment_id"] or "fake_pay_unknown",
    )
    # The FIRST delivery is legitimate and must apply — otherwise the replay
    # would be refused for the boring reason that nothing works.
    first = await _deliver(context, body=body, signature=context.provider.sign(body))
    state["body"] = body
    state["first"] = first
    state["webhook_events_after_first"] = await _webhook_event_count(context)
    intents = await payment_intents_for(context, state["mission_id"])
    state["state_after_first"] = intents[0]["state"]
    return state


async def _duplicate_execute(context: Any, state: dict[str, Any]) -> Observation:
    body = state["body"]
    signature = context.provider.sign(body)
    # Replayed three times with a genuine signature — a captured delivery an
    # attacker resends verbatim. The MAC is valid; the deduplication has to do
    # the work.
    replays = [await _deliver(context, body=body, signature=signature) for _ in range(3)]

    intents = await payment_intents_for(context, state["mission_id"])
    state_after = intents[0]["state"]
    events_after = await _webhook_event_count(context)

    first_applied = bool(state["first"]["applied"])
    none_reapplied = not any(r["applied"] for r in replays)
    all_duplicate = all(r["reason_code"] == ReasonCode.WEBHOOK_DUPLICATE.value for r in replays)
    state_unchanged = state_after == state["state_after_first"]
    # The unique index refused every second insert, so exactly one row exists
    # for this provider event no matter how many times it arrived.
    one_row_per_event = events_after == state["webhook_events_after_first"]

    blocked = (
        first_applied and none_reapplied and all_duplicate and state_unchanged and one_row_per_event
    )
    return Observation(
        blocked=blocked,
        reason_code=ReasonCode.WEBHOOK_DUPLICATE.value if all_duplicate else None,
        invariant_preserved=state_unchanged and none_reapplied,
        observed_effects={
            "first_delivery": state["first"],
            "replays": replays,
            "unauthorized_effect": not (none_reapplied and state_unchanged),
            "payment_state_after_first": state["state_after_first"],
            "payment_state_after_replays": state_after,
            "webhook_rows_after_first": state["webhook_events_after_first"],
            "webhook_rows_after_replays": events_after,
            "logical_payments": len(intents),
        },
        evidence=(
            "a genuinely-signed delivery replayed three times applied exactly once; "
            "the UNIQUE(provider, provider_event_id) index refused the repeats"
        ),
    )


WEBHOOK_REPLAY = AttackScenario(
    id="webhook_replay",
    name="Duplicate / replayed webhook",
    category=AttackCategory.WEBHOOK,
    severity=Severity.HIGH,
    description=(
        "A genuine, correctly-signed webhook is captured and resent three times. "
        "The first delivery applies; every replay must be recognised as a "
        "duplicate, change nothing, and add no second webhook row."
    ),
    target_invariants=(
        "A DUPLICATE WEBHOOK -> NO DUPLICATED SIDE EFFECT",
        "REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE",
    ),
    expected_reason_code=ReasonCode.WEBHOOK_DUPLICATE.value,
    critical=True,
    setup=_duplicate_setup,
    execute=_duplicate_execute,
)


# --------------------------------------------------------------------------- #
# 22. Out-of-order / delayed webhook
# --------------------------------------------------------------------------- #


async def _out_of_order_setup(context: Any) -> dict[str, Any]:
    """A payment settled SUCCEEDED by a legitimate webhook."""
    state = await _settled_payment(context, fault=FaultMode.PENDING)
    body = webhook_body(
        event_id="attack-legit-success",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=state["provider_payment_id"] or "fake_pay_unknown",
        sequence=2,
    )
    state["first"] = await _deliver(context, body=body, signature=context.provider.sign(body))
    intents = await payment_intents_for(context, state["mission_id"])
    state["state_after_success"] = intents[0]["state"]
    return state


async def _out_of_order_execute(context: Any, state: dict[str, Any]) -> Observation:
    payment_id = state["provider_payment_id"] or "fake_pay_unknown"

    # Each of these is correctly signed and NOT a duplicate — new event ids, so
    # deduplication cannot be what refuses them. Only the state machine can.
    # The failure even carries a HIGHER provider sequence number, so a system
    # that trusted provider-supplied ordering would apply it.
    deliveries = {
        "failure_after_success": webhook_body(
            event_id="attack-late-failure",
            event_type=WebhookEventType.PAYMENT_FAILED,
            provider_payment_id=payment_id,
            sequence=99,
        ),
        "pending_after_success": webhook_body(
            event_id="attack-late-pending",
            event_type=WebhookEventType.PAYMENT_PENDING,
            provider_payment_id=payment_id,
            sequence=100,
        ),
        "repeat_success": webhook_body(
            event_id="attack-repeat-success",
            event_type=WebhookEventType.PAYMENT_SUCCEEDED,
            provider_payment_id=payment_id,
            sequence=101,
        ),
    }
    results = {
        label: await _deliver(context, body=body, signature=context.provider.sign(body))
        for label, body in deliveries.items()
    }

    intents = await payment_intents_for(context, state["mission_id"])
    state_after = intents[0]["state"]

    first_settled = state["state_after_success"] == PaymentIntentState.SUCCEEDED.value
    none_applied = not any(r["applied"] for r in results.values())
    all_ignored = all(
        r["reason_code"] == ReasonCode.ILLEGAL_PAYMENT_TRANSITION.value for r in results.values()
    )
    no_regression = state_after == PaymentIntentState.SUCCEEDED.value

    blocked = first_settled and none_applied and all_ignored and no_regression
    return Observation(
        blocked=blocked,
        reason_code=ReasonCode.ILLEGAL_PAYMENT_TRANSITION.value if all_ignored else None,
        invariant_preserved=no_regression and none_applied,
        observed_effects={
            "deliveries": results,
            "provider_sequence_numbers_were_higher": True,
            "state_after_legitimate_success": state["state_after_success"],
            "state_after_out_of_order": state_after,
            "state_regressed": not no_regression,
            "logical_payments": len(intents),
        },
        evidence=(
            "a late failure, a late pending, and a repeated success — all correctly "
            "signed, all with higher provider sequence numbers, none a duplicate — "
            "were refused by the state machine; the settled payment did not regress"
        ),
    )


WEBHOOK_OUT_OF_ORDER = AttackScenario(
    id="webhook_out_of_order",
    name="Out-of-order / delayed webhook",
    category=AttackCategory.WEBHOOK,
    severity=Severity.HIGH,
    description=(
        "After a payment settles SUCCEEDED, three fresh correctly-signed "
        "deliveries arrive: a failure, a pending, and a repeated success — each "
        "carrying a higher provider sequence number. None is a duplicate, so only "
        "the state machine can refuse them, and no state regression may occur."
    ),
    target_invariants=(
        "A DELAYED WEBHOOK -> NO ILLEGAL STATE REGRESSION",
        "PROVIDER ORDERING -> NEVER THE AUTHORITY FOR A TRANSITION",
    ),
    expected_reason_code=ReasonCode.ILLEGAL_PAYMENT_TRANSITION.value,
    critical=True,
    setup=_out_of_order_setup,
    execute=_out_of_order_execute,
)


SCENARIOS = (WEBHOOK_FORGERY, WEBHOOK_REPLAY, WEBHOOK_OUT_OF_ORDER)
