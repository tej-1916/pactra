"""Webhook security and idempotency.

The ordering rule under test: VERIFY, then resolve the payment from server-side
state, then deduplicate, then apply only what the state machine permits. Nothing
in the payload is read as state before the MAC checks out, and nothing in the
payload names the amount, merchant, or authorization — a verified-but-hostile
webhook can point at a payment, never redefine one.
"""

import pytest
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import EventType
from packages.schemas.payment import (
    PaymentIntentState,
    ProviderPaymentStatus,
    WebhookEventType,
    WebhookVerificationError,
)
from services.audit_ledger.ledger import list_events
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.fake import (
    FakePaymentProvider,
    FaultMode,
    webhook_body,
)
from services.payment_executor.webhooks import WebhookRejected, handle_webhook
from services.payment_executor.worker import run_once
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()


async def _paid(sessionmaker, key: str, *, fault: FaultMode = FaultMode.PENDING):
    """A payment that reached the provider, so a webhook has something to hit.

    Defaults to PENDING so the intent is NOT yet terminal — a webhook that only
    ever arrived after settlement could not exercise a real transition.
    """
    provider = FakePaymentProvider(default_fault=fault)
    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key=key,
            provider="fake",
        )
        await setup.commit()
        mission_id, intent_id = mission.id, result.intent.id

    await run_once(sessionmaker, provider=provider)
    payment = provider.created_payments[key]
    return provider, mission_id, intent_id, payment.provider_payment_id


async def _state(sessionmaker, intent_id) -> str:
    from apps.api.db.models import PaymentIntentRow

    async with sessionmaker() as s:
        row = await s.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert row is not None
        return row.state


# --------------------------------------------------------------------------- #
# #16 Invalid signature is rejected
# --------------------------------------------------------------------------- #
async def test_invalid_signature_is_rejected(sessionmaker):
    provider, _, intent_id, provider_payment_id = await _paid(sessionmaker, "idem-badsig")
    body = webhook_body(
        event_id="evt-1",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )

    async with sessionmaker() as s:
        with pytest.raises(WebhookRejected) as exc:
            await handle_webhook(s, provider=provider, body=body, signature="deadbeef")
        assert exc.value.reason_code == "WEBHOOK_SIGNATURE_INVALID"
        await s.rollback()

    # NEVER TRUST WEBHOOK PAYLOAD STATE BEFORE VERIFICATION: the payload said
    # "succeeded" and the payment did not move.
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.PROVIDER_PENDING.value


async def test_a_tampered_body_invalidates_a_genuine_signature(sessionmaker):
    """The signature covers the RAW bytes, so editing the body breaks it."""
    provider, _, intent_id, provider_payment_id = await _paid(sessionmaker, "idem-tamper")
    honest = webhook_body(
        event_id="evt-t",
        event_type=WebhookEventType.PAYMENT_FAILED,
        provider_payment_id=provider_payment_id,
    )
    signature = provider.sign(honest)
    tampered = honest.replace(b"payment.failed", b"payment.succeeded")

    async with sessionmaker() as s:
        with pytest.raises(WebhookRejected):
            await handle_webhook(s, provider=provider, body=tampered, signature=signature)
        await s.rollback()

    assert await _state(sessionmaker, intent_id) == PaymentIntentState.PROVIDER_PENDING.value


def test_verification_rejects_before_parsing():
    """A body that is not even JSON is refused by the MAC, not by the parser.

    If parsing happened first, a malformed unsigned body would produce a parse
    error — evidence that unverified bytes were being interpreted.
    """
    provider = FakePaymentProvider()
    with pytest.raises(WebhookVerificationError) as exc:
        provider.verify_webhook(body=b"not json at all", signature="00")
    assert "signature" in exc.value.detail


def test_a_signed_but_malformed_body_is_still_rejected():
    """A valid MAC proves origin, never that the contents are well-formed."""
    provider = FakePaymentProvider()
    body = b'{"event_id": "e1"}'
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(body=body, signature=provider.sign(body))


def test_a_forged_signature_cannot_be_constructed_without_the_secret():
    a = FakePaymentProvider(webhook_secret="real-secret")
    b = FakePaymentProvider(webhook_secret="guessed-secret")
    body = webhook_body(
        event_id="evt-x",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id="fake_pay_1",
    )
    with pytest.raises(WebhookVerificationError):
        a.verify_webhook(body=body, signature=b.sign(body))


