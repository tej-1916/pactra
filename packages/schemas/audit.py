"""Audit verification + mission replay types (Phase 5).

Two vocabularies live here and are deliberately kept apart from ``ReasonCode``
in ``domain.py``. ``ReasonCode`` answers "why was this transaction allowed,
denied, or refused" — it is the policy and payment decision vocabulary.
Verification and replay answer a different question entirely ("is this history
intact", "could it be reconstructed"), and folding them into the decision
vocabulary would make ``AUDIT_VALID`` look like a reason to permit a payment.
They are separate enums for the same reason ``PaymentIntentState`` and
``ProviderPaymentStatus`` are separate.

These models are also the API response shapes. They are written to be API-safe
by construction rather than projected through a second read model: verification
carries hashes and positions but never an event payload, and the replay
projection carries only values the ledger already exposes through
``GET /missions/{id}/events``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from packages.schemas.approval import ApprovalScheme
from packages.schemas.domain import EventType, PolicyOutcome
from packages.schemas.payment import PaymentIntentState

# --------------------------------------------------------------------------- #
# C1 Decision Trace
# --------------------------------------------------------------------------- #


class DecisionStage(str, Enum):
    """The three security stages PACTRA exposes to a trace consumer."""

    ADMIT = "ADMIT"
    BIND = "BIND"
    EXECUTE = "EXECUTE"


class DecisionTraceVerdict(str, Enum):
    """What the source event established; never model reasoning."""

    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    IGNORED = "IGNORED"
    ADVISORY = "ADVISORY"


class DecisionTraceNextAction(str, Enum):
    """The next permitted workflow action after this recorded decision."""

    CONTINUE_ADMIT = "CONTINUE_ADMIT"
    CONTINUE_BIND = "CONTINUE_BIND"
    AWAIT_USER_SIGNATURE = "AWAIT_USER_SIGNATURE"
    CREATE_PAYMENT_INTENT = "CREATE_PAYMENT_INTENT"
    DISPATCH_PAYMENT = "DISPATCH_PAYMENT"
    AWAIT_PROVIDER = "AWAIT_PROVIDER"
    RECONCILE_PAYMENT = "RECONCILE_PAYMENT"
    RETRY_PAYMENT = "RETRY_PAYMENT"
    NONE = "NONE"


class DecisionTraceEvidenceRef(BaseModel):
    """Reference to the verified audit event from which an entry was projected."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: uuid.UUID
    sequence: int = Field(ge=0)
    actor: str


