"""PACTRA shared domain schemas (Pydantic v2).

These are the *trusted* structured types. Any data that originates from
untrusted sources (user free text, merchant agent responses, and — in later
phases — LLM output) must be parsed through one of these strict schemas before
any deterministic component is allowed to act on it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.schemas.provenance import ProvenanceMeta


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalize a datetime read back from storage to timezone-aware UTC.

    SQLite has no timezone-aware type: SQLAlchemy writes UTC and reads back a
    *naive* datetime. Comparing that to an aware `utcnow()` raises TypeError, so
    every datetime crossing the storage boundary is normalized here. Values are
    written as UTC unconditionally, so attaching UTC on read is exact rather
    than a guess. PostgreSQL returns aware values already and is unaffected.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# --------------------------------------------------------------------------- #
# Mission state machine
# --------------------------------------------------------------------------- #
class MissionState(str, Enum):
    CREATED = "CREATED"
    INTENT_PARSED = "INTENT_PARSED"
    DISCOVERING = "DISCOVERING"
    OFFERS_RECEIVED = "OFFERS_RECEIVED"
    OFFERS_NORMALIZED = "OFFERS_NORMALIZED"
    RANKED = "RANKED"
    POLICY_CHECKED = "POLICY_CHECKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    MISSION_CREATED = "MISSION_CREATED"
    INTENT_PARSED = "INTENT_PARSED"
    DISCOVERY_STARTED = "DISCOVERY_STARTED"
    OFFERS_RECEIVED = "OFFERS_RECEIVED"
    OFFERS_NORMALIZED = "OFFERS_NORMALIZED"
    OFFERS_RANKED = "OFFERS_RANKED"
    POLICY_DECISION = "POLICY_DECISION"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    MISSION_DENIED = "MISSION_DENIED"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    # Authorization lifecycle (Phase 3)
    AUTHORIZATION_CREATED = "AUTHORIZATION_CREATED"
    AUTHORIZATION_ACTIVATED = "AUTHORIZATION_ACTIVATED"
    AUTHORIZATION_CONSUMED = "AUTHORIZATION_CONSUMED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_REVOKED = "AUTHORIZATION_REVOKED"
    AUTHORIZATION_REPLAY_DETECTED = "AUTHORIZATION_REPLAY_DETECTED"
    TRANSACTION_BINDING_FAILURE = "TRANSACTION_BINDING_FAILURE"


class PolicyOutcome(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


class ReasonCode(str, Enum):
    # Deny reasons
    NO_VALID_OFFERS = "NO_VALID_OFFERS"
    HARD_LIMIT_EXCEEDED = "HARD_LIMIT_EXCEEDED"
    BLOCKED_MERCHANT = "BLOCKED_MERCHANT"
    MERCHANT_NOT_ALLOWED = "MERCHANT_NOT_ALLOWED"
    RATING_BELOW_MIN = "RATING_BELOW_MIN"
    CURRENCY_NOT_ALLOWED = "CURRENCY_NOT_ALLOWED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    MERCHANT_TRUST_TOO_LOW = "MERCHANT_TRUST_TOO_LOW"
    MERCHANT_IDENTITY_MISMATCH = "MERCHANT_IDENTITY_MISMATCH"
    # Approval reasons
    SOFT_BUDGET_EXCEEDED = "SOFT_BUDGET_EXCEEDED"
    # Allow
    WITHIN_LIMITS = "WITHIN_LIMITS"
    # Kernel (Phase 2)
    AUTHORITY_ESCALATION = "AUTHORITY_ESCALATION"
    CAPABILITY_DENIED = "CAPABILITY_DENIED"
    # Transaction binding / authorization (Phase 3)
    TRANSACTION_BINDING_FAILURE = "TRANSACTION_BINDING_FAILURE"
    AUTHORIZATION_REPLAY_DETECTED = "AUTHORIZATION_REPLAY_DETECTED"
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    AUTHORIZATION_NOT_ACTIVE = "AUTHORIZATION_NOT_ACTIVE"
    AUTHORIZATION_NOT_FOUND = "AUTHORIZATION_NOT_FOUND"


# --------------------------------------------------------------------------- #
# Constraints / intent (trusted after validation)
# --------------------------------------------------------------------------- #
class MissionConstraints(BaseModel):
    """Structured, validated purchase constraints.

    In Phase 1 these are supplied directly by the caller. In Phase 4 an LLM
    may *propose* these values, but they will still be validated through this
    exact schema before any deterministic component uses them.
    """

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=120)
    soft_budget_inr: int = Field(gt=0, description="Approval-required threshold")
    hard_limit_inr: int = Field(gt=0, description="Absolute transaction ceiling")
    min_rating: float = Field(default=0.0, ge=0.0, le=5.0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    allowed_merchants: list[str] | None = Field(default=None)
    blocked_merchants: list[str] = Field(default_factory=list)
    min_merchant_trust: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _check_budget_ordering(self) -> MissionConstraints:
        if self.soft_budget_inr > self.hard_limit_inr:
            raise ValueError("soft_budget_inr cannot exceed hard_limit_inr")
        return self


class CreateMissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_query: str | None = Field(default=None, max_length=2000)
    quantity: int = Field(default=1, ge=1, le=100)
    constraints: MissionConstraints


# --------------------------------------------------------------------------- #
# Offers
# --------------------------------------------------------------------------- #
# JSON-safe value types a merchant may attempt to claim. Deliberately a closed
# union rather than `Any`: every rejected claim is written verbatim into the
# hash-chained audit ledger, which must stay serializable.
ClaimValue = int | float | bool | str | list[str] | None


class RawMerchantOffer(BaseModel):
    """An offer exactly as returned by an (untrusted) merchant agent.

    This model carries PAYLOAD DATA ONLY. It deliberately has no field capable
    of carrying merchant identity or merchant trust as trusted values:

    * `merchant_id` is retained purely as a *claimed* identity. It is verified
      against the transport-authenticated `MerchantIdentity` at ingress and a
      mismatch rejects the offer (MERCHANT_IDENTITY_MISMATCH). It is never the
      source identity for provenance, ranking, or allow/block policy.
    * There is no `merchant_trust` field and no `merchant_name` field. Trust and
      display name come from the server-owned `MerchantRegistry`. Because
      `extra="ignore"` drops unknown keys, a merchant sending
      `{"merchant_trust": 1.0}` has that key silently discarded — self-assigning
      a trust score is structurally impossible, not merely disallowed.

    `extra="ignore"` is otherwise deliberate: merchants may attempt to smuggle
    extra fields (fake tool calls, injected instructions, forged security
    labels). Unknown fields are dropped here and never reach the trusted layer.
    `description` is retained ONLY as opaque data and is intentionally NOT
    propagated into NormalizedOffer.
    """

    model_config = ConfigDict(extra="ignore")

    merchant_id: str = Field(
        min_length=1,
        max_length=120,
        description="CLAIMED identity — untrusted, verified against the authenticated identity",
    )
    product_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    price: float = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    rating: float = Field(ge=0.0, le=5.0)
    in_stock: bool = True
    offered_at: datetime = Field(default_factory=utcnow)
    # Untrusted merchant-proposed policy overrides. A malicious merchant may try
    # to raise the user's budget or widen its allow-list here; the kernel
    # adjudicates every claim through the authority lattice and blocks any that
    # target higher-authority state.
    claims: dict[str, ClaimValue] = Field(default_factory=dict)


class NormalizedOffer(BaseModel):
    """Projection (DTO) of a merchant offer for persistence and API output.

    IMPORTANT: a normalized offer is STRUCTURALLY VALIDATED BUT STILL UNTRUSTED.
    Passing Pydantic validation does not make merchant data trusted — it only
    means the shape is well-formed. The authoritative, coupled representation the
    kernel reasons over is ``ProvenancedOffer`` (packages/schemas/kernel.py),
    where every value is bound to its provenance/taint. This DTO carries a
    `provenance` sidecar purely so the DB/API can surface that metadata.

    Note the absence of `description`: free-form merchant text is dropped
    entirely and never reaches ranking or policy.

    `merchant_id`, `merchant_name` and `merchant_trust` here are the TRUSTED
    values (authenticated identity + server-owned registry), never the payload's
    claims. `claimed_merchant_id` preserves what the payload asserted so an
    identity mismatch remains visible in persistence and audit.
    """

    model_config = ConfigDict(extra="forbid")

    offer_id: uuid.UUID = Field(default_factory=new_uuid)
    # Server-computed content fingerprint of this offer's security-relevant
    # values (Phase 3). Bound into the transaction digest, so a merchant that
    # edits its offer after approval cannot keep the authorization valid.
    offer_version: str
    merchant_id: str
    claimed_merchant_id: str
    merchant_name: str
    merchant_trust: float = Field(ge=0.0, le=1.0)
    product_id: str
    title: str
    amount_inr: int = Field(ge=0, description="Unit price in whole INR")
    currency: str
    rating: float = Field(ge=0.0, le=5.0)
    in_stock: bool
    offered_at: datetime
    valid: bool = True
    rejection_reasons: list[ReasonCode] = Field(default_factory=list)
    rank: int | None = None
    # Per-field provenance/taint for merchant-derived values (Phase 2). Untrusted
    # merchant data retains source + authority + trust + taint after normalization.
    provenance: dict[str, ProvenanceMeta] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Policy decision
# --------------------------------------------------------------------------- #
class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: PolicyOutcome
    # Version of the deterministic ruleset that produced this decision. Bound
    # into the transaction digest so an approval cannot be carried across a
    # policy change (Phase 3).
    policy_version: str
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    requested_amount: int | None = None
    soft_budget: int
    hard_limit: int
    selected_offer_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# Audit event (tamper-evident chain foundation; /verify lands in Phase 6)
# --------------------------------------------------------------------------- #
GENESIS_HASH = "0" * 64


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID = Field(default_factory=new_uuid)
    mission_id: uuid.UUID
    sequence: int = Field(ge=0)
    event_type: EventType
    actor: str
    payload: dict = Field(default_factory=dict)
    previous_hash: str
    event_hash: str
    created_at: datetime = Field(default_factory=utcnow)
