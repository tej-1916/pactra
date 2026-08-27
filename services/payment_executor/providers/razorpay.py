"""``RazorpayTestPaymentProvider`` — TEST MODE ONLY.

Added only after every reliability invariant was proven against
``FakePaymentProvider``. Nothing in this module changes the executor: the
guarantees live in the executor and its storage constraints, and this adapter is
just another implementation of ``PaymentProvider``.

DOCUMENTED LIMITATIONS — these are gaps, not features, and none of them is
simulated to look otherwise
---------------------------------------------------------------------------
1. **Razorpay does not enforce receipt uniqueness.** PACTRA sends its
   idempotency key as the Order ``receipt`` and reconciles with
   ``GET /v1/orders?receipt=…``, which is the documented way to look an order up
   by receipt. Razorpay's documentation does NOT state that a duplicate receipt
   is rejected, so this adapter does not claim provider-side idempotency the way
   ``FakePaymentProvider`` legitimately does. The duplicate-prevention guarantee
   here rests entirely on PACTRA's own ``UNIQUE(idempotency_key)`` plus the
   PROVIDER_PENDING/reconciliation path — which is exactly why those were built
   without assuming provider help.

2. **An Order is not a Payment.** Razorpay's server-side API creates an *Order*;
   the *Payment* is produced when a customer completes Checkout. This adapter
   therefore reports the Order as the provider reference and maps order status,
   not payment status. A completed end-to-end Razorpay payment needs a Checkout
   front end, which Phase 4 does not build. The adapter is labelled ``partial``
   for that reason.

3. **Not exercised against the live Razorpay API in this phase.** The tests here
   cover signature verification and the test-mode guard, both of which are
   offline and both of which follow published Razorpay behaviour. The HTTP paths
   are unverified against a real endpoint and are marked as such. They are not
   presented as tested.

Webhook signature verification IS implemented faithfully: Razorpay documents
``X-Razorpay-Signature`` as ``HMAC-SHA256(raw_body, webhook_secret)``, hex
encoded, and that is precisely what is computed and compared here.

SECRETS. The key secret and webhook secret are read from the environment only.
They are never defaulted to a real value, never logged, never written to an
audit payload, and never returned by the API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from packages.schemas.invariants import require
from packages.schemas.payment import (
    PaymentRequest,
    ProviderPayment,
    ProviderPaymentStatus,
    VerifiedWebhookEvent,
    WebhookEventType,
    WebhookVerificationError,
)

from services.payment_executor.providers.base import (
    ProviderTerminalError,
    ProviderTimeout,
    ProviderTransientError,
)

PROVIDER_NAME = "razorpay_test"

#: Razorpay test-mode keys carry this prefix. A live key does not.
TEST_KEY_PREFIX = "rzp_test_"

API_BASE = "https://api.razorpay.com/v1"

#: Razorpay order statuses, per its published Orders API.
_ORDER_STATUS_MAP: dict[str, ProviderPaymentStatus] = {
    "created": ProviderPaymentStatus.CREATED,
    "attempted": ProviderPaymentStatus.PENDING,
    "paid": ProviderPaymentStatus.SUCCEEDED,
}

#: Razorpay webhook events this adapter understands. Anything else is refused
#: rather than guessed at — an event whose meaning is not documented must not be
#: mapped onto a payment state.
_WEBHOOK_EVENT_MAP: dict[str, WebhookEventType] = {
    "payment.captured": WebhookEventType.PAYMENT_SUCCEEDED,
    "order.paid": WebhookEventType.PAYMENT_SUCCEEDED,
    "payment.failed": WebhookEventType.PAYMENT_FAILED,
    "payment.authorized": WebhookEventType.PAYMENT_PENDING,
}


class RazorpayTestModeViolation(Exception):
    """A non-test credential was supplied. Refused before any network call."""

    reason_code = "RAZORPAY_TEST_MODE_REQUIRED"


class RazorpayTestPaymentProvider:
    """Razorpay adapter, restricted to test mode. Status: ``partial``.

    ``http_client`` is injected rather than constructed so the adapter can be
    unit-tested offline. There is no default client: constructing one implicitly
    would make it possible to reach the network by accident from a test.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        key_id: str,
        key_secret: str,
        webhook_secret: str,
        http_client: Any = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        # Enforced BEFORE anything is stored, so a live key never even lands in
        # an attribute. This is the "no real-money payments" rule made
        # structural rather than procedural.
        require(
            key_id.startswith(TEST_KEY_PREFIX),
            "razorpay.test_mode_only",
            f"key_id must be a Razorpay TEST key (prefix '{TEST_KEY_PREFIX}'); "
            "PACTRA never runs against live credentials",
        )
        require(
            bool(key_secret),
            "razorpay.key_secret_present",
            "RAZORPAY_KEY_SECRET is not set; secrets come from the environment only",
        )
        require(
            bool(webhook_secret),
            "razorpay.webhook_secret_present",
            "RAZORPAY_WEBHOOK_SECRET is not set; webhooks cannot be verified without it",
        )
        self.key_id = key_id
        # Never logged, never serialized, never returned.
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._http = http_client
        self._timeout = timeout_seconds

    def __repr__(self) -> str:
        """Redacted by construction, so a stray log line cannot leak a secret."""
        return f"<RazorpayTestPaymentProvider key_id={self.key_id!r} secret=REDACTED>"

    # ------------------------------------------------------------------ #
    # Orders API
    # ------------------------------------------------------------------ #
    def _require_client(self) -> Any:
        if self._http is None:
            raise ProviderTransientError(
                self.name, "no HTTP client configured for the Razorpay adapter"
            )
        return self._http

    @staticmethod
    def _to_paise(amount_inr: int) -> int:
        """Razorpay amounts are in the smallest currency unit."""
        return amount_inr * 100

    def _order_to_payment(self, order: dict) -> ProviderPayment:
        """Translate a Razorpay order into PACTRA's vocabulary.

        An unrecognised status maps to PENDING rather than to a guess: reporting
        an order PACTRA does not understand as succeeded or failed would be
        inventing an outcome. PENDING keeps it in reconciliation, which is the
        honest place for something not yet understood.
        """
        status = _ORDER_STATUS_MAP.get(str(order.get("status", "")), ProviderPaymentStatus.PENDING)
        return ProviderPayment(
            provider=self.name,
            provider_payment_id=str(order["id"]),
            status=status,
            # Razorpay reports paise; PACTRA's domain is whole INR.
            amount_inr=int(order.get("amount", 0)) // 100,
            currency=str(order.get("currency", "INR")),
            idempotency_key=order.get("receipt"),
            idempotent_replay=False,
        )

    async def create_payment(self, request: PaymentRequest) -> ProviderPayment:
        """Create a Razorpay Order (test mode).

        NOTE: this creates an ORDER, not a captured payment. See the module
        docstring — the adapter is ``partial`` and does not claim otherwise.
        """
        client = self._require_client()
        payload = {
            "amount": self._to_paise(request.amount_inr),
            "currency": request.currency,
            # PACTRA's idempotency key. Razorpay does not enforce uniqueness on
            # this field, so it is a correlation handle for reconciliation, not
            # a provider-side idempotency guarantee.
            "receipt": request.idempotency_key,
            "notes": {"pactra_txn": request.transaction_digest_prefix},
        }
        try:
            response = await client.post(
                f"{API_BASE}/orders",
                json=payload,
                auth=(self.key_id, self._key_secret),
                timeout=self._timeout,
            )
        except Exception as exc:
            # Any transport failure is UNCERTAIN, never a failure: the order may
            # have been created before the response was lost. Collapsing this
            # into "failed" is the duplicate-charge bug.
            raise ProviderTimeout(self.name, f"transport error: {type(exc).__name__}") from exc

        return self._interpret_create(response)

    def _interpret_create(self, response: Any) -> ProviderPayment:
        status_code = int(response.status_code)
        if 200 <= status_code < 300:
            return self._order_to_payment(response.json())
        if status_code == 429 or status_code >= 500:
            raise ProviderTransientError(self.name, f"HTTP {status_code} from Razorpay")
        # 4xx other than rate limiting: Razorpay answered and refused.
        raise ProviderTerminalError(self.name, f"HTTP {status_code} from Razorpay")

    async def get_payment(
        self,
        *,
        provider_payment_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProviderPayment | None:
        """Look an order up by id, or by the receipt PACTRA set.

        The receipt lookup is what closes the lost-response gap: after a create
        whose response never arrived, the receipt is the only handle PACTRA has.
        """
        client = self._require_client()
        try:
            if provider_payment_id is not None:
                response = await client.get(
                    f"{API_BASE}/orders/{provider_payment_id}",
                    auth=(self.key_id, self._key_secret),
                    timeout=self._timeout,
                )
                if int(response.status_code) == 404:
                    return None
                if not 200 <= int(response.status_code) < 300:
                    raise ProviderTransientError(
                        self.name, f"HTTP {response.status_code} from Razorpay"
                    )
                return self._order_to_payment(response.json())

            if idempotency_key is None:
                return None

            response = await client.get(
                f"{API_BASE}/orders",
                params={"receipt": idempotency_key},
                auth=(self.key_id, self._key_secret),
                timeout=self._timeout,
            )
        except ProviderTransientError:
            raise
        except Exception as exc:
            raise ProviderTransientError(
                self.name, f"transport error: {type(exc).__name__}"
            ) from exc

        if not 200 <= int(response.status_code) < 300:
            raise ProviderTransientError(self.name, f"HTTP {response.status_code} from Razorpay")

        items = response.json().get("items") or []
        if not items:
            # The provider positively holds nothing for this receipt.
            return None
        if len(items) > 1:
            # Razorpay does not enforce receipt uniqueness (see limitation 1),
            # so this list CAN come back with more than one order. Picking the
            # first would resolve the lookup by discarding the evidence that
            # two orders exist for one logical payment — precisely the
            # duplicate Phase 4 is built to prevent. Raising keeps the intent
            # uncertain and routes it to a human instead of quietly adopting an
            # arbitrary one of the two.
            raise ProviderTransientError(
                self.name,
                f"{len(items)} Razorpay orders share receipt {idempotency_key!r}; "
                "refusing to adopt one arbitrarily",
            )
        return self._order_to_payment(items[0])

    # ------------------------------------------------------------------ #
    # Webhooks — this part IS faithful to documented Razorpay behaviour
    # ------------------------------------------------------------------ #
    def verify_webhook(self, *, body: bytes, signature: str) -> VerifiedWebhookEvent:
        """Verify ``X-Razorpay-Signature``.

        Razorpay documents this as the hex-encoded HMAC-SHA256 of the RAW
        request body under the webhook secret. Recomputed over the exact bytes
        received — re-serializing first would change them — and compared in
        constant time.
        """
        expected = hmac.new(self._webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise WebhookVerificationError(self.name, "X-Razorpay-Signature does not match")

        # Parsed only after the MAC verifies.
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError(self.name, "body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise WebhookVerificationError(self.name, "body is not a JSON object")

        razorpay_event = str(parsed.get("event", ""))
        event_type = _WEBHOOK_EVENT_MAP.get(razorpay_event)
        if event_type is None:
            # An undocumented or unmapped event is refused, not guessed at.
            raise WebhookVerificationError(
                self.name, f"unsupported Razorpay event '{razorpay_event}'"
            )

        order_id = _extract_order_id(parsed)
        if order_id is None:
            raise WebhookVerificationError(
                self.name, "webhook payload names no order to correlate against"
            )

        event_id = parsed.get("id") or parsed.get("event_id")
        if not event_id:
            # Without a provider event id there is nothing to deduplicate on,
            # and a webhook that cannot be deduplicated cannot be idempotent.
            raise WebhookVerificationError(self.name, "webhook payload carries no event id")

        return VerifiedWebhookEvent(
            provider=self.name,
            provider_event_id=str(event_id),
            event_type=event_type,
            provider_payment_id=order_id,
            sequence=None,
        )


def _extract_order_id(payload: dict) -> str | None:
    """Pull the order id out of a Razorpay webhook envelope.

    Razorpay nests entities under ``payload.<entity>.entity``. Only the two
    shapes this adapter maps are read; anything else returns None and the
    webhook is refused rather than partially understood.
    """
    entities = payload.get("payload")
    if not isinstance(entities, dict):
        return None
    for key in ("order", "payment"):
        wrapper = entities.get(key)
        if not isinstance(wrapper, dict):
            continue
        entity = wrapper.get("entity")
        if not isinstance(entity, dict):
            continue
        order_id = entity.get("id") if key == "order" else entity.get("order_id")
        if order_id:
            return str(order_id)
    return None


def from_environment(http_client: Any = None) -> RazorpayTestPaymentProvider:
    """Build the adapter from environment variables only.

    There is no source-code default for either secret. A missing secret raises
    rather than falling back, because a fallback would be a credential in the
    repository.
    """
    import os

    return RazorpayTestPaymentProvider(
        key_id=os.environ.get("RAZORPAY_KEY_ID", ""),
        key_secret=os.environ.get("RAZORPAY_KEY_SECRET", ""),
        webhook_secret=os.environ.get("RAZORPAY_WEBHOOK_SECRET", ""),
        http_client=http_client,
    )
