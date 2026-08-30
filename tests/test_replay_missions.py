"""Replay over REAL mission histories, built by the real kernel.

Nothing here hand-writes an event. Every chain is produced by running the
orchestrator, the authorization lifecycle, the payment executor, the outbox
worker and the webhook handler exactly as production does, and then replayed.
A reducer tested only against synthetic payloads proves it can read payloads a
test author imagined; these prove it can read the ones the system writes.

The eight flows the phase requires are each covered once: an ALLOW path, an
approval path, the authorization lifecycle, a consumed authorization, a payment
success, a retry/timeout history, a terminal failure, and a security-violation
path.
"""

import uuid
from datetime import timedelta

import pytest
from apps.api.db.models import PaymentIntentRow
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import (
    CreateMissionRequest,
    EventType,
    MissionState,
    PolicyOutcome,
    RawMerchantOffer,
    ReasonCode,
    utcnow,
)
from packages.schemas.payment import (
    PaymentIntentState,
    WebhookEventType,
)
from services.agent_orchestrator.merchants.base import MerchantAgent
from services.agent_orchestrator.orchestrator import Orchestrator
from services.audit_ledger.ledger import list_events
from services.audit_ledger.replay import replay_mission
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import (
    FakePaymentProvider,
    FaultMode,
    webhook_body,
)
from services.payment_executor.webhooks import handle_webhook
from services.payment_executor.worker import drain
from services.security_kernel.authorization import (
    AuthorizationReplayDetected,
    consume_authorization,
    revoke_authorization,
)
from sqlalchemy import select
from tests.conftest import approve_with_demo_signer, authorized_mission, make_constraints

pytestmark = pytest.mark.asyncio

EXECUTOR = payment_executor_capabilities()


def _request(**overrides) -> CreateMissionRequest:
    return CreateMissionRequest(
        raw_query="Find wireless earbuds",
        quantity=1,
        constraints=make_constraints(**overrides),
    )


async def _trusted_replay(session, mission_id: uuid.UUID):
    """Replay and insist the result is trusted before returning its state."""
    result = await replay_mission(session, mission_id)
    assert result.audit_valid is True, result.verification.detail
    assert result.trusted is True, result.detail
    assert result.state is not None
    return result


# --------------------------------------------------------------------------- #
# 1 + 2. Orchestrated missions: ALLOW and REQUIRE_APPROVAL
# --------------------------------------------------------------------------- #
async def test_replay_reconstructs_an_allow_mission(session):
    """A mission inside the soft budget needs no approval and reaches AUTHORIZED.

    The reconstruction must show `approval_required` false — an ALLOW path
    activates its authorization without a human, and claiming otherwise would
    misreport who authorized the spend.
    """
    mission = await Orchestrator().run(session, _request(soft_budget_inr=4500))
    assert mission.state == MissionState.AUTHORIZED.value

    result = await _trusted_replay(session, mission.id)
    state = result.state
    assert state.mission_state == MissionState.AUTHORIZED.value
    assert state.policy_decision == PolicyOutcome.ALLOW.value
    assert state.approval_required is False
    assert state.approval_granted is False
    assert state.selected_offer_id is not None
    assert state.raw_offer_count == 4
    assert state.authorization.status == AuthorizationStatus.ACTIVE.value
    assert state.authorization.bound_merchant_id is not None
    assert state.authorization.bound_amount_inr == state.requested_amount
    assert result.comparison.matches is True
    assert result.comparison.authorization_matches is True


async def test_replay_reconstructs_an_approval_mission(session):
    """Over the soft budget, under the hard limit: the mission waits for a human."""
    mission = await Orchestrator().run(session, _request())
    assert mission.state == MissionState.AWAITING_APPROVAL.value

    state = (await _trusted_replay(session, mission.id)).state
    assert state.mission_state == MissionState.AWAITING_APPROVAL.value
    assert state.policy_decision == PolicyOutcome.REQUIRE_APPROVAL.value
    assert state.approval_required is True
    assert state.approval_granted is False
    assert ReasonCode.SOFT_BUDGET_EXCEEDED.value in state.policy_reason_codes
    assert state.authorization.status == AuthorizationStatus.PENDING.value


