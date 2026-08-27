"""``FakePaymentProvider`` — a deterministic provider with injectable faults.

This is a TEST DOUBLE, and it is deliberately not a trivial stub. To prove
anything about duplicate prevention it has to model the two provider behaviours
that make the problem hard:

1. **Provider-side idempotency.** A repeated ``create_payment`` with the same
   idempotency key returns the SAME payment, flagged ``idempotent_replay``. Real
   rails behave this way, and a fake that created a second payment would let a
   broken executor look correct.
2. **Side effects that outlive the response.** ``TIMEOUT_AFTER_CREATE`` records
   the payment *and then* raises. The caller sees only a timeout, while the
   provider state now contains a payment. This is the exact shape of the lost
   response, and it is why a timeout can never be treated as a failure.

Faults are scripted per call rather than set globally, so a test can say
"time out once, then succeed" and prove that a retry converges instead of
merely proving that a single call behaves.

``created_payments`` is the ground truth the tests assert against: the count of
provider payments for one idempotency key must never exceed one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import deque
from enum import Enum

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

PROVIDER_NAME = "fake"


class FaultMode(str, Enum):
    """Deterministic provider behaviours the executor must survive."""

    #: The call completes and a payment exists.
    SUCCESS = "SUCCESS"
    #: The call times out and the provider created NOTHING.
    TIMEOUT_BEFORE_CREATE = "TIMEOUT_BEFORE_CREATE"
    #: The call times out AFTER the provider created the payment. The response
    #: is lost; the payment is real. The hard case.
    TIMEOUT_AFTER_CREATE = "TIMEOUT_AFTER_CREATE"
    #: The provider answered "not now". Nothing was created.
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    #: The provider answered "no", permanently. Nothing was created.
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    #: The call completes, but the provider reports a payment it already held
    #: for this idempotency key rather than a new one.
    DUPLICATE_RESPONSE = "DUPLICATE_RESPONSE"
    #: The call completes and the payment is accepted but not yet settled, so
    #: the outcome arrives later by webhook.
    PENDING = "PENDING"


class FakePaymentProvider:
    """An in-memory provider. Not thread-safe; one instance per test.

    ``created_payments`` maps idempotency_key -> ProviderPayment and is the
    provider's entire world. Because creation is keyed on the idempotency key,
    "how many payments exist for this key" is answerable exactly, which is the
    measurement every duplicate-prevention test depends on.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        webhook_secret: str = "fake-webhook-secret",
        default_fault: FaultMode = FaultMode.SUCCESS,
    ) -> None:
        self._webhook_secret = webhook_secret
        self.default_fault = default_fault
        self._fault_script: deque[FaultMode] = deque()
        #: idempotency_key -> payment. The provider's own idempotency store.
        self.created_payments: dict[str, ProviderPayment] = {}
        #: provider_payment_id -> idempotency_key, for id-based lookup.
        self._by_provider_id: dict[str, str] = {}
        #: Every create_payment call, in order — including the ones that raised.
        self.create_calls: list[str] = []
        self.get_calls: list[tuple[str | None, str | None]] = []

    # ------------------------------------------------------------------ #
    # Test control
    # ------------------------------------------------------------------ #
    def queue_faults(self, *modes: FaultMode) -> None:
        """Script the next N calls. Later calls fall back to ``default_fault``."""
        self._fault_script.extend(modes)

    def _next_fault(self) -> FaultMode:
        if self._fault_script:
            return self._fault_script.popleft()
        return self.default_fault

    def payment_count_for(self, idempotency_key: str) -> int:
        """How many provider payments exist for this key. Must never exceed 1."""
        return 1 if idempotency_key in self.created_payments else 0

    def settle(self, idempotency_key: str, status: ProviderPaymentStatus) -> ProviderPayment:
        """Move an existing provider payment to a settled status.

        Models the provider settling out-of-band — the event a webhook or a
        reconciliation poll would later report.
        """
        existing = self.created_payments[idempotency_key]
        updated = existing.model_copy(update={"status": status})
        self.created_payments[idempotency_key] = updated
        return updated

    # ------------------------------------------------------------------ #
    # PaymentProvider protocol
    # ------------------------------------------------------------------ #
    def _provider_payment_id(self, request: PaymentRequest) -> str:
        """A stable, opaque provider id derived from the idempotency key.

        Deriving it (rather than using a counter) keeps the fake deterministic
        across runs, which matters because these ids end up in assertions.
        """
        token = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()[:16]
        return f"fake_pay_{token}"

    def _record(self, request: PaymentRequest, status: ProviderPaymentStatus) -> ProviderPayment:
        """Create the payment if this key has none; otherwise return the held one.

        This single method IS the provider's idempotency guarantee, and it is
        why a blind retry cannot produce two payments here.
        """
        held = self.created_payments.get(request.idempotency_key)
        if held is not None:
            return held.model_copy(update={"idempotent_replay": True})

        payment = ProviderPayment(
            provider=self.name,
            provider_payment_id=self._provider_payment_id(request),
            status=status,
            amount_inr=request.amount_inr,
            currency=request.currency,
            idempotency_key=request.idempotency_key,
            idempotent_replay=False,
        )
        self.created_payments[request.idempotency_key] = payment
        self._by_provider_id[payment.provider_payment_id] = request.idempotency_key
        return payment

    async def create_payment(self, request: PaymentRequest) -> ProviderPayment:
        self.create_calls.append(request.idempotency_key)
        fault = self._next_fault()

        if fault is FaultMode.TIMEOUT_BEFORE_CREATE:
            # Nothing is recorded: the provider genuinely holds no payment.
            raise ProviderTimeout(self.name, "connection timed out before the payment was created")

        if fault is FaultMode.TRANSIENT_FAILURE:
            raise ProviderTransientError(self.name, "provider temporarily unavailable")

        if fault is FaultMode.TERMINAL_FAILURE:
            raise ProviderTerminalError(self.name, "payment declined")

        if fault is FaultMode.TIMEOUT_AFTER_CREATE:
            # THE HARD CASE: the payment is real, the response is not.
            self._record(request, ProviderPaymentStatus.SUCCEEDED)
            raise ProviderTimeout(self.name, "connection timed out after the payment was created")

        if fault is FaultMode.PENDING:
            return self._record(request, ProviderPaymentStatus.PENDING)

        if fault is FaultMode.DUPLICATE_RESPONSE:
            # Return whatever this key already maps to; create it first if the
            # test set the mode up front, so the flag is always meaningful.
            payment = self._record(request, ProviderPaymentStatus.SUCCEEDED)
            return payment.model_copy(update={"idempotent_replay": True})

        return self._record(request, ProviderPaymentStatus.SUCCEEDED)

    async def get_payment(
        self,
        *,
        provider_payment_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProviderPayment | None:
        self.get_calls.append((provider_payment_id, idempotency_key))

        if provider_payment_id is not None:
            key = self._by_provider_id.get(provider_payment_id)
            return None if key is None else self.created_payments.get(key)
        if idempotency_key is not None:
            return self.created_payments.get(idempotency_key)
        return None

    # ------------------------------------------------------------------ #
    # Webhooks
    # ------------------------------------------------------------------ #
    def sign(self, body: bytes) -> str:
        """Produce the signature a genuine provider would send for ``body``.

        Test-only helper. It is the same computation ``verify_webhook`` performs,
        which is exactly what makes a forged signature detectable: a test cannot
        accidentally construct a valid one without the secret.
        """
        return hmac.new(self._webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_webhook(self, *, body: bytes, signature: str) -> VerifiedWebhookEvent:
        expected = self.sign(body)
        # Constant-time: a byte-by-byte compare leaks the correct prefix through
        # timing and lets an attacker construct a valid signature incrementally.
        if not hmac.compare_digest(expected, signature):
            raise WebhookVerificationError(self.name, "signature does not match the request body")

        # Parsed only AFTER the MAC verifies. Nothing above this line reads the
        # body as meaning.
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebhookVerificationError(self.name, "body is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise WebhookVerificationError(self.name, "body is not a JSON object")

        try:
            return VerifiedWebhookEvent(
                provider=self.name,
                provider_event_id=str(parsed["event_id"]),
                event_type=WebhookEventType(parsed["event_type"]),
                provider_payment_id=str(parsed["provider_payment_id"]),
                sequence=parsed.get("sequence"),
            )
        except (KeyError, ValueError) as exc:
            # A signed but malformed body is still rejected. A valid MAC proves
            # origin, never that the contents are well-formed.
            raise WebhookVerificationError(self.name, f"malformed webhook body: {exc}") from exc


def webhook_body(
    *,
    event_id: str,
    event_type: WebhookEventType,
    provider_payment_id: str,
    sequence: int | None = None,
) -> bytes:
    """Build a canonical webhook body. Test helper.

    Bytes are produced once and both signed and delivered, because a signature
    covers the exact bytes on the wire — re-serializing before verification is
    a real-world source of spurious failures.
    """
    payload: dict = {
        "event_id": event_id,
        "event_type": event_type.value,
        "provider_payment_id": provider_payment_id,
    }
    if sequence is not None:
        payload["sequence"] = sequence
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