async def test_a_webhook_for_an_unknown_payment_is_rejected(sessionmaker):
    """The payment is resolved from server-side state; a pointer at nothing
    resolves to nothing."""
    provider = FakePaymentProvider()
    body = webhook_body(
        event_id="evt-unknown",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id="fake_pay_does_not_exist",
    )
    async with sessionmaker() as s:
        with pytest.raises(WebhookRejected) as exc:
            await handle_webhook(s, provider=provider, body=body, signature=provider.sign(body))
        assert exc.value.reason_code == "WEBHOOK_UNKNOWN_PAYMENT"
        await s.rollback()


# --------------------------------------------------------------------------- #
# Valid webhook
# --------------------------------------------------------------------------- #
async def test_a_valid_webhook_settles_the_payment(sessionmaker):
    provider, mission_id, intent_id, provider_payment_id = await _paid(sessionmaker, "idem-valid")
    body = webhook_body(
        event_id="evt-ok",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )

    async with sessionmaker() as s:
        outcome = await handle_webhook(
            s, provider=provider, body=body, signature=provider.sign(body)
        )
        await s.commit()

    assert outcome.applied is True
    assert outcome.state == PaymentIntentState.SUCCEEDED
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value

    async with sessionmaker() as s:
        events = await list_events(s, mission_id)
    types = [e.event_type for e in events]
    assert EventType.WEBHOOK_VERIFIED.value in types
    assert EventType.PAYMENT_SUCCEEDED.value in types


async def test_no_secret_or_signature_is_written_to_the_audit_trail(sessionmaker):
    provider, mission_id, _, provider_payment_id = await _paid(sessionmaker, "idem-nosecret")
    body = webhook_body(
        event_id="evt-secret",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )
    signature = provider.sign(body)

    async with sessionmaker() as s:
        await handle_webhook(s, provider=provider, body=body, signature=signature)
        await s.commit()

    async with sessionmaker() as s:
        blob = str([e.payload for e in await list_events(s, mission_id)])
    assert signature not in blob
    assert "fake-webhook-secret" not in blob


# --------------------------------------------------------------------------- #
# #17 Duplicate webhook is idempotently ignored
# --------------------------------------------------------------------------- #
async def test_duplicate_webhook_is_idempotently_ignored(sessionmaker):
    provider, mission_id, intent_id, provider_payment_id = await _paid(sessionmaker, "idem-dupe")
    body = webhook_body(
        event_id="evt-dupe",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )
    signature = provider.sign(body)

    outcomes = []
    for _ in range(3):
        async with sessionmaker() as s:
            outcomes.append(
                await handle_webhook(s, provider=provider, body=body, signature=signature)
            )
            await s.commit()

    assert [o.applied for o in outcomes] == [True, False, False]
    assert outcomes[1].reason_code == "WEBHOOK_DUPLICATE"
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value

    async with sessionmaker() as s:
        events = await list_events(s, mission_id)
    # ONE state transition, however many deliveries.
    assert len([e for e in events if e.event_type == EventType.PAYMENT_SUCCEEDED.value]) == 1
    assert (
        len([e for e in events if e.event_type == EventType.DUPLICATE_WEBHOOK_IGNORED.value]) == 2
    )
    assert len([e for e in events if e.event_type == EventType.WEBHOOK_VERIFIED.value]) == 1


async def test_only_one_webhook_row_exists_per_provider_event(sessionmaker):
    from apps.api.db.models import WebhookEventRow
    from sqlalchemy import func, select

    provider, _, _, provider_payment_id = await _paid(sessionmaker, "idem-dupe-row")
    body = webhook_body(
        event_id="evt-one-row",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
    )
    signature = provider.sign(body)

    for _ in range(4):
        async with sessionmaker() as s:
            await handle_webhook(s, provider=provider, body=body, signature=signature)
            await s.commit()

    async with sessionmaker() as s:
        count = await s.scalar(
            select(func.count())
            .select_from(WebhookEventRow)
            .where(WebhookEventRow.provider_event_id == "evt-one-row")
        )
    assert count == 1