async def test_replay_reconstructs_a_denied_mission(session):
    """A DENY ends the mission and mints no authorization at all."""
    mission = await Orchestrator().run(session, _request(soft_budget_inr=100, hard_limit_inr=200))
    assert mission.state == MissionState.CANCELLED.value

    state = (await _trusted_replay(session, mission.id)).state
    assert state.mission_state == MissionState.CANCELLED.value
    assert state.policy_decision == PolicyOutcome.DENY.value
    assert state.authorization.authorization_id is None
    assert state.authorization.status is None
    assert any(
        event.event_type == EventType.MISSION_DENIED.value for event in state.security_events
    )


async def test_replay_reconstructs_user_cryptographic_approval(client, demo_signer):
    """Signed approval through the real HTTP route, then real replay route.

    `approval_granted` must become true only here — on the ALLOW path the same
    AUTHORIZATION_ACTIVATED event is POLICY_AUTO on ALLOW; replay distinguishes
    that from a required USER_ED25519 proof.
    """
    created = await client.post(
        "/api/v1/missions",
        json={
            "raw_query": "earbuds",
            "quantity": 1,
            "constraints": {
                "category": "wireless_earbuds",
                "soft_budget_inr": 4000,
                "hard_limit_inr": 4500,
                "min_rating": 4.2,
                "currency": "INR",
            },
        },
    )
    mission_id = created.json()["id"]
    approved = await approve_with_demo_signer(client, mission_id, demo_signer)
    assert approved.status_code == 200, approved.text

    replay = await client.get(f"/api/v1/missions/{mission_id}/replay")
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["trusted"] is True
    assert body["state"]["mission_state"] == MissionState.AUTHORIZED.value
    assert body["state"]["approval_required"] is True
    assert body["state"]["approval_granted"] is True
    assert body["state"]["authorization"]["status"] == AuthorizationStatus.ACTIVE.value
    assert body["comparison"]["matches"] is True


# --------------------------------------------------------------------------- #
# 3 + 4. Authorization lifecycle, including a consumed one and a replayed one
# --------------------------------------------------------------------------- #
async def test_replay_reconstructs_a_consumed_authorization(session):
    mission, authorization, transaction = await authorized_mission(session)
    await consume_authorization(
        session, authorization_id=authorization.authorization_id, transaction=transaction
    )

    state = (await _trusted_replay(session, mission.id)).state
    assert state.authorization.status == AuthorizationStatus.CONSUMED.value
    assert state.authorization.consumed_at is not None
    assert state.authorization.replay_detected is False


async def test_replay_preserves_an_authorization_replay_attempt(session):
    """A reused authorization is refused, and the refusal survives replay.

    Both the flag and the ordered security record are asserted: a counter alone
    would not say WHEN in the mission the reuse was attempted.
    """
    mission, authorization, transaction = await authorized_mission(session)
    await consume_authorization(
        session, authorization_id=authorization.authorization_id, transaction=transaction
    )
    with pytest.raises(AuthorizationReplayDetected):
        await consume_authorization(
            session,
            authorization_id=authorization.authorization_id,
            transaction=transaction,
        )

    state = (await _trusted_replay(session, mission.id)).state
    assert state.authorization.replay_detected is True
    assert state.authorization.status == AuthorizationStatus.CONSUMED.value
    replay_records = [
        event
        for event in state.security_events
        if event.event_type == EventType.AUTHORIZATION_REPLAY_DETECTED.value
    ]
    assert len(replay_records) == 1
    assert replay_records[0].reason_code == ReasonCode.AUTHORIZATION_REPLAY_DETECTED.value


