"""Deterministic mission replay (Phase 5).

    EVENT HISTORY  ->  PURE DETERMINISTIC REDUCER  ->  RECONSTRUCTED STATE

REPLAY IS A PROJECTION, NOT A RERUN
-----------------------------------
Nothing here re-executes business operations. It does not call a merchant, a
payment provider, the authorization issuer, the payment executor, or a webhook
handler; it does not create a payment, consume or issue an authorization, append
an audit event, or write any row at all. That is enforced structurally rather
than by discipline: this module imports NOTHING from
``services.payment_executor``, ``services.security_kernel``, or the merchant
adapters, and ``tests/test_replay_isolation.py`` parses this file's imports to
keep it that way. A reducer that could reach an executor would eventually be
asked to.

The only imports from ``services`` are the two mission state-machine predicates,
which are pure functions over an enum.

DETERMINISM
-----------
``reduce_events`` reads no clock, generates no UUID, consults no environment,
and performs no I/O. The same ordered event list produces a byte-identical
result every time and in any process. Timestamps that appear in the projection
are copied verbatim out of event payloads as strings; they are never parsed and
re-formatted, because a parse/format round trip is where a locale or a
precision choice would sneak in.

THE INTEGRITY GATE
------------------
``replay_mission`` verifies the chain FIRST and refuses to produce a trusted
projection from a chain that does not verify. Reducing tampered history would
yield a confident-looking state derived from evidence already known to be
false — worse than no answer, because it looks like one.
``reduce_events`` remains callable on its own for tests and diagnostics, but it
is not reachable through the API without passing the gate.

UNKNOWN EVENTS: FAIL CLOSED
---------------------------
Audit events carry no schema or version field, and Phase 5 does not add one — a
migration whose only purpose is to look forward-compatible is decoration. The
honest smallest strategy is a policy about the thing that actually varies: an
``event_type`` string this build does not recognize.

That policy is REFUSAL. An unrecognized event may be a security event — an
escalation, a spoof, a replay — and a projection that silently drops it does not
merely omit information, it MISREPRESENTS what happened, while still presenting
itself as a faithful reconstruction. So replay stops and reports
``REPLAY_UNSUPPORTED_EVENT_TYPE`` with the offending sequence. Every event type
this build declares has a handler, which ``tests/test_replay_engine.py`` asserts
exhaustively against ``EventType``, so a new event type added without a reducer
rule fails a test rather than silently distorting a projection.

The same refusal covers a known type whose payload cannot be interpreted
(``REPLAY_MALFORMED_EVENT``) — for instance a payment ``state`` naming no state
in this build's vocabulary.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from apps.api.db.models import AuditEventRow, AuthorizationRow, Mission, PaymentIntentRow
from packages.schemas.approval import ApprovalScheme
from packages.schemas.audit import (
    DecisionStage,
    DecisionTraceEntry,
    DecisionTraceEvidenceRef,
    DecisionTraceNextAction,
    DecisionTraceVerdict,
    MissionProjection,
    MissionReplayResult,
    ReplayedAuthorization,
    ReplayedPayment,
    ReplayedRiskAssessment,
    ReplayedSecurityEvent,
    ReplayReasonCode,
    SkippedTransition,
    StateComparison,
)
from packages.schemas.authorization import AuthorizationStatus
from packages.schemas.domain import EventType, MissionState, PolicyOutcome, as_utc
from packages.schemas.payment import PaymentIntentState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_orchestrator.state_machine import can_transition
from services.audit_ledger.ledger import list_events
from services.audit_ledger.verify import verify_mission_chain

#: Identifies the reducer, not the events. Audit events carry no version of
#: their own, and inventing one for them retroactively would be a claim the
#: data cannot support. This stamps which set of reduction RULES ran.
REPLAY_ENGINE_VERSION = "pactra-replay-v1"

#: Event types whose presence is itself the security history worth preserving.
#: Recorded in order, with their reason code, rather than counted.
SECURITY_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.SECURITY_VIOLATION,
        EventType.AUTHORIZATION_REPLAY_DETECTED,
        EventType.TRANSACTION_BINDING_FAILURE,
        EventType.IDEMPOTENCY_CONFLICT,
        EventType.WEBHOOK_REJECTED,
        EventType.DUPLICATE_WEBHOOK_IGNORED,
        EventType.WEBHOOK_OUT_OF_ORDER_IGNORED,
        EventType.MISSION_DENIED,
    }
)

#: Payload keys that are safe and useful to carry into a security record. An
#: allow-list rather than "everything except": a payload gains fields over time,
#: and a deny-list silently starts leaking whatever is added next.
_SECURITY_DETAIL_KEYS = (
    "field",
    "attempted_value",
    "source_authority",
    "target_authority",
    "merchant_id",
    "claimed_merchant_id",
    "authenticated_merchant_id",
    "offer_id",
    "rejected",
    "status",
    "current_state",
    "requested_state",
    "provider_event_id",
    "idempotency_key",
    "bound_digest_prefix",
    "presented_digest_prefix",
    "reason_codes",
    "terminal",
    "invariant_id",
    "bind_refused",
)

# Exhaustive stage classification. A bind-time SECURITY_VIOLATION is promoted
# from ADMIT to BIND by ``_trace_stage`` based on its allow-listed marker.
TRACE_STAGE_BY_EVENT: dict[EventType, DecisionStage] = {
    EventType.MISSION_CREATED: DecisionStage.ADMIT,
    EventType.INTENT_PARSED: DecisionStage.ADMIT,
    EventType.DISCOVERY_STARTED: DecisionStage.ADMIT,
    EventType.OFFERS_RECEIVED: DecisionStage.ADMIT,
    EventType.OFFERS_NORMALIZED: DecisionStage.ADMIT,
    EventType.OFFERS_RANKED: DecisionStage.ADMIT,
    EventType.POLICY_DECISION: DecisionStage.ADMIT,
    EventType.APPROVAL_REQUESTED: DecisionStage.BIND,
    EventType.MISSION_DENIED: DecisionStage.ADMIT,
    EventType.SECURITY_VIOLATION: DecisionStage.ADMIT,
    EventType.AUTHORIZATION_CREATED: DecisionStage.BIND,
    EventType.AUTHORIZATION_ACTIVATED: DecisionStage.BIND,
    EventType.AUTHORIZATION_CONSUMED: DecisionStage.BIND,
    EventType.AUTHORIZATION_EXPIRED: DecisionStage.BIND,
    EventType.AUTHORIZATION_REVOKED: DecisionStage.BIND,
    EventType.AUTHORIZATION_REPLAY_DETECTED: DecisionStage.BIND,
    EventType.TRANSACTION_BINDING_FAILURE: DecisionStage.BIND,
    EventType.PAYMENT_INTENT_CREATED: DecisionStage.EXECUTE,
    EventType.PAYMENT_QUEUED: DecisionStage.EXECUTE,
    EventType.PAYMENT_ATTEMPTED: DecisionStage.EXECUTE,
    EventType.PAYMENT_PROVIDER_TIMEOUT: DecisionStage.EXECUTE,
    EventType.PAYMENT_PROVIDER_UNCERTAIN: DecisionStage.EXECUTE,
    EventType.PAYMENT_RETRY_SCHEDULED: DecisionStage.EXECUTE,
    EventType.PAYMENT_RECONCILED: DecisionStage.EXECUTE,
    EventType.PAYMENT_SUCCEEDED: DecisionStage.EXECUTE,
    EventType.PAYMENT_FAILED: DecisionStage.EXECUTE,
    EventType.PAYMENT_INTENT_REUSED: DecisionStage.EXECUTE,
    EventType.IDEMPOTENCY_CONFLICT: DecisionStage.EXECUTE,
    EventType.OUTBOX_EVENT_DEAD_LETTERED: DecisionStage.EXECUTE,
    EventType.WEBHOOK_VERIFIED: DecisionStage.EXECUTE,
    EventType.WEBHOOK_REJECTED: DecisionStage.EXECUTE,
    EventType.DUPLICATE_WEBHOOK_IGNORED: DecisionStage.EXECUTE,
    EventType.WEBHOOK_OUT_OF_ORDER_IGNORED: DecisionStage.EXECUTE,
    # Risk is advisory evidence about admission inputs. It is never a fourth
    # authority stage and never moves the mission or payment state.
    EventType.RISK_ASSESSED: DecisionStage.ADMIT,
}


class ReplayRefused(Exception):
    """The reducer cannot honestly interpret this history.

    Carries the position so the caller can point at the event rather than at
    the mission.
    """

    def __init__(
        self, reason_code: ReplayReasonCode, *, sequence: int, event_type: str, detail: str
    ) -> None:
        super().__init__(f"{reason_code.value}: {detail}")
        self.reason_code = reason_code
        self.sequence = sequence
        self.event_type = event_type
        self.detail = detail


@dataclass
class _ReplayState:
    """Mutable accumulator for the fold.

    A dataclass rather than a Pydantic model so the fold is cheap; it is
    converted to the immutable ``MissionProjection`` exactly once at the end.
    """

    mission_id: uuid.UUID
    mission_state: MissionState | None = None
    events_replayed: int = 0
    raw_query: str | None = None
    quantity: int | None = None
    policy_decision: str | None = None
    policy_version: str | None = None
    policy_reason_codes: list[str] = field(default_factory=list)
    requested_amount: int | None = None
    soft_budget: int | None = None
    hard_limit: int | None = None
    selected_offer_id: str | None = None
    approval_required: bool = False
    approval_granted: bool = False
    raw_offer_count: int | None = None
    valid_offer_count: int | None = None
    invalid_offer_count: int | None = None
    tainted_merchant_fields: list[str] = field(default_factory=list)
    authorization: ReplayedAuthorization = field(default_factory=ReplayedAuthorization)
    payment: ReplayedPayment = field(default_factory=ReplayedPayment)
    security_events: list[ReplayedSecurityEvent] = field(default_factory=list)
    skipped_transitions: list[SkippedTransition] = field(default_factory=list)
    risk_assessments: list[ReplayedRiskAssessment] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Payload readers — every one of them refuses rather than guesses
# --------------------------------------------------------------------------- #
def _refuse(event: AuditEventRow, detail: str) -> ReplayRefused:
    return ReplayRefused(
        ReplayReasonCode.REPLAY_MALFORMED_EVENT,
        sequence=event.sequence,
        event_type=str(event.event_type),
        detail=detail,
    )


def _opt_str(event: AuditEventRow, key: str) -> str | None:
    value = event.payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _refuse(event, f"payload field '{key}' is not a string")
    return value


def _opt_int(event: AuditEventRow, key: str) -> int | None:
    value = event.payload.get(key)
    if value is None:
        return None
    # bool is an int subclass in Python; a boolean where a count belongs is a
    # malformed payload, not a zero or a one.
    if not isinstance(value, int) or isinstance(value, bool):
        raise _refuse(event, f"payload field '{key}' is not an integer")
    return value


def _opt_str_list(event: AuditEventRow, key: str) -> list[str] | None:
    value = event.payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _refuse(event, f"payload field '{key}' is not a list of strings")
    return value


def _opt_approval_scheme(event: AuditEventRow) -> ApprovalScheme | None:
    value = _opt_str(event, "approval_scheme")
    if value is None:
        return None
    try:
        return ApprovalScheme(value)
    except ValueError as unknown:
        raise _refuse(event, f"approval scheme {value!r} is not known to this build") from unknown


def _security_detail(event: AuditEventRow) -> dict:
    return {key: event.payload[key] for key in _SECURITY_DETAIL_KEYS if key in event.payload}


# --------------------------------------------------------------------------- #
# Mission-state advance
# --------------------------------------------------------------------------- #
def _advance(state: _ReplayState, event: AuditEventRow, target: MissionState) -> None:
    """Move the mission if the state machine permits, and record it if not.

    This mirrors production exactly. ``Orchestrator._transition`` asserts the
    move is legal (and it always is, on the path that wrote the event), while
    ``apply_mission_state`` SKIPS an illegal move rather than dragging a mission
    backwards. Applying the same guard here is what makes the replayed state
    equal the persisted state instead of merely resembling it.
    """
    current = state.mission_state
    if current is None:
        # No prior state: the first event establishes one. Only MISSION_CREATED
        # legitimately reaches here on a complete chain; a partial chain handed
        # to the reducer directly (a diagnostic, not an API path) also starts
        # wherever it starts, which is the honest reading of the events given.
        state.mission_state = target
        return
    if current == target:
        return
    if can_transition(current, target):
        state.mission_state = target
        return
    state.skipped_transitions.append(
        SkippedTransition(
            sequence=event.sequence,
            event_type=str(event.event_type),
            from_state=current.value,
            to_state=target.value,
        )
    )


def _payment_state_from_payload(state: _ReplayState, event: AuditEventRow) -> None:
    """Adopt the payment state a transition payload recorded.

    ``apply_payment_transition`` stamps ``state`` into every payment transition
    payload, so this is the authoritative value — not an inference from the
    event type. ``PAYMENT_FAILED`` in particular is emitted for BOTH a retryable
    and a terminal failure, and only the recorded state distinguishes them.
    """
    raw = event.payload.get("state")
    if raw is None:
        return
    if not isinstance(raw, str):
        raise _refuse(event, "payload field 'state' is not a string")
    try:
        payment_state = PaymentIntentState(raw)
    except ValueError as unknown:
        raise ReplayRefused(
            ReplayReasonCode.REPLAY_MALFORMED_EVENT,
            sequence=event.sequence,
            event_type=str(event.event_type),
            detail=f"payment state {raw!r} is not a state this build knows",
        ) from unknown
    state.payment.state = payment_state.value


def _common_payment_fields(state: _ReplayState, event: AuditEventRow) -> None:
    """Fold in whichever payment identifiers this payload happens to carry.

    Written as "adopt what is present" rather than "expect this shape" because
    the payment events genuinely carry different subsets — an attempt names the
    provider, a settlement names the provider payment id, a reuse names neither.
    """
    payment = state.payment
    payment.payment_intent_id = _opt_str(event, "payment_intent_id") or payment.payment_intent_id
    payment.provider = _opt_str(event, "provider") or payment.provider
    payment.provider_payment_id = (
        _opt_str(event, "provider_payment_id") or payment.provider_payment_id
    )
    payment.idempotency_key = _opt_str(event, "idempotency_key") or payment.idempotency_key
    payment.amount_inr = _opt_int(event, "amount_inr") or payment.amount_inr
    payment.currency = _opt_str(event, "currency") or payment.currency
    payment.merchant_id = _opt_str(event, "merchant_id") or payment.merchant_id
    # PRESENCE, not truthiness, decides here. An event that carries the key —
    # even as an explicit null — is stating the reason as of that transition, so
    # a success that cleared a prior retryable failure clears it in the
    # projection too. An event that omits the key entirely is saying nothing
    # about the reason, so the previous value stands; pre-C1 payloads omitted
    # the key instead of recording a clear, and must keep replaying that way.
    if "reason_code" in event.payload:
        payment.last_reason_code = _opt_str(event, "reason_code")


def _record_security(state: _ReplayState, event: AuditEventRow) -> None:
    state.security_events.append(
        ReplayedSecurityEvent(
            sequence=event.sequence,
            event_type=str(event.event_type),
            actor=event.actor,
            reason_code=_opt_str(event, "reason_code"),
            detail=_security_detail(event),
        )
    )


# --------------------------------------------------------------------------- #
# Handlers — one per EventType, exhaustively
# --------------------------------------------------------------------------- #
def _on_mission_created(state: _ReplayState, event: AuditEventRow) -> None:
    state.raw_query = _opt_str(event, "raw_query")
    state.quantity = _opt_int(event, "quantity")
    _advance(state, event, MissionState.CREATED)


def _on_intent_parsed(state: _ReplayState, event: AuditEventRow) -> None:
    constraints = event.payload.get("constraints")
    if constraints is not None:
        if not isinstance(constraints, dict):
            raise _refuse(event, "payload field 'constraints' is not an object")
        soft = constraints.get("soft_budget_inr")
        hard = constraints.get("hard_limit_inr")
        if isinstance(soft, int) and not isinstance(soft, bool):
            state.soft_budget = soft
        if isinstance(hard, int) and not isinstance(hard, bool):
            state.hard_limit = hard
    _advance(state, event, MissionState.INTENT_PARSED)


def _on_discovery_started(state: _ReplayState, event: AuditEventRow) -> None:
    _advance(state, event, MissionState.DISCOVERING)


def _on_offers_received(state: _ReplayState, event: AuditEventRow) -> None:
    state.raw_offer_count = _opt_int(event, "raw_offer_count")
    _advance(state, event, MissionState.OFFERS_RECEIVED)


def _on_offers_normalized(state: _ReplayState, event: AuditEventRow) -> None:
    state.valid_offer_count = _opt_int(event, "valid")
    state.invalid_offer_count = _opt_int(event, "invalid")
    state.tainted_merchant_fields = _opt_str_list(event, "tainted_merchant_fields") or []
    _advance(state, event, MissionState.OFFERS_NORMALIZED)


def _on_offers_ranked(state: _ReplayState, event: AuditEventRow) -> None:
    _advance(state, event, MissionState.RANKED)


def _on_policy_decision(state: _ReplayState, event: AuditEventRow) -> None:
    decision = _opt_str(event, "decision")
    if decision is not None:
        try:
            state.policy_decision = PolicyOutcome(decision).value
        except ValueError as unknown:
            raise ReplayRefused(
                ReplayReasonCode.REPLAY_MALFORMED_EVENT,
                sequence=event.sequence,
                event_type=str(event.event_type),
                detail=f"policy decision {decision!r} is not an outcome this build knows",
            ) from unknown
    state.policy_version = _opt_str(event, "policy_version")
    state.policy_reason_codes = _opt_str_list(event, "reason_codes") or []
    state.requested_amount = _opt_int(event, "requested_amount")
    state.soft_budget = _opt_int(event, "soft_budget") or state.soft_budget
    state.hard_limit = _opt_int(event, "hard_limit") or state.hard_limit
    state.selected_offer_id = _opt_str(event, "selected_offer_id")
    _advance(state, event, MissionState.POLICY_CHECKED)


def _on_approval_requested(state: _ReplayState, event: AuditEventRow) -> None:
    state.approval_required = True
    state.requested_amount = _opt_int(event, "requested_amount") or state.requested_amount
    state.authorization.authorization_id = (
        _opt_str(event, "authorization_id") or state.authorization.authorization_id
    )
    _advance(state, event, MissionState.AWAITING_APPROVAL)


def _on_mission_denied(state: _ReplayState, event: AuditEventRow) -> None:
    state.policy_reason_codes = _opt_str_list(event, "reason_codes") or state.policy_reason_codes
    _record_security(state, event)
    _advance(state, event, MissionState.CANCELLED)


def _on_security_violation(state: _ReplayState, event: AuditEventRow) -> None:
    # Deliberately does NOT move the mission. A violation is a refusal that
    # left authoritative state untouched — that is the Phase 2 guarantee, and
    # inventing a state change here would misreport it.
    _record_security(state, event)


def _on_authorization_created(state: _ReplayState, event: AuditEventRow) -> None:
    auth = state.authorization
    auth.authorization_id = _opt_str(event, "authorization_id") or auth.authorization_id
    auth.status = _opt_str(event, "status") or AuthorizationStatus.PENDING.value
    auth.transaction_digest_prefix = _opt_str(event, "transaction_digest_prefix")
    auth.policy_version = _opt_str(event, "policy_version")
    auth.offer_version = _opt_str(event, "offer_version")
    auth.binding_version = _opt_str(event, "binding_version")
    auth.approval_scheme = _opt_approval_scheme(event)
    auth.expires_at = _opt_str(event, "expires_at")
    auth.bound_merchant_id = _opt_str(event, "bound_merchant_id")
    auth.bound_product_id = _opt_str(event, "bound_product_id")
    auth.bound_quantity = _opt_int(event, "bound_quantity")
    auth.bound_amount_inr = _opt_int(event, "bound_amount_inr")
    auth.bound_currency = _opt_str(event, "bound_currency")


def _on_authorization_activated(state: _ReplayState, event: AuditEventRow) -> None:
    auth = state.authorization
    auth.authorization_id = _opt_str(event, "authorization_id") or auth.authorization_id
    auth.status = _opt_str(event, "status") or AuthorizationStatus.ACTIVE.value
    auth.transaction_digest_prefix = (
        _opt_str(event, "transaction_digest_prefix") or auth.transaction_digest_prefix
    )
    scheme = _opt_approval_scheme(event)
    if scheme is not None:
        auth.approval_scheme = scheme
    if state.approval_required:
        # A valid USER_ED25519 proof activated it. On the ALLOW path the kernel
        # uses POLICY_AUTO without a user approval step.
        state.approval_granted = True
    _advance(state, event, MissionState.AUTHORIZED)


def _on_authorization_consumed(state: _ReplayState, event: AuditEventRow) -> None:
    auth = state.authorization
    auth.status = _opt_str(event, "status") or AuthorizationStatus.CONSUMED.value
    auth.consumed_at = _opt_str(event, "consumed_at")


def _on_authorization_expired(state: _ReplayState, event: AuditEventRow) -> None:
    auth = state.authorization
    auth.status = _opt_str(event, "status") or AuthorizationStatus.EXPIRED.value
    auth.expires_at = _opt_str(event, "expires_at") or auth.expires_at


def _on_authorization_revoked(state: _ReplayState, event: AuditEventRow) -> None:
    state.authorization.status = _opt_str(event, "status") or AuthorizationStatus.REVOKED.value


def _on_authorization_replay_detected(state: _ReplayState, event: AuditEventRow) -> None:
    auth = state.authorization
    auth.replay_detected = True
    # The status recorded here describes the row the replay attempt hit — still
    # CONSUMED. The refusal changed nothing, and the projection says so.
    auth.status = _opt_str(event, "status") or auth.status
    auth.consumed_at = _opt_str(event, "consumed_at") or auth.consumed_at
    _record_security(state, event)


def _on_transaction_binding_failure(state: _ReplayState, event: AuditEventRow) -> None:
    state.authorization.binding_failures += 1
    _record_security(state, event)


def _on_payment_intent_created(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    state.authorization.authorization_id = (
        _opt_str(event, "authorization_id") or state.authorization.authorization_id
    )


def _on_payment_queued(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    _advance(state, event, MissionState.PAYMENT_PENDING)


def _on_payment_attempted(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    state.payment.attempts += 1


def _on_payment_provider_timeout(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    state.payment.provider_timeouts += 1


def _on_payment_provider_uncertain(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    state.payment.uncertain_episodes += 1


def _on_payment_retry_scheduled(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    state.payment.retries_scheduled += 1


def _on_payment_reconciled(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    # PAYMENT_RECONCILED is a narration event, not a transition: the transition
    # it describes was already applied through apply_provider_payment and
    # recorded by its own event. Its `state` is therefore informational and is
    # NOT adopted here, so a reconciliation cannot silently move the projection
    # somewhere the payment state machine never went.
    state.payment.reconciliations += 1


def _on_payment_succeeded(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    _advance(state, event, MissionState.PAYMENT_SUCCEEDED)


def _on_payment_failed(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    # ONLY a terminal failure moves the mission. A retryable one leaves the
    # payment in flight, and production does not move the mission either.
    if state.payment.state == PaymentIntentState.FAILED_TERMINAL.value:
        _advance(state, event, MissionState.PAYMENT_FAILED)


def _on_payment_intent_reused(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    _payment_state_from_payload(state, event)
    state.payment.intent_reused = True


def _on_idempotency_conflict(state: _ReplayState, event: AuditEventRow) -> None:
    # No payment field is adopted: the payload deliberately carries fingerprint
    # PREFIXES of two different requests, not the values of either.
    _record_security(state, event)


def _on_outbox_dead_lettered(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    state.payment.dead_lettered = True


def _on_webhook_verified(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    state.payment.webhooks_verified += 1


def _on_webhook_rejected(state: _ReplayState, event: AuditEventRow) -> None:
    # Phase 4 deliberately emits no such event: a rejected signature cannot name
    # a mission chain. The handler exists so the type is HANDLED rather than
    # unknown — if a future transport-scoped path ever writes one, replay
    # records it as security history instead of refusing the whole mission.
    _record_security(state, event)


def _on_duplicate_webhook_ignored(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    state.payment.duplicate_webhooks_ignored += 1
    _record_security(state, event)


def _on_webhook_out_of_order_ignored(state: _ReplayState, event: AuditEventRow) -> None:
    _common_payment_fields(state, event)
    state.payment.out_of_order_webhooks_ignored += 1
    _record_security(state, event)


def _on_risk_assessed(state: _ReplayState, event: AuditEventRow) -> None:
    """Fold an advisory risk assessment. DELIBERATELY INERT (Phase 7).

    This handler touches nothing else on the accumulator: not
    ``mission_state``, not ``authorization``, not ``payment``, not
    ``security_events``. It appends one record to a list that no other rule
    reads and that no state comparison consults.

    That inertness is the reducer's half of the Phase 7 invariant that risk is
    never authority. An advisory event exists in the ledger, so replay must
    account for it — the exhaustive handler table means it cannot be silently
    dropped — but accounting for it must not let it move a reconstructed state.
    A test replays the same mission with and without the event and asserts every
    other field of the projection is byte-identical.

    It is NOT added to ``SECURITY_EVENT_TYPES``: a risk assessment is an opinion,
    and listing it beside AUTHORIZATION_REPLAY_DETECTED would put an opinion in
    the ordered history of refusals.

    Payload reads are lenient rather than refusing, unlike every other reducer
    here. The difference is deliberate: a malformed SECURITY_VIOLATION means the
    security history cannot be reconstructed and refusing is the only honest
    answer, whereas a malformed advisory payload costs the projection nothing it
    was relying on. Refusing the whole replay because an advisory note was
    unreadable would let the advisory layer break a reconstruction — precisely
    the authority it must not have.
    """
    payload = event.payload if isinstance(event.payload, dict) else {}
    score = payload.get("score")
    codes = payload.get("factor_codes")
    state.risk_assessments.append(
        ReplayedRiskAssessment(
            sequence=event.sequence,
            assessment_id=_advisory_str(payload.get("assessment_id")),
            score=float(score) if isinstance(score, (int, float)) else None,
            band=_advisory_str(payload.get("band")),
            recommendation=_advisory_str(payload.get("recommendation")),
            engine_version=_advisory_str(payload.get("engine_version")),
            model_version=_advisory_str(payload.get("model_version")),
            factor_codes=[str(code) for code in codes] if isinstance(codes, list) else [],
        )
    )


def _advisory_str(value: object) -> str | None:
    """Lenient string read for an advisory payload only.

    Distinct from the strict ``_opt_str(event, key)`` readers above, which refuse
    a malformed payload. See ``_on_risk_assessed`` for why the advisory path is
    lenient where every enforcement path is not.
    """
    return value if isinstance(value, str) else None


# --------------------------------------------------------------------------- #
# C1 Decision Trace — allow-listed projection, never raw event payloads
# --------------------------------------------------------------------------- #
_TRACE_REFUSALS = frozenset(
    {
        EventType.MISSION_DENIED,
        EventType.SECURITY_VIOLATION,
        EventType.AUTHORIZATION_EXPIRED,
        EventType.AUTHORIZATION_REVOKED,
        EventType.AUTHORIZATION_REPLAY_DETECTED,
        EventType.TRANSACTION_BINDING_FAILURE,
        EventType.IDEMPOTENCY_CONFLICT,
        EventType.WEBHOOK_REJECTED,
    }
)
_TRACE_PENDING = frozenset(
    {
        EventType.APPROVAL_REQUESTED,
        EventType.AUTHORIZATION_CREATED,
        EventType.PAYMENT_QUEUED,
        EventType.PAYMENT_ATTEMPTED,
        EventType.PAYMENT_PROVIDER_TIMEOUT,
        EventType.PAYMENT_PROVIDER_UNCERTAIN,
        EventType.PAYMENT_RETRY_SCHEDULED,
        EventType.PAYMENT_RECONCILED,
    }
)
_TRACE_IGNORED = frozenset(
    {
        EventType.DUPLICATE_WEBHOOK_IGNORED,
        EventType.WEBHOOK_OUT_OF_ORDER_IGNORED,
    }
)


def _trace_reason_codes(event: AuditEventRow) -> list[str]:
    """Copy only stable machine reason codes, preserving source order."""
    codes: list[str] = []
    single = event.payload.get("reason_code")
    if isinstance(single, str):
        codes.append(single)
    multiple = event.payload.get("reason_codes")
    if isinstance(multiple, list):
        codes.extend(code for code in multiple if isinstance(code, str))
    # A payload should not repeat itself, but deterministic de-duplication keeps
    # the public contract stable if it does.
    return list(dict.fromkeys(codes))


def _trace_approval_scheme(event: AuditEventRow) -> ApprovalScheme | None:
    raw = event.payload.get("approval_scheme")
    if not isinstance(raw, str):
        return None
    try:
        return ApprovalScheme(raw)
    except ValueError:
        return None


def _trace_policy_outcome(event: AuditEventRow) -> PolicyOutcome | None:
    if event.event_type != EventType.POLICY_DECISION.value:
        return None
    raw = event.payload.get("decision")
    if not isinstance(raw, str):
        return None
    try:
        return PolicyOutcome(raw)
    except ValueError:  # replay already refuses this malformed source event
        return None


def _trace_payment_state(event: AuditEventRow) -> PaymentIntentState | None:
    raw = event.payload.get("state")
    if not isinstance(raw, str):
        return None
    try:
        return PaymentIntentState(raw)
    except ValueError:
        return None


def _trace_stage(event_type: EventType, event: AuditEventRow) -> DecisionStage:
    if event_type is EventType.SECURITY_VIOLATION and event.payload.get("bind_refused") is True:
        return DecisionStage.BIND
    return TRACE_STAGE_BY_EVENT[event_type]


def _trace_verdict(event_type: EventType, event: AuditEventRow) -> DecisionTraceVerdict:
    if event_type is EventType.RISK_ASSESSED:
        return DecisionTraceVerdict.ADVISORY
    if event_type is EventType.POLICY_DECISION:
        outcome = _trace_policy_outcome(event)
        if outcome is PolicyOutcome.DENY:
            return DecisionTraceVerdict.REFUSED
        if outcome is PolicyOutcome.REQUIRE_APPROVAL:
            return DecisionTraceVerdict.PENDING
    if event_type in _TRACE_REFUSALS:
        return DecisionTraceVerdict.REFUSED
    if event_type in _TRACE_IGNORED:
        return DecisionTraceVerdict.IGNORED
    if event_type is EventType.PAYMENT_SUCCEEDED:
        return DecisionTraceVerdict.SUCCEEDED
    if event_type in {EventType.PAYMENT_FAILED, EventType.OUTBOX_EVENT_DEAD_LETTERED}:
        return DecisionTraceVerdict.FAILED
    if event_type in _TRACE_PENDING:
        return DecisionTraceVerdict.PENDING
    return DecisionTraceVerdict.ACCEPTED


def _trace_next_action(
    event_type: EventType,
    event: AuditEventRow,
    *,
    stage: DecisionStage,
) -> DecisionTraceNextAction:
    if event_type is EventType.RISK_ASSESSED:
        # Advice never grants, blocks, or selects the workflow's next action.
        return DecisionTraceNextAction.NONE
    if event_type is EventType.SECURITY_VIOLATION:
        return (
            DecisionTraceNextAction.NONE
            if stage is DecisionStage.BIND
            else DecisionTraceNextAction.CONTINUE_ADMIT
        )
    if event_type is EventType.POLICY_DECISION:
        return (
            DecisionTraceNextAction.NONE
            if _trace_policy_outcome(event) is PolicyOutcome.DENY
            else DecisionTraceNextAction.CONTINUE_BIND
        )
    if event_type in {
        EventType.MISSION_DENIED,
        EventType.AUTHORIZATION_EXPIRED,
        EventType.AUTHORIZATION_REVOKED,
        EventType.AUTHORIZATION_REPLAY_DETECTED,
        EventType.TRANSACTION_BINDING_FAILURE,
        EventType.IDEMPOTENCY_CONFLICT,
        EventType.WEBHOOK_REJECTED,
        EventType.PAYMENT_SUCCEEDED,
        EventType.OUTBOX_EVENT_DEAD_LETTERED,
    }:
        return DecisionTraceNextAction.NONE
    if event_type is EventType.APPROVAL_REQUESTED:
        return DecisionTraceNextAction.AWAIT_USER_SIGNATURE
    if event_type is EventType.AUTHORIZATION_CREATED:
        return (
            DecisionTraceNextAction.AWAIT_USER_SIGNATURE
            if _trace_approval_scheme(event) is ApprovalScheme.USER_ED25519
            else DecisionTraceNextAction.CONTINUE_BIND
        )
    if event_type is EventType.AUTHORIZATION_ACTIVATED:
        return DecisionTraceNextAction.CREATE_PAYMENT_INTENT
    if event_type is EventType.AUTHORIZATION_CONSUMED:
        return DecisionTraceNextAction.DISPATCH_PAYMENT
    if event_type in {EventType.PAYMENT_INTENT_CREATED, EventType.PAYMENT_QUEUED}:
        return DecisionTraceNextAction.DISPATCH_PAYMENT
    if event_type in {
        EventType.PAYMENT_PROVIDER_TIMEOUT,
        EventType.PAYMENT_PROVIDER_UNCERTAIN,
    }:
        return DecisionTraceNextAction.RECONCILE_PAYMENT
    if event_type is EventType.PAYMENT_RETRY_SCHEDULED:
        return DecisionTraceNextAction.RETRY_PAYMENT
    if event_type is EventType.PAYMENT_FAILED:
        return (
            DecisionTraceNextAction.RETRY_PAYMENT
            if _trace_payment_state(event) is PaymentIntentState.FAILED_RETRYABLE
            else DecisionTraceNextAction.NONE
        )
    if event_type is EventType.PAYMENT_INTENT_REUSED:
        state = _trace_payment_state(event)
        if state is PaymentIntentState.QUEUED:
            return DecisionTraceNextAction.DISPATCH_PAYMENT
        if state in {
            PaymentIntentState.PROCESSING,
            PaymentIntentState.PROVIDER_PENDING,
        }:
            return DecisionTraceNextAction.AWAIT_PROVIDER
        return DecisionTraceNextAction.NONE
    if stage is DecisionStage.ADMIT:
        return DecisionTraceNextAction.CONTINUE_ADMIT
    if stage is DecisionStage.BIND:
        return DecisionTraceNextAction.CONTINUE_BIND
    return DecisionTraceNextAction.AWAIT_PROVIDER


def decision_trace_from_events(events: Sequence[AuditEventRow]) -> list[DecisionTraceEntry]:
    """Project verified audit events into a deterministic, secret-free trace.

    ``replay_mission`` invokes this only after chain verification and successful
    replay. The function performs no I/O and sorts by the same total order as
    ``reduce_events``.
    """
    trace: list[DecisionTraceEntry] = []
    for event in sorted(events, key=lambda row: (row.sequence, str(row.event_id))):
        event_type = EventType(event.event_type)
        stage = _trace_stage(event_type, event)
        invariant = event.payload.get("invariant_id")
        trace.append(
            DecisionTraceEntry(
                stage=stage,
                event_type=event_type,
                verdict=_trace_verdict(event_type, event),
                reason_codes=_trace_reason_codes(event),
                invariant_id=invariant if isinstance(invariant, str) else None,
                approval_scheme=_trace_approval_scheme(event),
                policy_outcome=_trace_policy_outcome(event),
                payment_state=_trace_payment_state(event),
                advisory=event_type is EventType.RISK_ASSESSED,
                next_action=_trace_next_action(event_type, event, stage=stage),
                evidence=DecisionTraceEvidenceRef(
                    event_id=event.event_id,
                    sequence=event.sequence,
                    actor=event.actor,
                ),
                recorded_at=as_utc(event.created_at),
            )
        )
    return trace


#: Exhaustive by contract. `test_every_event_type_has_a_reducer` asserts this
#: table's keys equal the full EventType enum, so adding an event type without
#: teaching replay what it means fails a test instead of quietly distorting a
#: reconstructed mission.
HANDLERS: dict[EventType, Callable[[_ReplayState, AuditEventRow], None]] = {
    EventType.MISSION_CREATED: _on_mission_created,
    EventType.INTENT_PARSED: _on_intent_parsed,
    EventType.DISCOVERY_STARTED: _on_discovery_started,
    EventType.OFFERS_RECEIVED: _on_offers_received,
    EventType.OFFERS_NORMALIZED: _on_offers_normalized,
    EventType.OFFERS_RANKED: _on_offers_ranked,
    EventType.POLICY_DECISION: _on_policy_decision,
    EventType.APPROVAL_REQUESTED: _on_approval_requested,
    EventType.MISSION_DENIED: _on_mission_denied,
    EventType.SECURITY_VIOLATION: _on_security_violation,
    EventType.AUTHORIZATION_CREATED: _on_authorization_created,
    EventType.AUTHORIZATION_ACTIVATED: _on_authorization_activated,
    EventType.AUTHORIZATION_CONSUMED: _on_authorization_consumed,
    EventType.AUTHORIZATION_EXPIRED: _on_authorization_expired,
    EventType.AUTHORIZATION_REVOKED: _on_authorization_revoked,
    EventType.AUTHORIZATION_REPLAY_DETECTED: _on_authorization_replay_detected,
    EventType.TRANSACTION_BINDING_FAILURE: _on_transaction_binding_failure,
    EventType.PAYMENT_INTENT_CREATED: _on_payment_intent_created,
    EventType.PAYMENT_QUEUED: _on_payment_queued,
    EventType.PAYMENT_ATTEMPTED: _on_payment_attempted,
    EventType.PAYMENT_PROVIDER_TIMEOUT: _on_payment_provider_timeout,
    EventType.PAYMENT_PROVIDER_UNCERTAIN: _on_payment_provider_uncertain,
    EventType.PAYMENT_RETRY_SCHEDULED: _on_payment_retry_scheduled,
    EventType.PAYMENT_RECONCILED: _on_payment_reconciled,
    EventType.PAYMENT_SUCCEEDED: _on_payment_succeeded,
    EventType.PAYMENT_FAILED: _on_payment_failed,
    EventType.PAYMENT_INTENT_REUSED: _on_payment_intent_reused,
    EventType.IDEMPOTENCY_CONFLICT: _on_idempotency_conflict,
    EventType.OUTBOX_EVENT_DEAD_LETTERED: _on_outbox_dead_lettered,
    EventType.WEBHOOK_VERIFIED: _on_webhook_verified,
    EventType.WEBHOOK_REJECTED: _on_webhook_rejected,
    EventType.DUPLICATE_WEBHOOK_IGNORED: _on_duplicate_webhook_ignored,
    EventType.WEBHOOK_OUT_OF_ORDER_IGNORED: _on_webhook_out_of_order_ignored,
    EventType.RISK_ASSESSED: _on_risk_assessed,
}


# --------------------------------------------------------------------------- #
# The reducer
# --------------------------------------------------------------------------- #
def apply_event(state: _ReplayState, event: AuditEventRow) -> _ReplayState:
    """Fold ONE event into the accumulator. Pure; no I/O, no clock, no randomness."""
    raw_type = event.event_type
    try:
        event_type = EventType(raw_type)
    except ValueError as unknown:
        raise ReplayRefused(
            ReplayReasonCode.REPLAY_UNSUPPORTED_EVENT_TYPE,
            sequence=event.sequence,
            event_type=str(raw_type),
            detail=(
                f"event type {raw_type!r} is not known to this build; refusing to "
                "reconstruct a state that would silently omit it"
            ),
        ) from unknown

    if not isinstance(event.payload, dict):
        raise _refuse(event, "payload is not a JSON object")

    HANDLERS[event_type](state, event)
    state.events_replayed += 1
    return state


def reduce_events(mission_id: uuid.UUID, events: Sequence[AuditEventRow]) -> MissionProjection:
    """Reconstruct mission state from an ordered event stream.

    DIAGNOSTIC ENTRY POINT. It does not verify the chain — ``replay_mission``
    does that before calling here, and the API only ever reaches this through
    that gate. Calling it directly on unverified events is a debugging act, and
    its result must not be presented as a trusted reconstruction.

    Events are sorted by sequence first, so the caller's retrieval order cannot
    change the answer.
    """
    state = _ReplayState(mission_id=mission_id)
    for event in sorted(events, key=lambda row: (row.sequence, str(row.event_id))):
        apply_event(state, event)

    return MissionProjection(
        mission_id=state.mission_id,
        mission_state=None if state.mission_state is None else state.mission_state.value,
        events_replayed=state.events_replayed,
        raw_query=state.raw_query,
        quantity=state.quantity,
        policy_decision=state.policy_decision,
        policy_version=state.policy_version,
        policy_reason_codes=list(state.policy_reason_codes),
        requested_amount=state.requested_amount,
        soft_budget=state.soft_budget,
        hard_limit=state.hard_limit,
        selected_offer_id=state.selected_offer_id,
        approval_required=state.approval_required,
        approval_granted=state.approval_granted,
        raw_offer_count=state.raw_offer_count,
        valid_offer_count=state.valid_offer_count,
        invalid_offer_count=state.invalid_offer_count,
        tainted_merchant_fields=list(state.tainted_merchant_fields),
        authorization=state.authorization.model_copy(deep=True),
        payment=state.payment.model_copy(deep=True),
        security_events=list(state.security_events),
        skipped_transitions=list(state.skipped_transitions),
        risk_assessments=list(state.risk_assessments),
    )


# --------------------------------------------------------------------------- #
# Persisted-state comparison (diagnostic; never a repair)
# --------------------------------------------------------------------------- #
async def compare_with_persisted(
    session: AsyncSession, projection: MissionProjection
) -> StateComparison:
    """Report projection drift. Reads only; writes nothing, ever.

    A mismatch means the projection and the rows disagree, and that is worth
    knowing. It is NOT worth acting on automatically: the rows are what the
    kernel enforces against, and letting a reconstruction overwrite them would
    hand authority to the derived view.
    """
    mission = await session.get(Mission, projection.mission_id)
    persisted_state = None if mission is None else mission.state

    authorization = (
        await session.execute(
            select(AuthorizationRow)
            .where(AuthorizationRow.mission_id == projection.mission_id)
            .order_by(AuthorizationRow.issued_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    intent = (
        await session.execute(
            select(PaymentIntentRow)
            .where(PaymentIntentRow.mission_id == projection.mission_id)
            .order_by(PaymentIntentRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    replay_auth = projection.authorization.status
    persisted_auth = None if authorization is None else authorization.status
    replay_payment = projection.payment.state
    persisted_payment = None if intent is None else intent.state

    return StateComparison(
        replay_state=projection.mission_state,
        persisted_state=persisted_state,
        matches=projection.mission_state == persisted_state,
        replay_authorization_status=replay_auth,
        persisted_authorization_status=persisted_auth,
        # None rather than True when neither side has an authorization: there is
        # nothing to compare, and reporting a match would claim agreement about
        # something that does not exist.
        authorization_matches=(
            None
            if replay_auth is None and persisted_auth is None
            else replay_auth == persisted_auth
        ),
        replay_payment_state=replay_payment,
        persisted_payment_state=persisted_payment,
        payment_matches=(
            None
            if replay_payment is None and persisted_payment is None
            else replay_payment == persisted_payment
        ),
    )


# --------------------------------------------------------------------------- #
# The gated entry point
# --------------------------------------------------------------------------- #
async def replay_mission(
    session: AsyncSession, mission_id: uuid.UUID, *, compare: bool = True
) -> MissionReplayResult:
    """Verify, then replay. READ ONLY from end to end.

    The order is the security property. An invalid chain produces
    ``trusted=False`` and NO projection — not a projection with a warning
    attached, because a state object in the response is exactly the thing a
    caller will read past a flag to reach.
    """
    verification = await verify_mission_chain(session, mission_id)
    if not verification.valid:
        return MissionReplayResult(
            mission_id=mission_id,
            audit_valid=False,
            trusted=False,
            reason_code=ReplayReasonCode.REPLAY_AUDIT_INVALID,
            events_replayed=0,
            verification=verification,
            state=None,
            comparison=None,
            decision_trace=[],
            detail=(
                "the audit chain did not verify; replaying it would present a "
                "reconstruction built on evidence already known to be altered"
            ),
        )

    events = await list_events(session, mission_id)
    try:
        projection = reduce_events(mission_id, events)
    except ReplayRefused as refusal:
        return MissionReplayResult(
            mission_id=mission_id,
            audit_valid=True,
            trusted=False,
            reason_code=refusal.reason_code,
            events_replayed=0,
            verification=verification,
            state=None,
            comparison=None,
            decision_trace=[],
            unsupported_events=[{"sequence": refusal.sequence, "event_type": refusal.event_type}],
            detail=refusal.detail,
        )

    comparison = await compare_with_persisted(session, projection) if compare else None
    return MissionReplayResult(
        mission_id=mission_id,
        audit_valid=True,
        trusted=True,
        reason_code=ReplayReasonCode.REPLAY_OK,
        events_replayed=projection.events_replayed,
        verification=verification,
        state=projection,
        comparison=comparison,
        decision_trace=decision_trace_from_events(events),
    )