# --------------------------------------------------------------------------- #
# #18 Delayed webhook does not regress terminal state
# --------------------------------------------------------------------------- #
async def test_a_delayed_failure_webhook_cannot_regress_a_settled_payment(sessionmaker):
    """The dangerous one: a late 'failed' arriving after a real success."""
    provider, mission_id, intent_id, provider_payment_id = await _paid(
        sessionmaker, "idem-delayed", fault=FaultMode.SUCCESS
    )
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value

    late = webhook_body(
        event_id="evt-late",
        event_type=WebhookEventType.PAYMENT_FAILED,
        provider_payment_id=provider_payment_id,
        sequence=1,
    )
    async with sessionmaker() as s:
        outcome = await handle_webhook(
            s, provider=provider, body=late, signature=provider.sign(late)
        )
        await s.commit()

    assert outcome.accepted is True
    assert outcome.applied is False
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value

    async with sessionmaker() as s:
        types = [e.event_type for e in await list_events(s, mission_id)]
    assert EventType.WEBHOOK_OUT_OF_ORDER_IGNORED.value in types
    assert types.count(EventType.PAYMENT_FAILED.value) == 0

    from apps.api.db.models import WebhookEventRow
    from sqlalchemy import select

    async with sessionmaker() as s:
        stored = await s.scalar(
            select(WebhookEventRow).where(WebhookEventRow.provider_event_id == "evt-late")
        )
    assert stored is not None
    assert stored.processed_at is not None
    assert stored.applied_state is None


async def test_a_delayed_pending_webhook_cannot_reopen_a_settled_payment(sessionmaker):
    provider, _, intent_id, provider_payment_id = await _paid(
        sessionmaker, "idem-delayed-pending", fault=FaultMode.SUCCESS
    )
    stale = webhook_body(
        event_id="evt-stale-pending",
        event_type=WebhookEventType.PAYMENT_PENDING,
        provider_payment_id=provider_payment_id,
    )
    async with sessionmaker() as s:
        outcome = await handle_webhook(
            s, provider=provider, body=stale, signature=provider.sign(stale)
        )
        await s.commit()

    assert outcome.applied is False
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value


# --------------------------------------------------------------------------- #
# #19 Out-of-order webhook produces no illegal transition
# --------------------------------------------------------------------------- #
async def test_out_of_order_webhooks_do_not_produce_an_illegal_transition(sessionmaker):
    """Events delivered newest-first. The terminal one wins and the stale one
    is ignored — decided by the state machine, not by the sequence number."""
    provider, mission_id, intent_id, provider_payment_id = await _paid(sessionmaker, "idem-ooo")

    newer = webhook_body(
        event_id="evt-2",
        event_type=WebhookEventType.PAYMENT_SUCCEEDED,
        provider_payment_id=provider_payment_id,
        sequence=2,
    )
    older = webhook_body(
        event_id="evt-1",
        event_type=WebhookEventType.PAYMENT_PENDING,
        provider_payment_id=provider_payment_id,
        sequence=1,
    )

    results = []
    for body in (newer, older):
        async with sessionmaker() as s:
            results.append(
                await handle_webhook(s, provider=provider, body=body, signature=provider.sign(body))
            )
            await s.commit()

    assert results[0].applied is True
    assert results[1].applied is False
    assert results[1].reason_code == "ILLEGAL_PAYMENT_TRANSITION"
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value


async def test_a_higher_sequence_number_grants_nothing(sessionmaker):
    """A provider-supplied ordinal is recorded, never obeyed.

    A hostile 'sequence: 9999' on a failure event must not override a settled
    success — the transition table decides, so the ordinal is inert.
    """
    provider, _, intent_id, provider_payment_id = await _paid(
        sessionmaker, "idem-seq", fault=FaultMode.SUCCESS
    )
    body = webhook_body(
        event_id="evt-seq",
        event_type=WebhookEventType.PAYMENT_FAILED,
        provider_payment_id=provider_payment_id,
        sequence=9999,
    )
    async with sessionmaker() as s:
        outcome = await handle_webhook(
            s, provider=provider, body=body, signature=provider.sign(body)
        )
        await s.commit()

    assert outcome.applied is False
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value


async def test_a_failure_webhook_settles_a_pending_payment(sessionmaker):
    """The legal transition still works — the guard is not simply 'refuse all'."""
    provider, _, intent_id, provider_payment_id = await _paid(sessionmaker, "idem-fail-hook")
    provider.settle("idem-fail-hook", ProviderPaymentStatus.FAILED)

    body = webhook_body(
        event_id="evt-fail",
        event_type=WebhookEventType.PAYMENT_FAILED,
        provider_payment_id=provider_payment_id,
    )
    async with sessionmaker() as s:
        outcome = await handle_webhook(
            s, provider=provider, body=body, signature=provider.sign(body)
        )
        await s.commit()

    assert outcome.applied is True
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.FAILED_TERMINAL.value