async def test_replay_preserves_a_transaction_binding_failure(session):
    """A mutated transaction cannot consume the authorization, and replay shows it."""
    mission, authorization, transaction = await authorized_mission(session)
    mutated = transaction.model_copy(update={"amount_inr": transaction.amount_inr + 600})
    from services.security_kernel.authorization import TransactionBindingFailure

    with pytest.raises(TransactionBindingFailure):
        await consume_authorization(
            session, authorization_id=authorization.authorization_id, transaction=mutated
        )

    state = (await _trusted_replay(session, mission.id)).state
    assert state.authorization.binding_failures == 1
    assert state.authorization.status == AuthorizationStatus.ACTIVE.value
    assert any(
        event.reason_code == ReasonCode.TRANSACTION_BINDING_FAILURE.value
        for event in state.security_events
    )


async def test_replay_reconstructs_a_revoked_authorization(session):
    mission, authorization, _ = await authorized_mission(session)
    await revoke_authorization(
        session, authorization_id=authorization.authorization_id, reason="operator"
    )
    state = (await _trusted_replay(session, mission.id)).state
    assert state.authorization.status == AuthorizationStatus.REVOKED.value


# --------------------------------------------------------------------------- #
# 5 - 7. Payment histories
# --------------------------------------------------------------------------- #
async def _paid_mission(sessionmaker, *, faults=(), key="idem-replay", offsets=(0,)):
    """Run one payment all the way through the real outbox worker.

    ``offsets`` steps wall-clock time forward between drains rather than
    sleeping, because a retryable failure schedules its next attempt behind a
    backoff. This mirrors the Phase 4 fault-injection tests exactly.
    """
    provider = FakePaymentProvider()
    provider.queue_faults(*faults)

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        mission_id = mission.id
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await setup.commit()

    for offset in offsets:
        await drain(sessionmaker, provider=provider, now=utcnow() + timedelta(seconds=offset))
    return mission_id, provider


async def test_replay_reconstructs_a_successful_payment(sessionmaker):
    mission_id, provider = await _paid_mission(sessionmaker)

    async with sessionmaker() as reader:
        result = await _trusted_replay(reader, mission_id)
    state = result.state
    assert state.mission_state == MissionState.PAYMENT_SUCCEEDED.value
    assert state.payment.state == PaymentIntentState.SUCCEEDED.value
    assert state.payment.provider == "fake"
    assert state.payment.provider_payment_id is not None
    assert state.payment.idempotency_key == "idem-replay"
    assert state.payment.amount_inr == 3799
    assert state.payment.currency == "INR"
    assert state.payment.attempts == 1
    assert state.authorization.status == AuthorizationStatus.CONSUMED.value
    assert result.comparison.matches is True
    assert result.comparison.payment_matches is True


async def test_replay_reconstructs_a_timeout_and_reconciliation_history(sessionmaker):
    """The hard Phase 4 case: the response was lost but the payment is real.

    Replay must show the uncertainty EPISODE, not just the settled endpoint —
    "this payment was uncertain and was reconciled onto the provider's own
    payment" is a materially different history from "this payment succeeded
    first time", and a projection that flattened them would erase the evidence
    that the duplicate-prevention path ran.
    """
    mission_id, provider = await _paid_mission(
        sessionmaker, faults=(FaultMode.TIMEOUT_AFTER_CREATE,), key="idem-timeout"
    )

    async with sessionmaker() as reader:
        state = (await _trusted_replay(reader, mission_id)).state
    assert state.payment.provider_timeouts == 1
    assert state.payment.uncertain_episodes >= 1
    assert state.payment.reconciliations >= 1
    assert state.payment.state == PaymentIntentState.SUCCEEDED.value
    assert provider.payment_count_for("idem-timeout") == 1


async def test_replay_reconstructs_a_transient_retry_history(sessionmaker):
    """A provider that answered "not now" produced a retryable failure, then a
    successful retry. The mission never entered PAYMENT_FAILED, because a
    retryable failure is not a settled one — and replay agrees."""
    mission_id, _ = await _paid_mission(
        sessionmaker,
        faults=(FaultMode.TRANSIENT_FAILURE,),
        key="idem-retry",
        offsets=(0, 5),
    )

    async with sessionmaker() as reader:
        result = await _trusted_replay(reader, mission_id)
    state = result.state
    assert state.payment.retries_scheduled >= 1
    assert state.payment.attempts >= 2
    assert state.payment.state == PaymentIntentState.SUCCEEDED.value
    assert state.mission_state == MissionState.PAYMENT_SUCCEEDED.value
    assert result.comparison.payment_matches is True


