"""API response shapes (read models)."""

from __future__ import annotations

import uuid
from datetime import datetime

from packages.schemas.approval import SIGNATURE_HEX_LENGTH
from pydantic import BaseModel, ConfigDict, Field


class OfferOut(BaseModel):
    offer_id: uuid.UUID
    offer_version: str
    merchant_id: str
    merchant_name: str
    merchant_trust: float
    product_id: str
    title: str
    amount_inr: int
    currency: str
    rating: float
    in_stock: bool
    valid: bool
    rejection_reasons: list[str]
    rank: int | None


class PolicyDecisionOut(BaseModel):
    decision: str
    policy_version: str
    reason_codes: list[str]
    requested_amount: int | None
    soft_budget: int
    hard_limit: int
    selected_offer_id: uuid.UUID | None


class AuditEventOut(BaseModel):
    event_id: uuid.UUID
    sequence: int
    event_type: str
    actor: str
    payload: dict
    previous_hash: str
    event_hash: str
    created_at: datetime


class AuthorizationOut(BaseModel):
    """Public projection of an authorization artifact.

    The ``nonce`` is deliberately absent. It is server-held material that is
    part of the digest preimage; disclosing it would hand out the one input an
    attacker cannot otherwise guess. Nothing outside the kernel needs it, so
    nothing outside the kernel receives it.

    The artifact remains server-issued. ``USER_ED25519`` activation additionally
    carries a LOCAL CRYPTOGRAPHIC APPROVAL PROOF made by the pre-enrolled demo
    approver; the full signature is deliberately not exposed by this read model.
    """

    authorization_id: uuid.UUID
    mission_id: uuid.UUID
    status: str
    transaction_digest: str
    binding_version: str
    policy_version: str
    offer_version: str
    approval_scheme: str
    signing_key_id: str | None
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    bound_merchant_id: str
    bound_product_id: str
    bound_quantity: int
    bound_amount_inr: int
    bound_currency: str


class ApprovalRequest(BaseModel):
    """Proof submission. Algorithm and public key are intentionally absent."""

    model_config = ConfigDict(extra="forbid")

    signing_key_id: str = Field(min_length=1, max_length=120)
    signature: str = Field(
        min_length=SIGNATURE_HEX_LENGTH,
        max_length=SIGNATURE_HEX_LENGTH,
        pattern=r"^[0-9a-f]+$",
    )


class BoundTransactionSummary(BaseModel):
    merchant: str
    product: str
    quantity: int
    amount: int
    currency: str
    expiry: datetime


class ApprovalChallengeOut(BaseModel):
    authorization_id: uuid.UUID
    mission_id: uuid.UUID
    binding_version: str
    transaction_digest: str
    signing_key_id: str
    approval_scheme: str
    approval_message_hex: str
    transaction: BoundTransactionSummary


class MissionOut(BaseModel):
    id: uuid.UUID
    state: str
    raw_query: str | None
    quantity: int
    offers: list[OfferOut]
    policy_decision: PolicyDecisionOut | None
    created_at: datetime


class PaymentIntentOut(BaseModel):
    """Public projection of a payment intent.

    Absent by design: ``request_fingerprint`` and the full ``transaction_digest``
    preimage inputs. The fingerprint is what an idempotency-conflict check
    compares against, and handing it out would let a caller probe for a
    colliding request; the digest is shown because Phase 3 already exposes it on
    the authorization artifact, so it discloses nothing new.
    """

    payment_intent_id: uuid.UUID
    mission_id: uuid.UUID
    authorization_id: uuid.UUID
    state: str
    idempotency_key: str
    amount_inr: int
    currency: str
    merchant_id: str
    provider: str
    #: Public test key used by Razorpay Checkout. Never a secret; present only
    #: for Razorpay test intents.
    provider_key_id: str | None
    provider_payment_id: str | None
    provider_order_id: str | None
    provider_transaction_id: str | None
    provider_receipt: str | None
    provider_status: str | None
    provider_attempts: int | None
    attempts: int
    last_reason_code: str | None
    created_at: datetime


class WebhookAck(BaseModel):
    """What PACTRA did with one webhook delivery.

    ``applied`` is reported honestly: a duplicate or out-of-order delivery is
    ACCEPTED (so the provider stops retrying) while having changed nothing.
    Conflating the two would tell the provider a state change happened that did
    not.
    """

    accepted: bool
    applied: bool
    reason_code: str | None
    state: str | None
