"""Fault injection: timeouts, transient failures, terminal declines.

The two timeout cases are the point of Phase 4, and they are deliberately
INDISTINGUISHABLE to PACTRA. In both, the executor observes exactly one thing:
the call did not complete. What differs is only what the provider is holding
afterwards — nothing, or a real payment.

That is why both land in PROVIDER_PENDING. A design that branched here would be
branching on information it does not have. The tests below assert the observable
consequences instead: after TIMEOUT_BEFORE_CREATE the provider holds nothing and
a retry eventually succeeds; after TIMEOUT_AFTER_CREATE the provider holds
exactly one payment and PACTRA converges onto THAT payment rather than making a
second.
"""

import pytest
from apps.api.db.models import PaymentIntentRow
from packages.schemas.capability import payment_executor_capabilities
from packages.schemas.domain import EventType, MissionState
from packages.schemas.payment import (
    PaymentIntentState,
    ProviderPayment,
    ProviderPaymentStatus,
)
from services.audit_ledger.ledger import list_events
from services.payment_executor.intents import create_payment_intent
from services.payment_executor.providers.base import ProviderTransientError
from services.payment_executor.providers.fake import FakePaymentProvider, FaultMode
from services.payment_executor.worker import drain, run_once
from tests.conftest import authorized_mission

EXECUTOR = payment_executor_capabilities()


class MismatchedResponseProvider(FakePaymentProvider):
    def __init__(self, field: str, value: object) -> None:
        super().__init__()
        self.field = field
        self.value = value

    async def create_payment(self, request) -> ProviderPayment:
        payment = await super().create_payment(request)
        return payment.model_copy(update={self.field: self.value})


class LookupUnavailableProvider(FakePaymentProvider):
    async def get_payment(self, **kwargs) -> ProviderPayment | None:
        self.get_calls.append((kwargs.get("provider_payment_id"), kwargs.get("idempotency_key")))
        raise ProviderTransientError(self.name, "lookup unavailable")


async def _start_payment(sessionmaker, key: str) -> tuple:
    """Commit an AUTHORIZED mission with a QUEUED payment intent."""
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
        return mission.id, result.intent.id


async def _state(sessionmaker, intent_id) -> str:
    from apps.api.db.models import PaymentIntentRow

    async with sessionmaker() as s:
        row = await s.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert row is not None
        return row.state


async def _intent(sessionmaker, intent_id):
    from apps.api.db.models import PaymentIntentRow

    async with sessionmaker() as s:
        return await s.get(PaymentIntentRow, intent_id, populate_existing=True)


async def _event_types(sessionmaker, mission_id) -> list[str]:
    async with sessionmaker() as s:
        return [e.event_type for e in await list_events(s, mission_id)]


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #
async def test_success_settles_the_payment(sessionmaker):
    provider = FakePaymentProvider()
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-success")

    await run_once(sessionmaker, provider=provider)

    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value
    assert provider.payment_count_for("idem-success") == 1

    types = await _event_types(sessionmaker, mission_id)
    assert EventType.PAYMENT_ATTEMPTED.value in types
    assert EventType.PAYMENT_SUCCEEDED.value in types

    async with sessionmaker() as s:
        from apps.api.db.models import Mission

        mission = await s.get(Mission, mission_id, populate_existing=True)
        assert mission is not None
        assert mission.state == MissionState.PAYMENT_SUCCEEDED.value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "wrong-provider"),
        ("amount_inr", 999999),
        ("currency", "USD"),
        ("idempotency_key", "another-logical-payment"),
    ],
)
async def test_mismatched_provider_response_never_settles_the_intent(sessionmaker, field, value):
    """A provider response is untrusted until bound to the durable intent."""
    provider = MismatchedResponseProvider(field, value)
    _, intent_id = await _start_payment(sessionmaker, f"idem-mismatch-{field}")

    await run_once(sessionmaker, provider=provider)

    intent = await _intent(sessionmaker, intent_id)
    assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
    assert intent.provider_payment_id is None
    assert intent.last_reason_code == "PROVIDER_RESPONSE_MISMATCH"


async def test_failed_pre_create_lookup_never_falls_through_to_create(sessionmaker):
    """An unavailable lookup cannot prove that no earlier payment exists."""
    provider = LookupUnavailableProvider()
    _, intent_id = await _start_payment(sessionmaker, "idem-lookup-unavailable")

    await run_once(sessionmaker, provider=provider)

    assert provider.get_calls
    assert provider.create_calls == []
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.PROVIDER_PENDING.value


