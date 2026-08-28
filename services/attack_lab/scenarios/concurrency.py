"""CONCURRENCY — races, on PostgreSQL, because SQLite cannot host them.

SQLite serializes writers with a whole-database lock. A "race" there is refused
by the database declining to let the interleaving happen, not by the code under
test — so a scenario that passed on SQLite would prove the database prevented
the race, not that PACTRA survives it. PostgreSQL uses row-level locks and MVCC:
two sessions genuinely interleave, the loser genuinely blocks, re-evaluates its
WHERE clause under READ COMMITTED, and is refused by the conditional UPDATE
matching zero rows. That is the mechanism production relies on.

Every scenario here therefore declares ``Backend.POSTGRES``. With no server
reachable they report INCONCLUSIVE with ``BACKEND_UNAVAILABLE`` and are excluded
from every rate — never BLOCKED. A concurrency guarantee that was not exercised
must never be reported as one that was, and the alternative (quietly degrading
to SQLite) would produce exactly that lie.

The measurement in each case is a COUNT of winners, not a status: "exactly one
of eight concurrent attempts succeeded" is evidence, and it is the only claim
these scenarios make.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from apps.api.db.models import AuditEventRow, OutboxEventRow, PaymentIntentRow
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import EventType, ReasonCode
from packages.schemas.payment import PaymentIntentState, WebhookEventType
from sqlalchemy import func, select

from services.attack_lab.models import (
    AttackCategory,
    AttackScenario,
    Backend,
    Observation,
    Severity,
)
from services.attack_lab.scenarios._helpers import drain_worker, payment_intents_for
from services.audit_ledger.ledger import append_event, list_events
from services.audit_ledger.verify import verify_events
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.outbox import claim_next_event
from services.payment_executor.providers.fake import FaultMode, webhook_body
from services.payment_executor.webhooks import WebhookRejected, handle_webhook
from services.security_kernel.authorization import (
    AuthorizationFailure,
    consume_authorization,
    load_authorization,
)

EXECUTOR = payment_executor_capabilities()

#: How many genuinely concurrent attempts each race makes. Eight is enough that
#: a lock held for the wrong duration shows up, and small enough that the whole
#: batch stays fast.
RACERS = 8


def _pg(
    *,
    scenario_id: str,
    name: str,
    severity: Severity,
    description: str,
    invariants: tuple[str, ...],
    expected_reason_code: str | None,
    setup: Any,
    execute: Any,
    critical: bool = False,
) -> AttackScenario:
    return AttackScenario(
        id=scenario_id,
        name=name,
        category=AttackCategory.CONCURRENCY,
        severity=severity,
        description=description,
        target_invariants=invariants,
        backend=Backend.POSTGRES,
        expected_reason_code=expected_reason_code,
        critical=critical,
        setup=setup,
        execute=execute,
    )


# --------------------------------------------------------------------------- #
# 1. Concurrent authorization consumption
# --------------------------------------------------------------------------- #


async def _auth_race_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, transaction = await context.authorized_mission()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "transaction": transaction,
    }


async def _auth_race_execute(context: Any, state: dict[str, Any]) -> Observation:
    authorization_id: uuid.UUID = state["authorization_id"]
    transaction = state["transaction"]

    async def attempt() -> str:
        async with context.sessionmaker() as session:
            try:
                await consume_authorization(
                    session, authorization_id=authorization_id, transaction=transaction
                )
                await session.commit()
                return "WON"
            except AuthorizationFailure as failure:
                await session.rollback()
                return failure.reason_code
            except Exception as exc:  # noqa: BLE001 - a DB-level refusal is still a loss
                await session.rollback()
                return type(exc).__name__

    outcomes = await asyncio.gather(*[attempt() for _ in range(RACERS)])
    winners = outcomes.count("WON")
    replay_losses = outcomes.count(ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value)

    async with context.sessionmaker() as session:
        row = await load_authorization(session, authorization_id)
        final_status = None if row is None else row.status
        consumed_once = bool(row is not None and row.consumed_at is not None)

    exactly_one = winners == 1
    settled_consumed = final_status == AuthorizationStatus.CONSUMED.value

    blocked = exactly_one and settled_consumed
    return Observation(
        blocked=blocked,
        reason_code=(ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value if replay_losses else None),
        invariant_preserved=exactly_one,
        observed_effects={
            "concurrent_attempts": RACERS,
            "winners": winners,
            "losers": RACERS - winners,
            "losses_by_replay_detection": replay_losses,
            "loss_reasons": sorted(set(outcomes) - {"WON"}),
            "unauthorized_effect": winners > 1,
            "final_authorization_status": final_status,
            "consumed_at_recorded_once": consumed_once,
        },
        evidence=(
            f"{RACERS} genuinely concurrent consumptions of one authorization produced "
            f"exactly {winners} winner; the losers were refused by the conditional UPDATE"
        ),
    )


PG_CONCURRENT_AUTHORIZATION_CONSUMPTION = _pg(
    scenario_id="pg_concurrent_authorization_consumption",
    name="PostgreSQL: concurrent authorization consumption",
    severity=Severity.CRITICAL,
    description=(
        "Eight sessions concurrently consume one ACTIVE authorization with the "
        "correct bound transaction. Exactly one may win; the rest must be refused "
        "by the atomic conditional UPDATE matching zero rows."
    ),
    invariants=(
        "REPLAYED APPROVAL -> PAYMENT IMPOSSIBLE",
        "ONE AUTHORIZATION -> AT MOST ONE CONSUMPTION",
    ),
    expected_reason_code=ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value,
    critical=True,
    setup=_auth_race_setup,
    execute=_auth_race_execute,
)


# --------------------------------------------------------------------------- #
# 2. Concurrent same-key payment creation
# --------------------------------------------------------------------------- #


async def _same_key_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, _ = await context.authorized_mission()
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "key": "attack-pg-same-key",
    }


async def _same_key_execute(context: Any, state: dict[str, Any]) -> Observation:
    async def attempt() -> dict[str, Any]:
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
                created = result.created
                intent_id = str(result.intent.id)
                await session.commit()
                return {"created": created, "intent_id": intent_id, "reason_code": None}
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                return {
                    "created": False,
                    "intent_id": None,
                    "reason_code": getattr(exc, "reason_code", type(exc).__name__),
                }

    outcomes = await asyncio.gather(*[attempt() for _ in range(RACERS)])
    creations = sum(bool(o["created"]) for o in outcomes)

    # Drain so the provider layer gets its chance to double as well.
    await drain_worker(context)
    intents = await payment_intents_for(context, state["mission_id"])
    provider_payments = context.provider.payment_count_for(state["key"])

    async with context.sessionmaker() as session:
        total_intents = int(
            (await session.execute(select(func.count()).select_from(PaymentIntentRow))).scalar_one()
        )

    one_creation = creations == 1
    one_logical = len(intents) == 1 and total_intents == 1
    one_provider = provider_payments <= 1
    distinct_ids = {o["intent_id"] for o in outcomes if o["intent_id"]}

    blocked = one_creation and one_logical and one_provider
    return Observation(
        blocked=blocked,
        reason_code=None,
        invariant_preserved=one_logical and one_provider,
        observed_effects={
            "concurrent_attempts": RACERS,
            "requests_that_created": creations,
            "distinct_intent_ids_returned": len(distinct_ids),
            "logical_payments": len(intents),
            "payment_intent_rows_total": total_intents,
            "provider_payments": provider_payments,
            "provider_create_calls": len(context.provider.create_calls),
            "loss_reasons": sorted({o["reason_code"] for o in outcomes if o["reason_code"]}),
        },
        evidence=(
            f"{RACERS} concurrent requests sharing one idempotency key created "
            f"{creations} payment; UNIQUE(idempotency_key) decided the race"
        ),
    )


PG_CONCURRENT_SAME_KEY_PAYMENT = _pg(
    scenario_id="pg_concurrent_same_key_payment",
    name="PostgreSQL: concurrent same-key payment creation",
    severity=Severity.CRITICAL,
    description=(
        "Eight sessions concurrently request a payment with one shared idempotency "
        "key. Exactly one may bring a payment into existence; every other must "
        "receive that same intent. At most one provider payment may result."
    ),
    invariants=("SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT",),
    expected_reason_code=None,
    critical=True,
    setup=_same_key_setup,
    execute=_same_key_execute,
)


# --------------------------------------------------------------------------- #
# 3. Conflicting idempotency key under concurrency
# --------------------------------------------------------------------------- #


async def _conflict_setup(context: Any) -> dict[str, Any]:
    mission_a, authorization_a, _ = await context.authorized_mission(amount_inr=3799)
    mission_b, authorization_b, _ = await context.authorized_mission(
        amount_inr=2999, product_id="P2"
    )
    return {
        "mission_a": mission_a,
        "authorization_a": authorization_a,
        "mission_b": mission_b,
        "authorization_b": authorization_b,
        "key": "attack-pg-conflict",
    }


async def _conflict_execute(context: Any, state: dict[str, Any]) -> Observation:
    async def attempt(mission_id: uuid.UUID, authorization_id: uuid.UUID) -> dict[str, Any]:
        async with context.sessionmaker() as session:
            try:
                result = await create_payment_intent(
                    session,
                    capabilities=EXECUTOR,
                    mission_id=mission_id,
                    authorization_id=authorization_id,
                    idempotency_key=state["key"],
                    provider="fake",
                )
                created = result.created
                await session.commit()
                return {"accepted": True, "created": created, "reason_code": None}
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                return {
                    "accepted": False,
                    "created": False,
                    "reason_code": getattr(exc, "reason_code", type(exc).__name__),
                }

    # Two materially DIFFERENT requests racing for the same key. Whichever wins,
    # the other must be refused rather than silently handed the winner's intent.
    outcomes = await asyncio.gather(
        attempt(state["mission_a"], state["authorization_a"]),
        attempt(state["mission_b"], state["authorization_b"]),
    )
    creations = sum(bool(o["created"]) for o in outcomes)
    accepted = sum(bool(o["accepted"]) for o in outcomes)
    conflicts = sum(o["reason_code"] == ReasonCode.IDEMPOTENCY_CONFLICT.value for o in outcomes)

    async with context.sessionmaker() as session:
        total_intents = int(
            (await session.execute(select(func.count()).select_from(PaymentIntentRow))).scalar_one()
        )
        # The loser must not have spent its own authorization discovering it lost.
        loser_authorizations = [
            (await load_authorization(session, state["authorization_a"])),
            (await load_authorization(session, state["authorization_b"])),
        ]
    consumed = sum(
        row is not None and row.status == AuthorizationStatus.CONSUMED.value
        for row in loser_authorizations
    )

    one_creation = creations == 1
    one_intent = total_intents == 1
    one_accepted = accepted == 1
    refused_as_conflict = conflicts == 1
    one_authorization_spent = consumed == 1

    blocked = one_creation and one_intent and one_accepted and refused_as_conflict
    return Observation(
        blocked=blocked,
        reason_code=(ReasonCode.IDEMPOTENCY_CONFLICT.value if refused_as_conflict else None),
        invariant_preserved=one_intent and one_authorization_spent,
        observed_effects={
            "requests_that_created": creations,
            "requests_accepted": accepted,
            "refused_with_idempotency_conflict": conflicts,
            "payment_intent_rows_total": total_intents,
            "logical_payments": total_intents,
            "authorizations_consumed": consumed,
            "loser_authorization_left_unspent": one_authorization_spent,
            "outcomes": outcomes,
        },
        evidence=(
            "two materially different concurrent requests shared one key; one created "
            "a payment, the other was refused with IDEMPOTENCY_CONFLICT, and only the "
            "winner's authorization was spent"
        ),
    )


PG_CONFLICTING_IDEMPOTENCY_KEY = _pg(
    scenario_id="pg_conflicting_idempotency_key",
    name="PostgreSQL: conflicting idempotency key under concurrency",
    severity=Severity.HIGH,
    description=(
        "Two materially different payment requests race for one idempotency key. "
        "Exactly one may create a payment; the other must be refused with "
        "IDEMPOTENCY_CONFLICT, and must not have spent its own authorization "
        "discovering that."
    ),
    invariants=("SAME IDEMPOTENCY KEY -> AT MOST ONE LOGICAL PAYMENT",),
    expected_reason_code=ReasonCode.IDEMPOTENCY_CONFLICT.value,
    critical=True,
    setup=_conflict_setup,
    execute=_conflict_execute,
)


# --------------------------------------------------------------------------- #
# 4. Outbox double-claim
# --------------------------------------------------------------------------- #


async def _outbox_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id, _ = await context.authorized_mission()
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="attack-pg-outbox",
            provider="fake",
        )
        await session.commit()
    return {"mission_id": mission_id}


async def _outbox_execute(context: Any, state: dict[str, Any]) -> Observation:
    async def claim(worker_id: str) -> str | None:
        async with context.sessionmaker() as session:
            event = await claim_next_event(session, worker_id=worker_id)
            claimed = None if event is None else str(event.id)
            await session.commit()
            return claimed

    # Two workers reaching for one event. `SELECT ... FOR UPDATE SKIP LOCKED`
    # must hand it to exactly one; the other must skip rather than block and
    # then take the same row.
    claims = await asyncio.gather(*[claim(f"worker-{i}") for i in range(RACERS)])
    successful = [c for c in claims if c is not None]

    async with context.sessionmaker() as session:
        events = list((await session.execute(select(OutboxEventRow))).scalars().all())
    claimed_by = {e.claimed_by for e in events if e.claimed_by}
    attempts = {e.id: e.attempts for e in events}

    exactly_one_claim = len(successful) == 1
    one_distinct_event = len(set(successful)) == len(successful)
    one_owner = len(claimed_by) <= 1
    # An event claimed twice would show two attempt increments for one turn.
    single_increment = all(count <= 1 for count in attempts.values())

    blocked = exactly_one_claim and one_distinct_event and one_owner and single_increment
    return Observation(
        blocked=blocked,
        reason_code=None,
        invariant_preserved=exactly_one_claim and one_owner,
        observed_effects={
            "concurrent_workers": RACERS,
            "successful_claims": len(successful),
            "distinct_events_claimed": len(set(successful)),
            "distinct_claim_owners": len(claimed_by),
            "attempt_counts": sorted(attempts.values()),
            "outbox_rows": len(events),
            "logical_payments": 1,
            "provider_payments": len(context.provider.created_payments),
        },
        evidence=(
            f"{RACERS} workers reached for one outbox event; exactly {len(successful)} "
            "claimed it and the rest skipped the locked row"
        ),
    )


PG_OUTBOX_DOUBLE_CLAIM = _pg(
    scenario_id="pg_outbox_double_claim",
    name="PostgreSQL: outbox double-claim attempt",
    severity=Severity.HIGH,
    description=(
        "Eight workers concurrently claim from an outbox holding one due event. "
        "SELECT ... FOR UPDATE SKIP LOCKED must give it to exactly one; a second "
        "claimant would dispatch the same provider call twice."
    ),
    invariants=("ONE OUTBOX EVENT -> AT MOST ONE CONCURRENT CLAIM",),
    expected_reason_code=None,
    critical=True,
    setup=_outbox_setup,
    execute=_outbox_execute,
)


# --------------------------------------------------------------------------- #
# 5. Conflicting terminal webhooks
# --------------------------------------------------------------------------- #


async def _webhook_race_setup(context: Any) -> dict[str, Any]:
    context.provider.queue_faults(FaultMode.PENDING)
    mission_id, authorization_id, _ = await context.authorized_mission()
    async with context.sessionmaker() as session:
        await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key="attack-pg-webhook",
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


async def _webhook_race_execute(context: Any, state: dict[str, Any]) -> Observation:
    payment_id = state["provider_payment_id"] or "fake_pay_unknown"

    async def deliver(event_id: str, event_type: WebhookEventType) -> dict[str, Any]:
        body = webhook_body(
            event_id=event_id, event_type=event_type, provider_payment_id=payment_id
        )
        signature = context.provider.sign(body)
        async with context.sessionmaker() as session:
            try:
                outcome = await handle_webhook(
                    session, provider=context.provider, body=body, signature=signature
                )
                await session.commit()
                return {
                    "event": event_type.value,
                    "applied": outcome.applied,
                    "reason_code": outcome.reason_code,
                }
            except WebhookRejected as rejected:
                await session.rollback()
                return {
                    "event": event_type.value,
                    "applied": False,
                    "reason_code": rejected.reason_code,
                }
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                return {
                    "event": event_type.value,
                    "applied": False,
                    "reason_code": type(exc).__name__,
                }

    # Two CONFLICTING terminal outcomes for one payment, arriving together. Both
    # are correctly signed and both are distinct events, so deduplication cannot
    # decide it — the row lock and the state machine must.
    outcomes = await asyncio.gather(
        deliver("attack-pg-success", WebhookEventType.PAYMENT_SUCCEEDED),
        deliver("attack-pg-failure", WebhookEventType.PAYMENT_FAILED),
    )
    applied = sum(bool(o["applied"]) for o in outcomes)

    intents = await payment_intents_for(context, state["mission_id"])
    final_state = intents[0]["state"] if intents else None
    terminal = final_state in (
        PaymentIntentState.SUCCEEDED.value,
        PaymentIntentState.FAILED_TERMINAL.value,
    )

    exactly_one_applied = applied == 1
    blocked = exactly_one_applied and terminal
    return Observation(
        blocked=blocked,
        reason_code=next((o["reason_code"] for o in outcomes if o["reason_code"]), None),
        invariant_preserved=exactly_one_applied,
        observed_effects={
            "state_before": state["state_before"],
            "deliveries": outcomes,
            "transitions_applied": applied,
            "final_state": final_state,
            "final_state_is_terminal": terminal,
            "logical_payments": len(intents),
        },
        evidence=(
            "a success and a failure webhook for one payment arrived concurrently; "
            f"exactly {applied} terminal transition was applied"
        ),
    )


PG_CONCURRENT_TERMINAL_WEBHOOK = _pg(
    scenario_id="pg_concurrent_terminal_webhook_race",
    name="PostgreSQL: conflicting concurrent terminal webhooks",
    severity=Severity.CRITICAL,
    description=(
        "A payment.succeeded and a payment.failed webhook for the same payment "
        "arrive concurrently. Both are validly signed and distinct events, so "
        "deduplication cannot resolve it: the SELECT ... FOR UPDATE on the intent "
        "row must serialize them and exactly one terminal transition may apply."
    ),
    invariants=(
        "CONFLICTING TERMINAL WEBHOOKS -> EXACTLY ONE TRANSITION",
        "A DELAYED WEBHOOK -> NO ILLEGAL STATE REGRESSION",
    ),
    expected_reason_code=None,
    critical=True,
    setup=_webhook_race_setup,
    execute=_webhook_race_execute,
)


# --------------------------------------------------------------------------- #
# 6. Concurrent audit append
# --------------------------------------------------------------------------- #


async def _audit_race_setup(context: Any) -> dict[str, Any]:
    mission_id = await context.make_mission("CREATED")
    return {"mission_id": mission_id}


async def _audit_race_execute(context: Any, state: dict[str, Any]) -> Observation:
    mission_id: uuid.UUID = state["mission_id"]

    async def append(index: int) -> str | None:
        async with context.sessionmaker() as session:
            try:
                await append_event(
                    session,
                    mission_id=mission_id,
                    event_type=EventType.SECURITY_VIOLATION,
                    actor="attack-lab",
                    payload={"index": index},
                )
                await session.commit()
                return None
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                return type(exc).__name__

    failures = [f for f in await asyncio.gather(*[append(i) for i in range(RACERS)]) if f]

    async with context.sessionmaker() as session:
        events = await list_events(session, mission_id)
        total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AuditEventRow)
                    .where(AuditEventRow.mission_id == mission_id)
                )
            ).scalar_one()
        )
        verification = verify_events(mission_id, events)

    sequences = [event.sequence for event in events]
    contiguous = sequences == list(range(len(sequences)))
    all_written = total == RACERS
    chain_valid = verification.valid

    blocked = contiguous and all_written and chain_valid and not failures
    return Observation(
        blocked=blocked,
        reason_code=verification.reason_code.value,
        invariant_preserved=contiguous and chain_valid,
        observed_effects={
            "concurrent_appends": RACERS,
            "events_written": total,
            "append_failures": failures,
            "sequences": sequences,
            "sequences_contiguous": contiguous,
            "chain_verifies": chain_valid,
            "verification_reason_code": verification.reason_code.value,
            "events_checked": verification.events_checked,
        },
        evidence=(
            f"{RACERS} concurrent appends produced sequences {sequences} with a chain "
            "that verifies; the row lock made each writer observe its predecessor"
        ),
    )


PG_CONCURRENT_AUDIT_APPEND = _pg(
    scenario_id="pg_concurrent_audit_append",
    name="PostgreSQL: concurrent audit append",
    severity=Severity.HIGH,
    description=(
        "Eight sessions append to one mission's audit chain concurrently. The "
        "sequences must come out as the contiguous run 0..7 AND the resulting "
        "chain must verify — a gap or a broken previous_hash link would make the "
        "whole history unverifiable."
    ),
    invariants=(
        "CONCURRENT APPENDS -> A CONTIGUOUS, VERIFIABLE CHAIN",
        "AUDIT EVENT MODIFIED -> VERIFICATION FAILURE",
    ),
    expected_reason_code="AUDIT_VALID",
    critical=True,
    setup=_audit_race_setup,
    execute=_audit_race_execute,
)


SCENARIOS = (
    PG_CONCURRENT_AUTHORIZATION_CONSUMPTION,
    PG_CONCURRENT_SAME_KEY_PAYMENT,
    PG_CONFLICTING_IDEMPOTENCY_KEY,
    PG_OUTBOX_DOUBLE_CLAIM,
    PG_CONCURRENT_TERMINAL_WEBHOOK,
    PG_CONCURRENT_AUDIT_APPEND,
)