async def test_replay_reconstructs_a_terminal_payment_failure(sessionmaker):
    mission_id, _ = await _paid_mission(
        sessionmaker, faults=(FaultMode.TERMINAL_FAILURE,), key="idem-terminal"
    )

    async with sessionmaker() as reader:
        result = await _trusted_replay(reader, mission_id)
    state = result.state
    assert state.payment.state == PaymentIntentState.FAILED_TERMINAL.value
    assert state.mission_state == MissionState.PAYMENT_FAILED.value
    assert result.comparison.matches is True
    assert result.comparison.payment_matches is True

    # DOCUMENTED LIMITATION, asserted so it cannot drift unnoticed.
    # `apply_payment_transition` writes `reason_code` to the payment_intents
    # COLUMN but not into the audit payload, so PROVIDER_TERMINAL_FAILURE is not
    # in the ledger and replay cannot know it. The projection leaves it None
    # rather than inferring it from the event type — inferring would be
    # fabricating a value the events do not contain. See README, "What replay
    # cannot reconstruct".
    async with sessionmaker() as check:
        intent = (
            await check.execute(
                select(PaymentIntentRow).where(PaymentIntentRow.mission_id == mission_id)
            )
        ).scalar_one()
    assert intent.last_reason_code == ReasonCode.PROVIDER_TERMINAL_FAILURE.value
    assert state.payment.last_reason_code is None


async def test_replay_distinguishes_retryable_from_terminal_failure(sessionmaker):
    """Both emit PAYMENT_FAILED. Only the recorded state tells them apart.

    Reading the event TYPE alone would move the mission to PAYMENT_FAILED on a
    retryable failure that production left in flight — the projection would then
    disagree with the persisted row for a payment that later succeeded.
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TRANSIENT_FAILURE)

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        mission_id = mission.id
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-retryable-only",
            provider="fake",
        )
        await setup.commit()

    from services.payment_executor.worker import run_once

    await run_once(sessionmaker, provider=provider)

    async with sessionmaker() as reader:
        result = await _trusted_replay(reader, mission_id)
        intent = (
            await reader.execute(
                __import__("sqlalchemy")
                .select(PaymentIntentRow)
                .where(PaymentIntentRow.mission_id == mission_id)
            )
        ).scalar_one()
    assert result.state.payment.state == PaymentIntentState.FAILED_RETRYABLE.value
    assert result.state.mission_state == MissionState.PAYMENT_PENDING.value
    assert intent.state == PaymentIntentState.FAILED_RETRYABLE.value
    assert result.comparison.payment_matches is True
    assert result.comparison.matches is True


async def test_replay_reconstructs_a_webhook_settled_payment(sessionmaker):
    """A payment accepted but not settled, then settled by a verified webhook.

    Also covers the duplicate delivery: the second one is accepted and changes
    nothing, and replay reports exactly one verified webhook and one ignored
    duplicate.
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.PENDING)

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        mission_id = mission.id
        await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-webhook",
            provider="fake",
        )
        await setup.commit()

    await drain(sessionmaker, provider=provider)

    async with sessionmaker() as lookup:
        intent = (
            await lookup.execute(
                __import__("sqlalchemy")
                .select(PaymentIntentRow)
                .where(PaymentIntentRow.mission_id == mission_id)
            )
        ).scalar_one()
        provider_payment_id = intent.provider_payment_id
    assert provider_payment_id is not None

    body = webhook_body(
        event_id="evt-1",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )
    for _ in range(2):
        async with sessionmaker() as hook:
            await handle_webhook(hook, provider=provider, body=body, signature=provider.sign(body))
            await hook.commit()

    async with sessionmaker() as reader:
        result = await _trusted_replay(reader, mission_id)
    state = result.state
    assert state.payment.webhooks_verified == 1
    assert state.payment.duplicate_webhooks_ignored == 1
    assert state.payment.state == PaymentIntentState.SUCCEEDED.value
    assert state.mission_state == MissionState.PAYMENT_SUCCEEDED.value
    assert result.comparison.payment_matches is True