# --------------------------------------------------------------------------- #
# #10, #11 TIMEOUT BEFORE the provider creates a payment
# --------------------------------------------------------------------------- #
async def test_timeout_before_create_produces_no_provider_payment(sessionmaker):
    """The provider genuinely holds nothing."""
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_BEFORE_CREATE)
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-timeout-before")

    await run_once(sessionmaker, provider=provider)

    assert provider.payment_count_for("idem-timeout-before") == 0
    assert provider.created_payments == {}
    # Uncertain, NOT failed: PACTRA cannot know the provider created nothing.
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.PROVIDER_PENDING.value

    types = await _event_types(sessionmaker, mission_id)
    assert EventType.PAYMENT_PROVIDER_TIMEOUT.value in types
    assert EventType.PAYMENT_PROVIDER_UNCERTAIN.value in types


async def test_retry_after_timeout_before_create_eventually_succeeds(sessionmaker):
    """The whole convergence path, driven to completion.

    timeout -> uncertain -> reconcile (provider holds nothing)
            -> retryable -> re-create -> SUCCEEDED
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_BEFORE_CREATE)
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-timeout-before-retry")

    await drain(sessionmaker, provider=provider, max_events=12)

    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value
    # Exactly one payment, despite two create attempts.
    assert provider.payment_count_for("idem-timeout-before-retry") == 1
    assert provider.create_calls.count("idem-timeout-before-retry") == 2

    types = await _event_types(sessionmaker, mission_id)
    assert EventType.PAYMENT_RECONCILED.value in types
    assert EventType.PAYMENT_RETRY_SCHEDULED.value in types
    assert EventType.PAYMENT_SUCCEEDED.value in types


async def test_reconciliation_only_retries_once_it_knows_nothing_exists(sessionmaker):
    """The safety condition for re-creating a payment.

    The provider is asked BEFORE any second create attempt, and the audit trail
    records the conclusion that made the retry safe.
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_BEFORE_CREATE)
    mission_id, _ = await _start_payment(sessionmaker, "idem-ask-first")

    await drain(sessionmaker, provider=provider, max_events=12)

    # get_payment was called before the second create.
    assert provider.get_calls, "reconciliation must ask the provider"
    async with sessionmaker() as s:
        events = await list_events(s, mission_id)
    reconciled = [e for e in events if e.event_type == EventType.PAYMENT_RECONCILED.value]
    assert any(e.payload.get("provider_holds_no_payment") is True for e in reconciled)


# --------------------------------------------------------------------------- #
# #12, #13 TIMEOUT AFTER the provider creates a payment — the important demo
# --------------------------------------------------------------------------- #
async def test_timeout_after_create_creates_at_most_one_provider_payment(sessionmaker):
    """The response is lost; the payment is real."""
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE)
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-timeout-after")

    await run_once(sessionmaker, provider=provider)

    # The provider DID create one. PACTRA does not know that yet.
    assert provider.payment_count_for("idem-timeout-after") == 1
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.PROVIDER_PENDING.value

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    # Nothing was linked, because nothing was learned.
    assert intent.provider_payment_id is None

    async with sessionmaker() as s:
        events = await list_events(s, mission_id)
    uncertain = [e for e in events if e.event_type == EventType.PAYMENT_PROVIDER_UNCERTAIN.value]
    assert uncertain and uncertain[0].payload["provider_payment_may_exist"] is True


async def test_reconciliation_resolves_onto_the_original_provider_payment(sessionmaker):
    """THE DEMO. No blind duplicate; the original payment is adopted.

    create -> provider creates P -> response lost -> uncertain
           -> reconcile -> provider returns P -> same intent linked to P
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE)
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-timeout-after-reconcile")

    # The payment the provider actually created, before PACTRA knows of it.
    await run_once(sessionmaker, provider=provider)
    original = provider.created_payments["idem-timeout-after-reconcile"]

    await drain(sessionmaker, provider=provider, max_events=12)

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    assert intent.state == PaymentIntentState.SUCCEEDED.value
    # Linked to the ORIGINAL payment, not a new one.
    assert intent.provider_payment_id == original.provider_payment_id

    # NO DUPLICATE: exactly one provider payment ever existed.
    assert provider.payment_count_for("idem-timeout-after-reconcile") == 1
    assert len(provider.created_payments) == 1

    types = await _event_types(sessionmaker, mission_id)
    assert EventType.PAYMENT_RECONCILED.value in types


async def test_no_second_create_call_is_made_after_an_uncertain_timeout(sessionmaker):
    """PACTRA MUST NOT blindly create another provider payment.

    Asserted on the provider's own call log, so it holds even if provider-side
    idempotency were absent — the executor must not make the call at all.
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TIMEOUT_AFTER_CREATE)
    _, _ = await _start_payment(sessionmaker, "idem-no-blind-create")

    await drain(sessionmaker, provider=provider, max_events=12)

    assert provider.create_calls.count("idem-no-blind-create") == 1, (
        "a second create call was made while the outcome was uncertain"
    )


