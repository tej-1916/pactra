"""Authored mechanism coverage for LOCAL CRYPTOGRAPHIC APPROVAL PROOF.

These four scenarios exercise the real verifier and measure durable effects.
They are Attack Lab regression cases, not independent security validation and
not additions to the pinned Phase 6 canonical benchmark.
"""

from __future__ import annotations

from typing import Any

from apps.api.db.models import AuthorizationRow, Mission, OutboxEventRow, PaymentIntentRow
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import MissionState, ReasonCode, as_utc
from sqlalchemy import select, text, update

from services.attack_lab.models import AttackCategory, AttackScenario, Observation, Severity
from services.attack_lab.scenarios._helpers import constraints, effect_delta, run_mission
from services.payment_executor.executor import dispatch_create
from services.payment_executor.intents import create_payment_intent
from services.security_kernel.authorization import (
    AuthorizationProofFailure,
    approve_authorization_with_signature,
    authorization_for_mission,
)

EXECUTOR = payment_executor_capabilities()


async def _pending_mission(context: Any) -> tuple[Any, Any]:
    from services.agent_orchestrator.merchants.mock_merchants import MockMerchantA

    mission_id = await run_mission(
        context,
        merchants=[MockMerchantA()],
        mission_constraints=constraints(soft_budget_inr=4000, hard_limit_inr=4500),
    )
    async with context.sessionmaker() as session:
        row = await authorization_for_mission(session, mission_id)
        if row is None:  # pragma: no cover - scenario wiring
            raise RuntimeError("REQUIRE_APPROVAL mission produced no authorization")
        return mission_id, row.authorization_id


async def _status(context: Any, authorization_id: Any) -> str | None:
    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, authorization_id)
        return None if row is None else row.status


async def _forged_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id = await _pending_mission(context)
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "census": await context.census(),
    }


async def _forged_execute(context: Any, state: dict[str, Any]) -> Observation:
    reason: str | None = None
    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, state["authorization_id"])
        if row is None:  # pragma: no cover
            raise RuntimeError("authorization vanished")
        correct_signature = context.demo_approval_signature(row)
        # Signatures are fixed-size; XORing one byte preserves strict encoding
        # while making the real proof cryptographically invalid.
        forged_signature = (
            bytes([bytes.fromhex(correct_signature)[0] ^ 1]) + bytes.fromhex(correct_signature)[1:]
        )
        try:
            await approve_authorization_with_signature(
                session,
                mission_id=row.mission_id,
                authorization_id=row.authorization_id,
                signing_key_id=context.demo_approver_signing_key_id,
                signature_hex=forged_signature.hex(),
            )
        except AuthorizationProofFailure as failure:
            reason = failure.reason_code
        await session.commit()
    after = await context.census()
    delta = effect_delta(state["census"], after)
    pending = await _status(context, state["authorization_id"]) == AuthorizationStatus.PENDING.value
    blocked = reason == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value and pending
    return Observation(
        blocked=blocked,
        reason_code=reason,
        invariant_preserved=pending and delta["payment_intents"] == 0,
        observed_effects={
            "authorization_still_pending": pending,
            "payment_intents_created": delta["payment_intents"],
            "outbox_events_created": delta["outbox_events"],
        },
        evidence="A forged fixed-length Ed25519 signature left the authorization PENDING.",
    )


async def _cross_setup(context: Any) -> dict[str, Any]:
    mission_a, authorization_a = await _pending_mission(context)
    mission_b, authorization_b = await _pending_mission(context)
    async with context.sessionmaker() as session:
        row_a = await session.get(AuthorizationRow, authorization_a)
        if row_a is None:  # pragma: no cover
            raise RuntimeError("source authorization vanished")
        copied_signature = context.demo_approval_signature(row_a)
    return {
        "mission_a": mission_a,
        "mission_b": mission_b,
        "authorization_a": authorization_a,
        "authorization_b": authorization_b,
        "copied_signature": copied_signature,
        "census": await context.census(),
    }