class DecisionTraceEntry(BaseModel):
    """Allow-listed action/security projection of one hash-chained event.

    Raw payloads are intentionally absent. In particular this model has no
    signature, nonce, key material, free-form merchant content, provider
    secret, or model-reasoning field.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: DecisionStage
    event_type: EventType
    verdict: DecisionTraceVerdict
    reason_codes: list[str]
    # Required-but-nullable: null means the source event recorded no dotted
    # invariant identifier; the projection never fabricates one.
    invariant_id: str | None
    approval_scheme: ApprovalScheme | None
    policy_outcome: PolicyOutcome | None
    payment_state: PaymentIntentState | None
    advisory: bool
    next_action: DecisionTraceNextAction
    evidence: DecisionTraceEvidenceRef
    recorded_at: datetime


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #


class AuditReasonCode(str, Enum):
    """Why a chain verified, or the FIRST way in which it did not.

    Exactly one failure is reported — the earliest one by sequence. A tampered
    event breaks its own hash AND every link after it, so listing all of them
    would report one act of tampering as dozens of findings and bury the
    position that actually matters.
    """

    AUDIT_VALID = "AUDIT_VALID"
    #: Sequences are not the contiguous run 0..N-1. A deleted middle event, an
    #: injected event, or a renumbered one all land here.
    AUDIT_SEQUENCE_GAP = "AUDIT_SEQUENCE_GAP"
    #: An event does not link to the hash of the event before it.
    AUDIT_PREVIOUS_HASH_MISMATCH = "AUDIT_PREVIOUS_HASH_MISMATCH"
    #: The event's own stored hash is not what its contents hash to. This is
    #: what a payload edit produces.
    AUDIT_EVENT_HASH_MISMATCH = "AUDIT_EVENT_HASH_MISMATCH"
    #: Event 0 does not carry the genesis previous_hash.
    AUDIT_GENESIS_INVALID = "AUDIT_GENESIS_INVALID"
    #: The row is not shaped like an audit event at all (negative sequence,
    #: non-hex hash, non-object payload). Checked before hashing, because a
    #: malformed row's hash comparison would be meaningless.
    AUDIT_EVENT_MALFORMED = "AUDIT_EVENT_MALFORMED"


class AuditVerificationResult(BaseModel):
    """The outcome of verifying one mission's chain.

    ``events_checked`` counts events the verifier actually validated, so on a
    failure it is the position of the break rather than the size of the table.
    It is the honest measure of how much of the chain is known-good.

    Deliberately absent: event payloads. A verification result says whether
    history is intact and where it broke; reproducing the tampered content is
    not part of that answer, and the events endpoint already serves anyone
    entitled to read it.
    """

    model_config = ConfigDict(extra="forbid")

    valid: bool
    mission_id: uuid.UUID
    events_checked: int = Field(ge=0)
    #: The sequence at which verification stopped. None on a valid chain.
    first_invalid_sequence: int | None = None
    reason_code: AuditReasonCode = AuditReasonCode.AUDIT_VALID
    #: Populated only for hash failures, and only with hashes — never payloads.
    expected_hash: str | None = None
    actual_hash: str | None = None
    detail: str | None = None


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #


class ReplayReasonCode(str, Enum):
    """Why a replay produced a trusted projection, or why it refused to."""

    REPLAY_OK = "REPLAY_OK"
    #: The chain did not verify. Replay is refused BEFORE reducing, because a
    #: projection built from tampered history is a confident-looking lie.
    REPLAY_AUDIT_INVALID = "REPLAY_AUDIT_INVALID"
    #: An event type this build does not know. Fail-closed; see
    #: services/audit_ledger/replay.py for why it is not skipped.
    REPLAY_UNSUPPORTED_EVENT_TYPE = "REPLAY_UNSUPPORTED_EVENT_TYPE"
    #: A known event type whose payload cannot be interpreted (for example a
    #: payment ``state`` naming no state in this build's vocabulary).
    REPLAY_MALFORMED_EVENT = "REPLAY_MALFORMED_EVENT"


class ReplayedAuthorization(BaseModel):
    """Authorization lifecycle as the events describe it.

    Every field is ``None`` until an event supplies it. Nothing here is read
    from the ``authorizations`` table — the event log is the only source, which
    is the whole point of replay.

    The ``nonce`` is absent because it was never written to an audit payload in
    the first place (Phase 3 keeps it server-held). Replay cannot surface what
    the ledger does not contain, and that is the correct outcome.
    """

    model_config = ConfigDict(extra="forbid")

    authorization_id: str | None = None
    status: str | None = None
    transaction_digest_prefix: str | None = None
    policy_version: str | None = None
    offer_version: str | None = None
    binding_version: str | None = None
    approval_scheme: ApprovalScheme | None = None
    expires_at: str | None = None
    consumed_at: str | None = None
    bound_merchant_id: str | None = None
    bound_product_id: str | None = None
    bound_quantity: int | None = None
    bound_amount_inr: int | None = None
    bound_currency: str | None = None
    #: A consumed authorization was presented again.
    replay_detected: bool = False
    #: How many times a presented transaction failed to match the bound digest.
    binding_failures: int = 0


class ReplayedPayment(BaseModel):
    """Payment lifecycle as the events describe it.

    ``state`` is taken from the ``state`` field that ``apply_payment_transition``
    stamps into every payment transition payload — never inferred from the event
    type. ``PAYMENT_FAILED`` is emitted for both a retryable and a terminal
    failure, so the event type alone cannot tell them apart; the recorded state
    can.
    """

    model_config = ConfigDict(extra="forbid")

    payment_intent_id: str | None = None
    state: str | None = None
    provider: str | None = None
    provider_payment_id: str | None = None
    idempotency_key: str | None = None
    amount_inr: int | None = None
    currency: str | None = None
    merchant_id: str | None = None
    last_reason_code: str | None = None
    #: Provider call attempts, counted from PAYMENT_ATTEMPTED events.
    attempts: int = 0
    #: A retry presented the same idempotency key and reused the held intent.
    intent_reused: bool = False
    #: Times the payment entered the uncertain state.
    uncertain_episodes: int = 0
    provider_timeouts: int = 0
    retries_scheduled: int = 0
    reconciliations: int = 0
    dead_lettered: bool = False
    webhooks_verified: int = 0
    duplicate_webhooks_ignored: int = 0
    out_of_order_webhooks_ignored: int = 0


class ReplayedSecurityEvent(BaseModel):
    """One security-relevant moment, kept in order.

    Recorded rather than folded into a counter because "what happened" is the
    question a security history has to answer. This is not an analytics
    surface: it is the ordered list of refusals, with the reason code that
    named each one.
    """

    model_config = ConfigDict(extra="forbid")

    sequence: int
    event_type: str
    actor: str
    reason_code: str | None = None
    detail: dict = Field(default_factory=dict)


class ReplayedRiskAssessment(BaseModel):
    """An advisory risk assessment, reconstructed from a RISK_ASSESSED event.

    Present in the projection so a replayed mission shows that the advisory
    layer was consulted and what it concluded. Deliberately INERT: nothing here
    participates in reconstructing mission state, authorization status, or
    payment state, and the reducer's handler for this event type moves none of
    them. A test replays the same mission with and without the event and asserts
    every other field of the projection is identical — so an advisory record
    cannot influence a reconstruction any more than it can influence a decision.

    Carries only what the audit payload carries: the verdict, the factor codes,
    and the versions. No feature values, no weights, no digest.
    """

    model_config = ConfigDict(extra="forbid")

    sequence: int
    assessment_id: str | None = None
    score: float | None = None
    band: str | None = None
    recommendation: str | None = None
    engine_version: str | None = None
    model_version: str | None = None
    factor_codes: list[str] = Field(default_factory=list)


class SkippedTransition(BaseModel):
    """A mission-state move the state machine does not permit, recorded rather
    than forced.

    Production's ``apply_mission_state`` skips an illegal move instead of
    dragging a mission backwards; replay applies the same guard so the
    reconstructed state matches what was persisted. Skips are surfaced because
    a silent one would hide a genuine projection gap.
    """

    model_config = ConfigDict(extra="forbid")

    sequence: int
    event_type: str
    from_state: str
    to_state: str


class MissionProjection(BaseModel):
    """Mission state reconstructed purely from the ordered event history.

    Fields the events do not carry stay ``None``. Nothing here is filled in
    from the live ``missions``, ``offers``, ``authorizations`` or
    ``payment_intents`` rows — a projection that quietly consulted current state
    would verify nothing at all.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: uuid.UUID
    mission_state: str | None = None
    events_replayed: int = 0

    raw_query: str | None = None
    quantity: int | None = None

    policy_decision: str | None = None
    policy_version: str | None = None
    policy_reason_codes: list[str] = Field(default_factory=list)
    requested_amount: int | None = None
    soft_budget: int | None = None
    hard_limit: int | None = None
    selected_offer_id: str | None = None
    approval_required: bool = False
    approval_granted: bool = False

    raw_offer_count: int | None = None
    valid_offer_count: int | None = None
    invalid_offer_count: int | None = None
    tainted_merchant_fields: list[str] = Field(default_factory=list)

    authorization: ReplayedAuthorization = Field(default_factory=ReplayedAuthorization)
    payment: ReplayedPayment = Field(default_factory=ReplayedPayment)
    security_events: list[ReplayedSecurityEvent] = Field(default_factory=list)
    skipped_transitions: list[SkippedTransition] = Field(default_factory=list)
    #: Advisory only. Reconstructed for visibility; contributes to no other
    #: field of this projection and to no state comparison.
    risk_assessments: list[ReplayedRiskAssessment] = Field(default_factory=list)


