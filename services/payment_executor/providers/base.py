"""The ``PaymentProvider`` protocol and its error vocabulary.

Orchestration depends on THIS module and never on a concrete provider. That is
not stylistic: the reliability invariants — at most one logical payment, safe
retry, recoverable uncertainty — are properties of the executor, and they are
only credible if they can be proven against a provider whose faults are
deterministic. ``FakePaymentProvider`` exists to make them provable; Razorpay
is added only after they hold.

The error taxonomy is the contract that matters most:

``ProviderTimeout``
    The call did not complete. **The provider may or may not have created a
    payment.** This is not a failure — it is an absence of information, and the
    executor must treat it as uncertainty rather than as either outcome.

``ProviderTransientError``
    The provider operation did not settle successfully, but a later lookup or
    operation may succeed. This classification alone never licenses another
    non-idempotent create; the provider contract and durable fence decide that.

``ProviderTerminalError``
    The provider answered, and the answer was "no". Retrying cannot change it.

Conflating the first with either of the others is the classic duplicate-charge
bug: treat a timeout as a failure and you re-create a payment that already
exists; treat it as a success and you record money moved that never did.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from packages.schemas.payment import (
    PaymentRequest,
    ProviderPayment,
    VerifiedWebhookEvent,
)


class ProviderError(Exception):
    """Base class for every provider-side failure."""

    reason_code = "PROVIDER_ERROR"

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.provider = provider
        self.detail = detail


class ProviderTimeout(ProviderError):
    """The call did not complete. Whether a payment was created is UNKNOWN.

    The executor must never resolve this by guessing. It records the payment as
    uncertain and lets reconciliation ask the provider what actually happened.
    """

    reason_code = "PAYMENT_PROVIDER_TIMEOUT"


class ProviderTransientError(ProviderError):
    """A transient operation failure; never by itself create-retry permission."""

    reason_code = "PROVIDER_TRANSIENT_FAILURE"


class ProviderAmbiguity(ProviderTransientError):
    """Provider evidence names more than one possible remote payment.

    This is retryable only as a LOOKUP: a later search may produce clearer
    evidence.  It never licenses another create operation.
    """

    reason_code = "PROVIDER_AMBIGUITY"


class ProviderTerminalError(ProviderError):
    """The provider refused permanently. A retry cannot succeed."""

    reason_code = "PROVIDER_TERMINAL_FAILURE"


class ProviderPaymentMismatch(ProviderError, ValueError):
    """A provider response does not describe the intent PACTRA requested.

    A successful HTTP response is still untrusted input.  A mismatched amount,
    currency, provider, or idempotency key is evidence that a provider payment
    may exist, but it is not evidence that the approved payment succeeded.
    Callers must keep the intent uncertain and reconcile; they must never link
    or settle from this response.
    """

    reason_code = "PROVIDER_RESPONSE_MISMATCH"


@runtime_checkable
class PaymentProvider(Protocol):
    """The only surface through which PACTRA may reach a payment rail."""

    #: Short provider name, persisted on the intent and used to route webhooks.
    name: str
    #: True only when repeated create calls with the same idempotency key are
    #: themselves guaranteed to resolve to one remote payment.  Receipt search
    #: is not such a guarantee.  Providers that set this false require PACTRA's
    #: durable one-way create fence.
    create_retries_are_idempotent: bool

    async def create_payment(self, request: PaymentRequest) -> ProviderPayment:
        """Create (or idempotently return) the payment for ``request``.

        Implementations MUST treat ``request.idempotency_key`` as the provider's
        own idempotency key where the provider supports one, so that a repeated
        call returns the SAME payment instead of creating a second. Where a
        provider does not support it, the adapter must declare
        ``create_retries_are_idempotent = False`` so the executor applies its
        durable one-way create fence.

        Raises ``ProviderTimeout`` / ``ProviderTransientError`` /
        ``ProviderTerminalError`` per the taxonomy in this module's docstring.
        """
        ...

    async def get_payment(
        self,
        *,
        provider_payment_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ProviderPayment | None:
        """Look a payment up by provider id or by idempotency key.

        Lookup BY IDEMPOTENCY KEY is what makes a lost response recoverable: it
        is the only handle PACTRA still holds after a create call whose response
        never arrived. ``None`` permits a create retry only when
        ``create_retries_are_idempotent`` is true. For a fenced provider it is
        still uncertain and never restores create permission.
        """
        ...

    def verify_webhook(
        self,
        *,
        body: bytes,
        signature: str,
        provider_event_id: str | None = None,
    ) -> VerifiedWebhookEvent:
        """Verify a raw webhook body and parse it.

        MUST recompute the MAC over the RAW body with a constant-time compare,
        and MUST raise ``WebhookVerificationError`` before parsing anything as
        state. Returning a ``VerifiedWebhookEvent`` is the adapter asserting the
        signature checked out; the handler accepts no other input type, so an
        unverified payload has no path into state.

        ``provider_event_id`` carries a provider's transport-level delivery id
        when it is not embedded in the signed body. Razorpay supplies its
        unique deduplication key in ``X-Razorpay-Event-Id``.
        """
        ...