async def _cross_execute(context: Any, state: dict[str, Any]) -> Observation:
    reason: str | None = None
    async with context.sessionmaker() as session:
        try:
            await approve_authorization_with_signature(
                session,
                mission_id=state["mission_b"],
                authorization_id=state["authorization_b"],
                signing_key_id=context.demo_approver_signing_key_id,
                signature_hex=state["copied_signature"],
            )
        except AuthorizationProofFailure as failure:
            reason = failure.reason_code
        await session.commit()
    pending = await _status(context, state["authorization_b"]) == AuthorizationStatus.PENDING.value
    after = await context.census()
    delta = effect_delta(state["census"], after)
    return Observation(
        blocked=reason == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value and pending,
        reason_code=reason,
        invariant_preserved=pending and delta["payment_intents"] == 0,
        observed_effects={
            "target_authorization_still_pending": pending,
            "cross_mission_copy_refused": reason
            == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value,
            "payment_intents_created": delta["payment_intents"],
        },
        evidence="A proof copied to another authorization and mission did not activate it.",
    )


async def _mutation_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id = await _pending_mission(context)
    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, authorization_id)
        if row is None:  # pragma: no cover
            raise RuntimeError("authorization vanished")
        signature = context.demo_approval_signature(row)
    return {
        "mission_id": mission_id,
        "authorization_id": authorization_id,
        "signature": signature,
        "census": await context.census(),
    }


async def _mutation_execute(context: Any, state: dict[str, Any]) -> Observation:
    reason: str | None = None
    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, state["authorization_id"])
        if row is None:  # pragma: no cover
            raise RuntimeError("authorization vanished")
        row.bound_amount_inr += 1
        # Recompute the Phase 3 digest for the mutated durable transaction.
        from packages.schemas.transaction import BoundTransaction

        mutated = BoundTransaction(
            merchant_id=row.bound_merchant_id,
            product_id=row.bound_product_id,
            quantity=row.bound_quantity,
            amount_inr=row.bound_amount_inr,
            currency=row.bound_currency,
            policy_version=row.policy_version,
            offer_version=row.offer_version,
            expires_at=as_utc(row.expires_at),
            nonce=row.nonce,
        )
        row.transaction_digest = mutated.digest()
        await session.flush()
        try:
            await approve_authorization_with_signature(
                session,
                mission_id=row.mission_id,
                authorization_id=row.authorization_id,
                signing_key_id=context.demo_approver_signing_key_id,
                signature_hex=state["signature"],
            )
        except AuthorizationProofFailure as failure:
            reason = failure.reason_code
        await session.commit()
    pending = await _status(context, state["authorization_id"]) == AuthorizationStatus.PENDING.value
    after = await context.census()
    delta = effect_delta(state["census"], after)
    return Observation(
        blocked=reason == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value and pending,
        reason_code=reason,
        invariant_preserved=pending and delta["payment_intents"] == 0,
        observed_effects={
            "authorization_still_pending": pending,
            "post_signature_amount_mutation_refused": reason
            == ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value,
            "payment_intents_created": delta["payment_intents"],
        },
        evidence="Changing amount and recomputing the Phase 3 digest invalidated the user proof.",
    )


async def _proof_removal_setup(context: Any) -> dict[str, Any]:
    mission_id, authorization_id = await _pending_mission(context)
    async with context.sessionmaker() as session:
        row = await session.get(AuthorizationRow, authorization_id)
        mission = await session.get(Mission, mission_id)
        if row is None or mission is None:  # pragma: no cover
            raise RuntimeError("signed-approval setup vanished")
        await context.approve_pending_user_authorization(session, row)
        mission.state = MissionState.AUTHORIZED.value
        result = await create_payment_intent(
            session,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization_id,
            idempotency_key=f"signed-proof-removal-{mission_id}",
            provider="fake",
        )
        event = (
            await session.execute(
                select(OutboxEventRow).where(OutboxEventRow.payment_intent_id == result.intent.id)
            )
        ).scalar_one()
        await session.commit()
        return {
            "authorization_id": authorization_id,
            "intent_id": result.intent.id,
            "event_id": event.id,
            "census": await context.census(),
        }