class StateComparison(BaseModel):
    """Replayed state vs. what the database currently holds.

    DIAGNOSTIC ONLY. A mismatch is reported and nothing is repaired: replay is
    observability here, not recovery. Auto-correcting persisted state from a
    projection would make the projection authoritative over the rows the kernel
    actually enforces against, which inverts the trust relationship.
    """

    model_config = ConfigDict(extra="forbid")

    replay_state: str | None
    persisted_state: str | None
    matches: bool
    replay_authorization_status: str | None = None
    persisted_authorization_status: str | None = None
    authorization_matches: bool | None = None
    replay_payment_state: str | None = None
    persisted_payment_state: str | None = None
    payment_matches: bool | None = None


class MissionReplayResult(BaseModel):
    """What a replay request produced.

    ``trusted`` is separate from ``audit_valid`` on purpose. A chain can verify
    and STILL fail to replay (an unsupported event type), and the caller must be
    able to tell "history is intact but this build cannot interpret it" from
    "history is not intact". Collapsing them would hide one behind the other.
    """

    model_config = ConfigDict(extra="forbid")

    mission_id: uuid.UUID
    audit_valid: bool
    trusted: bool
    reason_code: ReplayReasonCode
    events_replayed: int = Field(ge=0)
    verification: AuditVerificationResult
    state: MissionProjection | None = None
    comparison: StateComparison | None = None
    #: Ordered action/security projection of the same verified audit events.
    #: Always an array; empty when no trusted projection can be produced.
    decision_trace: list[DecisionTraceEntry]
    #: Sequence + type of any event this build could not interpret. Non-empty
    #: only alongside REPLAY_UNSUPPORTED_EVENT_TYPE / REPLAY_MALFORMED_EVENT.
    unsupported_events: list[dict] = Field(default_factory=list)
    detail: str | None = None
