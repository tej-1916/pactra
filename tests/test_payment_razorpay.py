"""The Razorpay adapter, tested OFFLINE — and only where a test can be honest.

Scope is deliberately narrow, and the narrowness is the point. Two things about
this adapter are verifiable without a network: the test-mode credential guard,
and webhook signature verification. Both are pure functions of their inputs, and
both follow published Razorpay behaviour, so a test of them proves something
real.

The HTTP paths are exercised only against a stub client. That proves this
adapter's *interpretation* of a response — which status codes mean transient
versus terminal, that a lost connection is uncertainty rather than failure, that
paise convert to rupees — but it does NOT prove Razorpay actually replies that
way. The adapter is labelled ``partial`` for exactly this reason, and nothing
here upgrades that claim.

No test in this file performs a network call, and no real credential appears in
it: ``rzp_test_`` keys here are syntactic fixtures, not accounts.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from packages.schemas.invariants import InvariantViolation
from packages.schemas.payment import (
    PaymentRequest,
    ProviderPaymentStatus,
    WebhookEventType,
    WebhookVerificationError,
)
from services.payment_executor.providers.base import (
    ProviderTerminalError,
    ProviderTimeout,
    ProviderTransientError,
)
from services.payment_executor.providers.razorpay import (
    RazorpayTestPaymentProvider,
    from_environment,
)

KEY_ID = "rzp_test_0000000000"
KEY_SECRET = "test-secret-not-a-credential"
WEBHOOK_SECRET = "test-webhook-secret-not-a-credential"

REQUEST = PaymentRequest(
    idempotency_key="idem-rzp-1",
    amount_inr=3799,
    currency="INR",
    merchant_id="merchant_a",
    transaction_digest_prefix="a" * 16,
)


class StubResponse:
    def __init__(self, status_code: int, body: dict | None = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class StubClient:
    """Records calls and replays scripted responses. Never touches a socket."""

    def __init__(self, *, post=None, get=None) -> None:
        self._post = post
        self._get = get
        self.post_calls: list[tuple] = []
        self.get_calls: list[tuple] = []

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if isinstance(self._get, Exception):
            raise self._get
        if callable(self._get):
            return self._get(url, kwargs)
        return self._get


def make_provider(**kwargs) -> RazorpayTestPaymentProvider:
    return RazorpayTestPaymentProvider(
        key_id=kwargs.pop("key_id", KEY_ID),
        key_secret=kwargs.pop("key_secret", KEY_SECRET),
        webhook_secret=kwargs.pop("webhook_secret", WEBHOOK_SECRET),
        **kwargs,
    )


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# 1. Test-mode guard — "no real-money payments" made structural
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "key_id",
    ["rzp_live_0000000000", "rzp_0000000000", "", "RZP_TEST_0000000000"],
)
def test_a_non_test_key_is_refused_before_anything_is_stored(key_id):
    """A live key must not survive construction, let alone reach the network.

    Checking at call time would leave a live credential sitting in an attribute
    in the meantime; refusing in ``__init__`` means the object holding it never
    exists. The uppercase variant is included because a case-insensitive prefix
    check would accept a live key whose id merely looked shouty.
    """
    with pytest.raises(InvariantViolation) as exc:
        make_provider(key_id=key_id)
    assert exc.value.invariant == "razorpay.test_mode_only"


@pytest.mark.parametrize(
    "field,invariant",
    [
        ("key_secret", "razorpay.key_secret_present"),
        ("webhook_secret", "razorpay.webhook_secret_present"),
    ],
)
def test_a_missing_secret_raises_instead_of_defaulting(field, invariant):
    """There is no source-code fallback, because a fallback is a committed secret."""
    with pytest.raises(InvariantViolation) as exc:
        make_provider(**{field: ""})
    assert exc.value.invariant == invariant


def test_from_environment_refuses_when_secrets_are_absent(monkeypatch):
    for name in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(InvariantViolation):
        from_environment()


def test_the_repr_cannot_leak_a_secret():
    """Redaction is a property of the type, not of every call site that logs it."""
    rendered = repr(make_provider())
    assert KEY_SECRET not in rendered
    assert WEBHOOK_SECRET not in rendered
    assert "REDACTED" in rendered


# --------------------------------------------------------------------------- #
# 2. Webhook signature verification — faithful to documented Razorpay behaviour
# --------------------------------------------------------------------------- #
def razorpay_webhook(
    *, event: str = "order.paid", order_id: str = "order_ABC123", event_id: str = "evt_1"
) -> bytes:
    payload = {
        "id": event_id,
        "event": event,
        "payload": {"order": {"entity": {"id": order_id}}},
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_a_valid_signature_verifies_and_parses():
    provider = make_provider()
    body = razorpay_webhook()
    event = provider.verify_webhook(body=body, signature=sign(body))
    assert event.provider == "razorpay_test"
    assert event.provider_event_id == "evt_1"
    assert event.event_type is WebhookEventType.PAYMENT_SUCCEEDED
    assert event.provider_payment_id == "order_ABC123"


def test_a_forged_signature_is_refused():
    """INVALID WEBHOOK SIGNATURE -> REJECT BEFORE TRUSTING STATE."""
    provider = make_provider()
    body = razorpay_webhook()
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(body=body, signature="0" * 64)


def test_a_signature_from_the_wrong_secret_is_refused():
    provider = make_provider()
    body = razorpay_webhook()
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(body=body, signature=sign(body, "some-other-secret"))


def test_tampering_with_the_body_invalidates_the_signature():
    """The MAC covers the RAW bytes, so a single altered field breaks it."""
    provider = make_provider()
    original = razorpay_webhook(order_id="order_ABC123")
    signature = sign(original)
    tampered = razorpay_webhook(order_id="order_ATTACKER")
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(body=tampered, signature=signature)


@pytest.mark.parametrize(
    "body",
    [b"not json at all", b"[1,2,3]", b'"a string"', b"\xff\xfe"],
)
def test_a_signed_but_malformed_body_is_still_refused(body):
    """A valid MAC proves origin, never that the contents are well-formed."""
    provider = make_provider()
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(body=body, signature=sign(body))


def test_an_unmapped_event_is_refused_rather_than_guessed_at():
    """An event whose meaning is undocumented must not be mapped onto a state."""
    provider = make_provider()
    body = razorpay_webhook(event="payment.dispute.created")
    with pytest.raises(WebhookVerificationError) as exc:
        provider.verify_webhook(body=body, signature=sign(body))
    assert "unsupported" in exc.value.detail


def test_a_webhook_without_an_event_id_is_refused():
    """No event id means no deduplication key, and an undeduplicable webhook
    cannot be idempotent — so it is refused rather than applied once and hoped
    about."""
    provider = make_provider()
    payload = {"event": "order.paid", "payload": {"order": {"entity": {"id": "order_1"}}}}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with pytest.raises(WebhookVerificationError) as exc:
        provider.verify_webhook(body=body, signature=sign(body))
    assert "event id" in exc.value.detail


def test_a_webhook_naming_no_order_is_refused():
    provider = make_provider()
    payload = {"id": "evt_9", "event": "order.paid", "payload": {}}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(body=body, signature=sign(body))


def test_a_payment_entity_webhook_correlates_by_its_order_id():
    """Razorpay nests a payment under ``payload.payment.entity``; the handle
    PACTRA stored is the ORDER id, so that is what must be extracted."""
    provider = make_provider()
    payload = {
        "id": "evt_5",
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_XYZ", "order_id": "order_ABC123"}}},
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    event = provider.verify_webhook(body=body, signature=sign(body))
    assert event.provider_payment_id == "order_ABC123"


# --------------------------------------------------------------------------- #
# 3. Response interpretation — proven against a stub, NOT against Razorpay
# --------------------------------------------------------------------------- #
async def test_a_created_order_maps_paise_back_to_rupees():
    client = StubClient(
        post=StubResponse(
            200,
            {
                "id": "order_ABC123",
                "status": "created",
                "amount": 379900,
                "currency": "INR",
                "receipt": REQUEST.idempotency_key,
            },
        )
    )
    provider = make_provider(http_client=client)
    payment = await provider.create_payment(REQUEST)

    assert payment.amount_inr == 3799
    assert payment.currency == "INR"
    assert payment.idempotency_key == REQUEST.idempotency_key
    assert payment.status is ProviderPaymentStatus.CREATED
    # The idempotency key travels as the receipt — the correlation handle
    # reconciliation later looks up.
    assert client.post_calls[0][1]["json"]["receipt"] == REQUEST.idempotency_key
    assert client.post_calls[0][1]["json"]["amount"] == 379900


async def test_a_transport_failure_is_uncertainty_not_failure():
    """PROVIDER LOOKUP/CREATE FAILURE -> NEVER ASSUME NOTHING WAS CREATED.

    The order may have been created before the connection died. Collapsing this
    into a retryable failure is the duplicate-charge bug.
    """
    client = StubClient(post=ConnectionResetError("connection reset"))
    provider = make_provider(http_client=client)
    with pytest.raises(ProviderTimeout):
        await provider.create_payment(REQUEST)


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
async def test_rate_limits_and_server_errors_are_transient(status_code):
    client = StubClient(post=StubResponse(status_code))
    provider = make_provider(http_client=client)
    with pytest.raises(ProviderTransientError):
        await provider.create_payment(REQUEST)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
async def test_other_client_errors_are_terminal(status_code):
    """Razorpay answered and refused; a retry cannot change the answer."""
    client = StubClient(post=StubResponse(status_code))
    provider = make_provider(http_client=client)
    with pytest.raises(ProviderTerminalError):
        await provider.create_payment(REQUEST)


async def test_an_unknown_order_status_stays_pending():
    """Reporting an order PACTRA does not understand as settled would be
    inventing an outcome. PENDING keeps it in reconciliation."""
    client = StubClient(
        post=StubResponse(
            200, {"id": "order_1", "status": "some_future_status", "amount": 100, "receipt": "k"}
        )
    )
    provider = make_provider(http_client=client)
    payment = await provider.create_payment(REQUEST)
    assert payment.status is ProviderPaymentStatus.PENDING


async def test_a_missing_http_client_never_silently_succeeds():
    provider = make_provider()
    with pytest.raises(ProviderTransientError):
        await provider.create_payment(REQUEST)


# --------------------------------------------------------------------------- #
# 4. Receipt lookup — the lost-response handle, and its documented weakness
# --------------------------------------------------------------------------- #
async def test_an_empty_receipt_search_reports_no_payment():
    """The one answer that makes re-creating a payment safe."""
    client = StubClient(get=StubResponse(200, {"items": []}))
    provider = make_provider(http_client=client)
    assert await provider.get_payment(idempotency_key="idem-missing") is None


async def test_a_single_matching_receipt_is_adopted():
    client = StubClient(
        get=StubResponse(
            200,
            {
                "items": [
                    {
                        "id": "order_ABC123",
                        "status": "paid",
                        "amount": 379900,
                        "currency": "INR",
                        "receipt": "idem-rzp-1",
                    }
                ]
            },
        )
    )
    provider = make_provider(http_client=client)
    payment = await provider.get_payment(idempotency_key="idem-rzp-1")
    assert payment is not None
    assert payment.provider_payment_id == "order_ABC123"
    assert payment.status is ProviderPaymentStatus.SUCCEEDED
    assert client.get_calls[0][1]["params"] == {"receipt": "idem-rzp-1"}


async def test_two_orders_sharing_a_receipt_are_refused_not_arbitrated():
    """Razorpay does not enforce receipt uniqueness (documented limitation 1).

    Two orders for one receipt IS the duplicate this phase exists to prevent.
    Returning the first would resolve the lookup by discarding the evidence, and
    the intent would settle against an arbitrary one of two real orders. The
    adapter refuses, which leaves the intent uncertain and reconcilable.
    """
    client = StubClient(
        get=StubResponse(
            200,
            {
                "items": [
                    {"id": "order_1", "status": "paid", "amount": 379900, "receipt": "dup"},
                    {"id": "order_2", "status": "paid", "amount": 379900, "receipt": "dup"},
                ]
            },
        )
    )
    provider = make_provider(http_client=client)
    with pytest.raises(ProviderTransientError) as exc:
        await provider.get_payment(idempotency_key="dup")
    assert "refusing to adopt one arbitrarily" in exc.value.detail


async def test_a_404_on_an_order_id_lookup_means_no_such_payment():
    client = StubClient(get=StubResponse(404))
    provider = make_provider(http_client=client)
    assert await provider.get_payment(provider_payment_id="order_gone") is None


async def test_a_failed_receipt_lookup_raises_rather_than_reporting_absence():
    """A lookup that could not be performed is NOT evidence of no payment.

    Returning None here would be the blind-retry bug wearing a different hat:
    the executor treats None as 'safe to create', so an unreachable provider
    must raise instead.
    """
    client = StubClient(get=StubResponse(503))
    provider = make_provider(http_client=client)
    with pytest.raises(ProviderTransientError):
        await provider.get_payment(idempotency_key="idem-unreachable")

    client = StubClient(get=ConnectionResetError("reset"))
    provider = make_provider(http_client=client)
    with pytest.raises(ProviderTransientError):
        await provider.get_payment(idempotency_key="idem-unreachable")