async def test_a_duplicate_provider_response_does_not_create_a_second_payment(sessionmaker):
    """Provider-side idempotency, exercised explicitly."""
    provider = FakePaymentProvider(default_fault=FaultMode.DUPLICATE_RESPONSE)
    _, intent_id = await _start_payment(sessionmaker, "idem-duplicate-response")

    await drain(sessionmaker, provider=provider, max_events=8)

    assert provider.payment_count_for("idem-duplicate-response") == 1
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value


# --------------------------------------------------------------------------- #
# #20, #21 Terminal vs retryable provider failures
# --------------------------------------------------------------------------- #
async def test_terminal_provider_failure_reaches_failed_terminal(sessionmaker):
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TERMINAL_FAILURE)
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-terminal")

    await drain(sessionmaker, provider=provider, max_events=8)

    assert await _state(sessionmaker, intent_id) == PaymentIntentState.FAILED_TERMINAL.value
    assert provider.payment_count_for("idem-terminal") == 0
    # A terminal decline is not retried: one call, no more.
    assert provider.create_calls.count("idem-terminal") == 1

    types = await _event_types(sessionmaker, mission_id)
    assert EventType.PAYMENT_FAILED.value in types

    async with sessionmaker() as s:
        from apps.api.db.models import Mission

        mission = await s.get(Mission, mission_id, populate_existing=True)
        assert mission is not None
        assert mission.state == MissionState.PAYMENT_FAILED.value


async def test_retryable_provider_failure_remains_recoverable(sessionmaker):
    """A transient refusal must leave the payment recoverable, not dead."""
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TRANSIENT_FAILURE)
    mission_id, intent_id = await _start_payment(sessionmaker, "idem-transient")

    await run_once(sessionmaker, provider=provider)

    assert await _state(sessionmaker, intent_id) == PaymentIntentState.FAILED_RETRYABLE.value
    # The provider answered, so nothing was created.
    assert provider.payment_count_for("idem-transient") == 0

    types = await _event_types(sessionmaker, mission_id)
    assert EventType.PAYMENT_RETRY_SCHEDULED.value in types

    # And the outbox event is genuinely still queued for another attempt.
    from services.payment_executor.outbox import pending_events_for

    async with sessionmaker() as s:
        assert len(await pending_events_for(s, intent_id)) == 1


async def test_a_transient_failure_then_success_converges(sessionmaker):
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.TRANSIENT_FAILURE, FaultMode.TRANSIENT_FAILURE)
    _, intent_id = await _start_payment(sessionmaker, "idem-transient-converge")

    from datetime import timedelta

    from packages.schemas.domain import utcnow

    # Backoff means later attempts are only due in the future; step time
    # forward rather than sleeping.
    for offset in (0, 5, 30, 120):
        await run_once(sessionmaker, provider=provider, now=utcnow() + timedelta(seconds=offset))

    assert await _state(sessionmaker, intent_id) == PaymentIntentState.SUCCEEDED.value
    assert provider.payment_count_for("idem-transient-converge") == 1


async def test_a_pending_provider_payment_stays_uncertain_until_settled(sessionmaker):
    """Accepted but not settled is uncertainty too, and it must not be reported
    as success."""
    provider = FakePaymentProvider(default_fault=FaultMode.PENDING)
    _, intent_id = await _start_payment(sessionmaker, "idem-pending")

    await run_once(sessionmaker, provider=provider)
    assert await _state(sessionmaker, intent_id) == PaymentIntentState.PROVIDER_PENDING.value

    intent = await _intent(sessionmaker, intent_id)
    assert intent is not None
    # Linked, because the provider DID answer and name the payment.
    assert intent.provider_payment_id is not None