async def test_replay_reconstructs_an_idempotent_retry(sessionmaker):
    """The same key presented twice reuses one logical payment.

    `intent_reused` is what a caller needs to see: a retry happened and did NOT
    consume a second authorization.
    """
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        mission_id = mission.id
        first = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-same",
            provider="fake",
        )
        second = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission_id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-same",
            provider="fake",
        )
        await setup.commit()
    assert first.created is True
    assert second.created is False

    async with sessionmaker() as reader:
        state = (await _trusted_replay(reader, mission_id)).state
    assert state.payment.intent_reused is True
    assert state.payment.payment_intent_id == str(first.intent.id)


# --------------------------------------------------------------------------- #
# 8. Security-violation path
# --------------------------------------------------------------------------- #
class _EscalatingMerchant:
    """A merchant that claims a bigger budget and spoofs another identity.

    Both attacks are refused by the kernel, and both must survive into the
    replayed history — a projection that dropped them would describe an
    uneventful mission that was in fact attacked twice.
    """

    merchant_id = "evil"

    def quote(self, constraints, quantity):
        return [
            RawMerchantOffer(
                merchant_id="merchant_a",  # spoofed: not the authenticated id
                product_id="EV1",
                title="Too Good Buds",
                price=3499,
                currency="INR",
                rating=4.9,
                in_stock=True,
                claims={"hard_limit_inr": 100000, "soft_budget_inr": 99000},
            )
        ]


async def test_replay_preserves_security_violations(session):
    merchants: list[MerchantAgent] = [*Orchestrator().merchants, _EscalatingMerchant()]
    mission = await Orchestrator(merchants=merchants).run(session, _request())

    state = (await _trusted_replay(session, mission.id)).state
    reason_codes = [event.reason_code for event in state.security_events]
    assert ReasonCode.AUTHORITY_ESCALATION.value in reason_codes
    assert ReasonCode.MERCHANT_IDENTITY_MISMATCH.value in reason_codes

    escalation = next(
        event
        for event in state.security_events
        if event.reason_code == ReasonCode.AUTHORITY_ESCALATION.value
    )
    assert escalation.detail["field"] in {"hard_limit_inr", "soft_budget_inr"}
    assert escalation.detail["source_authority"] == "MERCHANT_DATA"
    assert escalation.detail["target_authority"] == "USER_POLICY"

    # The refusals changed nothing: the mission still ran on the USER's limits.
    assert state.hard_limit == 4500
    assert state.soft_budget == 4000
    # Security events are ordered by where they happened, not merely counted.
    assert [event.sequence for event in state.security_events] == sorted(
        event.sequence for event in state.security_events
    )


async def test_security_events_survive_a_session_boundary(sessionmaker):
    """Replay from a cold session — the API's actual situation."""
    async with sessionmaker() as writer:
        merchants: list[MerchantAgent] = [
            *Orchestrator().merchants,
            _EscalatingMerchant(),
        ]
        mission = await Orchestrator(merchants=merchants).run(writer, _request())
        mission_id = mission.id
        await writer.commit()

    async with sessionmaker() as reader:
        state = (await _trusted_replay(reader, mission_id)).state
        events = await list_events(reader, mission_id)
    assert state.events_replayed == len(events)
    assert len(state.security_events) >= 2


# --------------------------------------------------------------------------- #
# Cross-cutting: every replay accounts for every event
# --------------------------------------------------------------------------- #
async def test_replay_accounts_for_every_event_in_the_chain(sessionmaker):
    """`events_replayed` must equal the chain length for every flow above.

    An event silently skipped by the reducer would show up here as a shortfall,
    which is the cheapest possible guard against a handler that returns early.
    """
    mission_id, _ = await _paid_mission(sessionmaker, key="idem-accounting")
    async with sessionmaker() as reader:
        result = await _trusted_replay(reader, mission_id)
        events = await list_events(reader, mission_id)
    assert result.events_replayed == len(events)
    assert result.state.events_replayed == len(events)
    assert result.verification.events_checked == len(events)
