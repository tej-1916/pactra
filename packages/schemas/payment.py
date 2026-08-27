"""Payment domain types (Phase 4).

Three separate vocabularies live here, and keeping them separate is the point:

* ``PaymentIntentState`` — PACTRA's own belief about a logical payment.
* ``ProviderPaymentStatus`` — what a payment PROVIDER says about its payment.
* ``WebhookEventType`` — what a provider *claims* happened, in an unverified
  message.

Collapsing them would let an untrusted provider/webhook string become an
internal state directly. Instead every provider value is translated by
deterministic code (``provider_status_to_state``) after verification, so an
unknown or hostile provider status can never name an internal state.

HONEST SCOPING: a ``PaymentIntent`` is an intent to move money through a
provider. Nothing here settles money by itself, and Phase 4 runs against
``FakePaymentProvider`` plus Razorpay TEST MODE only.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from packages.schemas.canonical import canonical_digest

#: Domain separator for the idempotent-request fingerprint. Bump the suffix if
#: the covered field set ever changes, so old and new fingerprints cannot be
#: confused for one another.
PAYMENT_REQUEST_FINGERPRINT_DOMAIN = "pactra-payment-request-v1"


# --------------------------------------------------------------------------- #
# PaymentIntent state machine
# --------------------------------------------------------------------------- #
class PaymentIntentState(str, Enum):
    """The lifecycle of ONE logical payment.

    ``PROVIDER_PENDING`` is the *uncertain* state, and it is deliberately one
    state rather than two. When a provider call times out, PACTRA cannot know
    whether the provider created a payment before the response was lost. There
    is no observation that distinguishes "timeout before create" from "timeout
    after create" from the caller's side, so encoding a guess as a state would
    be encoding a lie. The single honest answer is "a provider payment may
    exist and its outcome is unknown", which is exactly PROVIDER_PENDING, and
    the only way out is reconciliation.
    """

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    PROVIDER_PENDING = "PROVIDER_PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"


#: States from which no further transition is permitted. A settled payment can
#: never be moved again — this is what stops a delayed or out-of-order webhook
#: from regressing a completed payment.
TERMINAL_PAYMENT_STATES = frozenset(
    {
        PaymentIntentState.SUCCEEDED,
        PaymentIntentState.FAILED_TERMINAL,
        PaymentIntentState.CANCELLED,
    }
)

#: States in which a provider payment may already exist, so re-creating one
#: blindly would risk a duplicate charge.
UNCERTAIN_PAYMENT_STATES = frozenset({PaymentIntentState.PROVIDER_PENDING})


# --------------------------------------------------------------------------- #
# Outbox
# --------------------------------------------------------------------------- #
class OutboxStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class OutboxEventType(str, Enum):
    PAYMENT_CREATE_REQUESTED = "PAYMENT_CREATE_REQUESTED"
    PAYMENT_RECONCILE_REQUESTED = "PAYMENT_RECONCILE_REQUESTED"


# --------------------------------------------------------------------------- #
# Provider-side vocabulary (UNTRUSTED until translated)
# --------------------------------------------------------------------------- #
class ProviderPaymentStatus(str, Enum):
    """What the provider says about its own payment object."""

    CREATED = "CREATED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


#: Deterministic translation from a provider's answer to PACTRA's own state.
#: A provider status PACTRA does not recognise cannot appear here, so it can
#: never become an internal state; callers treat an unmapped status as
#: uncertain and reconcile again.
_PROVIDER_STATUS_TO_STATE: dict[ProviderPaymentStatus, PaymentIntentState] = {
    ProviderPaymentStatus.CREATED: PaymentIntentState.PROVIDER_PENDING,
    ProviderPaymentStatus.PENDING: PaymentIntentState.PROVIDER_PENDING,
    ProviderPaymentStatus.SUCCEEDED: PaymentIntentState.SUCCEEDED,
    ProviderPaymentStatus.FAILED: PaymentIntentState.FAILED_TERMINAL,
}


def provider_status_to_state(status: ProviderPaymentStatus) -> PaymentIntentState:
    """Translate a provider status into PACTRA's state vocabulary."""
    return _PROVIDER_STATUS_TO_STATE[status]