async def _proof_removal_execute(context: Any, state: dict[str, Any]) -> Observation:
    async with context.sessionmaker() as session:
        await session.execute(text("PRAGMA ignore_check_constraints = ON"))
        await session.execute(
            update(AuthorizationRow)
            .where(AuthorizationRow.authorization_id == state["authorization_id"])
            .values(signing_key_id=None, approval_signature=None)
        )
        await session.execute(text("PRAGMA ignore_check_constraints = OFF"))
        await session.commit()

    reason: str | None = None
    provider = context.provider
    async with context.sessionmaker() as session:
        intent = await session.get(PaymentIntentRow, state["intent_id"])
        event = await session.get(OutboxEventRow, state["event_id"])
        if intent is None or event is None:  # pragma: no cover
            raise RuntimeError("queued payment vanished")
        try:
            await dispatch_create(
                session,
                capabilities=EXECUTOR,
                provider=provider,
                intent=intent,
                event=event,
            )
        except AuthorizationProofFailure as failure:
            reason = failure.reason_code
        await session.rollback()
    provider_calls = len(provider.get_calls) + len(provider.create_calls)
    after = await context.census()
    return Observation(
        blocked=reason == ReasonCode.AUTHORIZATION_PROOF_MISSING.value and provider_calls == 0,
        reason_code=reason,
        invariant_preserved=provider_calls == 0,
        observed_effects={
            "provider_lookup_calls": len(provider.get_calls),
            "provider_create_calls": len(provider.create_calls),
            "payment_intents_after": after["payment_intents"],
        },
        evidence="Removing the durable proof after queueing caused zero provider I/O.",
    )


FORGED_SIGNATURE = AttackScenario(
    id="signed_approval_forged_signature",
    name="Signed approval: forged signature",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description="A corrupted Ed25519 proof is submitted for the exact pending challenge.",
    target_invariants=("FORGED SIGNATURE -> AUTHORIZATION REMAINS PENDING",),
    expected_reason_code=ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value,
    critical=True,
    setup=_forged_setup,
    execute=_forged_execute,
)

CROSS_MISSION_REPLAY = AttackScenario(
    id="signed_approval_cross_mission_replay",
    name="Signed approval: cross-mission replay",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description="A valid proof for one mission and authorization is copied to another.",
    target_invariants=("SIGNATURE COPY -> DIFFERENT MISSION/AUTHORIZATION REFUSED",),
    expected_reason_code=ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value,
    critical=True,
    setup=_cross_setup,
    execute=_cross_execute,
)

POST_SIGNATURE_MUTATION = AttackScenario(
    id="signed_approval_post_signature_mutation",
    name="Signed approval: post-signature transaction mutation",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description="Amount and transaction digest are changed after the user signs.",
    target_invariants=("POST-SIGNATURE TRANSACTION MUTATION -> APPROVAL REFUSED",),
    expected_reason_code=ReasonCode.AUTHORIZATION_SIGNATURE_INVALID.value,
    critical=True,
    setup=_mutation_setup,
    execute=_mutation_execute,
)

PROOF_REMOVAL_BEFORE_EXECUTOR = AttackScenario(
    id="signed_approval_proof_removal",
    name="Signed approval: proof removal before executor",
    category=AttackCategory.TRANSACTION,
    severity=Severity.CRITICAL,
    description="The durable proof is removed after queueing but before provider dispatch.",
    target_invariants=("MISSING PROOF -> ZERO PROVIDER I/O",),
    expected_reason_code=ReasonCode.AUTHORIZATION_PROOF_MISSING.value,
    critical=True,
    setup=_proof_removal_setup,
    execute=_proof_removal_execute,
)

SCENARIOS = (
    FORGED_SIGNATURE,
    CROSS_MISSION_REPLAY,
    POST_SIGNATURE_MUTATION,
    PROOF_REMOVAL_BEFORE_EXECUTOR,
)