# --------------------------------------------------------------------------- #
# Adoption requires CORRELATION, not merely a plausible-looking payment
# --------------------------------------------------------------------------- #
class UncorrelatedLookupProvider(FakePaymentProvider):
    """A lookup that answers with a payment it does not tie to the key asked about.

    Amount, currency and provider all match, so every field-equality check
    passes. The only thing missing is the one thing that says "this is the
    payment for YOUR key". A real provider can produce this shape by omitting
    the receipt/reference field from a search result.
    """

    async def get_payment(self, *, provider_payment_id=None, idempotency_key=None):
        self.get_calls.append((provider_payment_id, idempotency_key))
        return ProviderPayment(
            provider=self.name,
            provider_payment_id="not_our_payment",
            status=ProviderPaymentStatus.SUCCEEDED,
            amount_inr=3799,
            currency="INR",
            idempotency_key=None,
            idempotent_replay=False,
        )


class WrongKeyLookupProvider(FakePaymentProvider):
    """A lookup that answers with a payment belonging to a DIFFERENT key."""

    async def get_payment(self, *, provider_payment_id=None, idempotency_key=None):
        self.get_calls.append((provider_payment_id, idempotency_key))
        return ProviderPayment(
            provider=self.name,
            provider_payment_id="another_missions_payment",
            status=ProviderPaymentStatus.SUCCEEDED,
            amount_inr=3799,
            currency="INR",
            idempotency_key="somebody-elses-key",
            idempotent_replay=False,
        )


@pytest.mark.parametrize("provider_class", [UncorrelatedLookupProvider, WrongKeyLookupProvider])
async def test_an_uncorrelated_lookup_result_is_never_adopted(sessionmaker, provider_class):
    """PROVIDER RESPONSE MISMATCH -> NEVER SETTLES INTENT.

    The pre-create lookup asks "what do you hold for key K?". Adoption is the
    step that decides an existing provider payment IS this intent's payment, and
    the recovery design rests entirely on the key being the handle that makes
    that decision sound. A response that does not carry the key — or carries a
    different one — must therefore leave the intent uncertain and UNLINKED,
    even when its amount and currency match perfectly.

    Linking here would be worse than a duplicate charge: the intent would report
    SUCCEEDED against money that was moved for someone else.
    """
    provider = provider_class()

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-uncorrelated",
            provider="fake",
        )
        intent_id = result.intent.id
        await setup.commit()

    await run_once(sessionmaker, provider=provider, worker_id="w1")

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent is not None
        assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
        # The important half: nothing was linked, so no later webhook for that
        # foreign payment can find this intent either.
        assert intent.provider_payment_id is None
        assert intent.last_reason_code == "PROVIDER_RESPONSE_MISMATCH"

    # And no create was attempted on the back of the rejected answer.
    assert provider.create_calls == []


async def test_a_linked_payment_still_reconciles_without_a_returned_key(sessionmaker):
    """Once an id is linked, the id is the correlation — the key need not repeat.

    The stricter rule above must not become "a provider that omits the key can
    never settle anything". After ``provider_payment_id`` is recorded, PACTRA
    already knows which payment this is, and ``link_provider_payment`` refuses
    to relink a different one, so an id-correlated response is sound.
    """
    provider = FakePaymentProvider()
    provider.queue_faults(FaultMode.PENDING)

    async with sessionmaker() as setup:
        mission, authorization, _ = await authorized_mission(setup)
        result = await create_payment_intent(
            setup,
            capabilities=EXECUTOR,
            mission_id=mission.id,
            authorization_id=authorization.authorization_id,
            idempotency_key="idem-linked-then-keyless",
            provider="fake",
        )
        intent_id = result.intent.id
        await setup.commit()

    await run_once(sessionmaker, provider=provider, worker_id="w1")

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent.state == PaymentIntentState.PROVIDER_PENDING.value
        linked = intent.provider_payment_id
        assert linked is not None

    # The provider now settles, but its reconciliation answer omits the key.
    held = provider.created_payments["idem-linked-then-keyless"]
    provider.created_payments["idem-linked-then-keyless"] = held.model_copy(
        update={"status": ProviderPaymentStatus.SUCCEEDED, "idempotency_key": None}
    )

    await drain(sessionmaker, provider=provider, max_events=6)

    async with sessionmaker() as check:
        intent = await check.get(PaymentIntentRow, intent_id, populate_existing=True)
        assert intent.state == PaymentIntentState.SUCCEEDED.value
        assert intent.provider_payment_id == linked