class PaymentRequest(BaseModel):
    """What PACTRA asks a provider to do. Built entirely from server-side state.

    ``idempotency_key`` is passed to the provider as well as being PACTRA's own
    unique key, so provider-side idempotency and PACTRA-side idempotency
    correlate on the same value. That correlation is what makes a lost response
    recoverable: the payment the provider may have created is findable by the
    key PACTRA already holds.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(min_length=1, max_length=200)
    amount_inr: int = Field(ge=1)
    currency: str = Field(min_length=3, max_length=3)
    merchant_id: str = Field(min_length=1, max_length=120)
    #: Truncated digest prefix, for provider-side correlation in a demo/test
    #: dashboard. Deliberately not the whole digest: it is a commitment PACTRA
    #: holds, not something a third party needs a copy of.
    transaction_digest_prefix: str = Field(min_length=1, max_length=32)


class ProviderPayment(BaseModel):
    """A payment as the provider reports it. UNTRUSTED shape, validated here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=40)
    provider_payment_id: str = Field(min_length=1, max_length=200)
    status: ProviderPaymentStatus
    amount_inr: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    idempotency_key: str | None = None
    #: True when the provider returned an ALREADY EXISTING payment for this
    #: idempotency key rather than creating a new one. Provider-side idempotency
    #: is what makes a blind retry safe at the second layer.
    idempotent_replay: bool = False


# --------------------------------------------------------------------------- #
# Webhooks (UNTRUSTED until the signature verifies)
# --------------------------------------------------------------------------- #
class WebhookEventType(str, Enum):
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_PENDING = "payment.pending"


_WEBHOOK_TYPE_TO_STATE: dict[WebhookEventType, PaymentIntentState] = {
    WebhookEventType.PAYMENT_SUCCEEDED: PaymentIntentState.SUCCEEDED,
    WebhookEventType.PAYMENT_FAILED: PaymentIntentState.FAILED_TERMINAL,
    WebhookEventType.PAYMENT_PENDING: PaymentIntentState.PROVIDER_PENDING,
}


def webhook_type_to_state(event_type: WebhookEventType) -> PaymentIntentState:
    return _WEBHOOK_TYPE_TO_STATE[event_type]


class VerifiedWebhookEvent(BaseModel):
    """A webhook whose signature ALREADY verified.

    This type exists so "verified" is carried by the type system rather than by
    a boolean somebody might forget to check. A provider returns one of these
    only after ``verify_webhook`` has recomputed the MAC over the raw body; the
    handler accepts nothing else. Payload state is therefore never read before
    verification — there is no code path that can construct this from an
    unverified body.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=40)
    #: Provider-assigned event id. UNIQUE per provider in storage, which is what
    #: makes duplicate delivery idempotent.
    provider_event_id: str = Field(min_length=1, max_length=200)
    event_type: WebhookEventType
    provider_payment_id: str = Field(min_length=1, max_length=200)
    #: Provider-assigned monotonic ordinal where the provider supplies one.
    #: Used only to DETECT out-of-order delivery for audit; it is never trusted
    #: to authorize a transition. The state machine decides that.
    sequence: int | None = None
    occurred_at: datetime | None = None


class WebhookVerificationError(Exception):
    """The signature did not verify. The payload must not be read as state."""

    reason_code = "WEBHOOK_SIGNATURE_INVALID"

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.provider = provider
        self.detail = detail


# --------------------------------------------------------------------------- #
# Idempotent-request fingerprint
# --------------------------------------------------------------------------- #
def request_fingerprint(
    *,
    mission_id: uuid.UUID,
    authorization_id: uuid.UUID,
    transaction_digest: str,
    amount_inr: int,
    currency: str,
    merchant_id: str,
    provider: str,
) -> str:
    """Commitment to everything that makes two payment requests "the same".

    Reusing an idempotency key is only legitimate when the request is
    genuinely identical. Comparing fingerprints — rather than comparing a
    couple of fields by hand — means a field added to the request without being
    added here is a visible omission, not a silent hole through which a
    different amount could ride in on an old key.
    """
    return canonical_digest(
        PAYMENT_REQUEST_FINGERPRINT_DOMAIN,
        {
            "mission_id": str(mission_id),
            "authorization_id": str(authorization_id),
            "transaction_digest": transaction_digest,
            "amount_inr": amount_inr,
            "currency": currency,
            "merchant_id": merchant_id,
            "provider": provider,
        },
    )
