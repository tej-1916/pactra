"""Read-only feature extraction. Every number declares where it came from.

READ-ONLY IS STRUCTURAL, NOT PROMISED
-------------------------------------
Every database access in this module is a ``select``. There is no ``add``, no
``flush``, no ``commit``, no ``update``, and no import that could reach one:
this module cannot see ``services.payment_executor``, the merchant adapters, or
the authorization write path. ``tests/test_risk_isolation.py`` parses the import
graph and asserts it, then replaces every side-effecting function with a
landmine, then counts every table before and after. Extraction consumes no
authorization, creates no intent, calls no merchant, and calls no provider.

A FEATURE IS NOT TRUSTED BECAUSE IT IS A NUMBER
------------------------------------------------
``FEATURE_SPECS`` is the authoritative table of what each feature reads and at
what authority. Three rules it encodes:

* **Merchant trust comes from the registry, never the payload.** There is no
  code path here that reads a merchant-controlled field. ``RawMerchantOffer``
  has no ``merchant_trust`` at all, so a merchant asserting perfect trust has
  the key dropped at the schema boundary long before this module runs — the
  defence is structural, and this module simply never goes looking.
* **Audit-derived counts keep their provenance.** Several features count
  ``SECURITY_VIOLATION`` events: records the KERNEL wrote, about behaviour a
  MERCHANT attempted. ``derived_from_untrusted_evidence=True`` travels with
  those values and is rendered in the explanation, rather than being laundered
  into "trusted, because the row is ours".
* **Absent is not zero.** A feature with nothing behind it is ``available=False``
  with a reason, never ``0.0``. "No prior payments with this merchant" scored as
  "a perfect payment record" is the single easiest way to make a risk engine
  quietly wrong in the direction that costs money.

A test asserts every extracted feature has a ``FEATURE_SPECS`` entry, and that
no entry claims ``FeatureSource.MERCHANT_PAYLOAD``.

BOUNDED WINDOWS, STATED
-----------------------
Cross-mission history is read through bounded windows
(``SECURITY_HISTORY_WINDOW``, ``anomaly.HISTORY_WINDOW``). A risk assessment has
to be cheap, and an unbounded scan is not. The consequence is real and is
disclosed rather than hidden: a merchant whose violations are older than the
window is not counted, so these counters are "recent history", not "all
history".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from apps.api.db.models import (
    AuditEventRow,
    AuthorizationRow,
    Mission,
    MissionConstraintsRow,
    Offer,
    PaymentIntentRow,
    PolicyDecisionRow,
)
from packages.schemas.domain import EventType, ReasonCode, as_utc
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.audit_ledger.ledger import list_events
from services.audit_ledger.verify import verify_events
from services.risk_engine.anomaly import (
    MerchantHistory,
    empty_history,
    load_merchant_history,
)
from services.risk_engine.config import RiskConfig
from services.risk_engine.models import (
    FeatureSource,
    FeatureUnavailableReason,
    FeatureValue,
)
from services.security_kernel.merchant_registry import MerchantRegistry, default_merchant_registry

#: Stands in for "this mission settled on no merchant" in a ``MerchantHistory``.
#: A sentinel rather than ``None`` so the history object always has the same
#: shape; nothing looks it up, because ``load_merchant_history`` is never called
#: for a mission with no counterparty.
NO_MERCHANT = ""

#: How many recent SECURITY_VIOLATION events are scanned for merchant history.
#: Bounded for cost; see the module docstring on what that costs in coverage.
SECURITY_HISTORY_WINDOW = 500

#: Payload key the orchestrator writes for an authority-escalation violation.
_MERCHANT_KEY = "merchant_id"
#: Payload key the orchestrator writes for an identity-spoof violation. Distinct
#: because in a spoof the AUTHENTICATED identity is the one that matters, and
#: attributing the violation to the merchant it impersonated would blame the
#: victim.
_AUTHENTICATED_MERCHANT_KEY = "authenticated_merchant_id"


@dataclass(frozen=True)
class FeatureSpec:
    """Declared provenance for one feature. The documentation IS the code."""

    source: FeatureSource
    authority: AuthorityLevel
    trust: TrustLevel
    detail: str
    derived_from_untrusted_evidence: bool = False


def _audit(detail: str, *, untrusted_evidence: bool = False) -> FeatureSpec:
    return FeatureSpec(
        source=FeatureSource.AUDIT_LEDGER,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail=detail,
        derived_from_untrusted_evidence=untrusted_evidence,
    )


#: The authoritative provenance table. Every feature this module can emit has an
#: entry, and no entry names ``MERCHANT_PAYLOAD``.
FEATURE_SPECS: dict[str, FeatureSpec] = {
    # ---- amount ---------------------------------------------------------- #
    "amount_to_hard_limit_ratio": FeatureSpec(
        source=FeatureSource.POLICY_DECISION,
        authority=AuthorityLevel.USER_POLICY,
        trust=TrustLevel.AUTHORITATIVE,
        detail=(
            "policy_decisions.requested_amount over mission_constraints."
            "hard_limit_inr — a server-computed amount against a USER_POLICY ceiling"
        ),
    ),
    "amount_to_soft_budget_ratio": FeatureSpec(
        source=FeatureSource.POLICY_DECISION,
        authority=AuthorityLevel.USER_POLICY,
        trust=TrustLevel.AUTHORITATIVE,
        detail=(
            "policy_decisions.requested_amount over mission_constraints."
            "soft_budget_inr — both server-held"
        ),
    ),
    "requested_amount_inr": FeatureSpec(
        source=FeatureSource.POLICY_DECISION,
        authority=AuthorityLevel.SYSTEM_SECURITY_POLICY,
        trust=TrustLevel.TRUSTED,
        detail="policy_decisions.requested_amount, computed by the deterministic engine",
    ),
    "quantity": FeatureSpec(
        source=FeatureSource.MISSION_ROW,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail="missions.quantity, validated through CreateMissionRequest at the API boundary",
    ),
    # ---- merchant -------------------------------------------------------- #
    "merchant_trust": FeatureSpec(
        source=FeatureSource.MERCHANT_REGISTRY,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail=(
            "MerchantRegistry.trust_for(authenticated merchant id) — server-owned. "
            "RawMerchantOffer has no merchant_trust field, so a payload cannot "
            "contribute to this value"
        ),
    ),
    "merchant_known": FeatureSpec(
        source=FeatureSource.MERCHANT_REGISTRY,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail="MerchantRegistry membership for the transport-authenticated identity",
    ),
    "merchant_identity_mismatch_events": _audit(
        "SECURITY_VIOLATION events with reason MERCHANT_IDENTITY_MISMATCH naming "
        "this authenticated merchant, within the recent window",
        untrusted_evidence=True,
    ),
    "merchant_authority_escalation_events": _audit(
        "SECURITY_VIOLATION events with reason AUTHORITY_ESCALATION naming this "
        "authenticated merchant, within the recent window",
        untrusted_evidence=True,
    ),
    "merchant_failed_payment_ratio": FeatureSpec(
        source=FeatureSource.PAYMENT_INTENT_ROW,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail=(
            "payment_intents terminal outcomes for this merchant across prior "
            "missions; gated on min_merchant_payment_history"
        ),
    ),
    "merchant_payment_observations": FeatureSpec(
        source=FeatureSource.PAYMENT_INTENT_ROW,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail="count of prior settled/failed payment intents for this merchant",
    ),
    # ---- authorization --------------------------------------------------- #
    "authorization_replay_attempts": _audit(
        "AUTHORIZATION_REPLAY_DETECTED events on this mission",
        untrusted_evidence=True,
    ),
    "transaction_binding_failures": _audit(
        "TRANSACTION_BINDING_FAILURE events on this mission",
        untrusted_evidence=True,
    ),
    "mission_authority_escalation_attempts": _audit(
        "SECURITY_VIOLATION events with reason AUTHORITY_ESCALATION on this mission",
        untrusted_evidence=True,
    ),
    "authorization_lifetime_used_ratio": FeatureSpec(
        source=FeatureSource.AUTHORIZATION_ROW,
        authority=AuthorityLevel.AUTHORIZATION,
        trust=TrustLevel.TRUSTED,
        detail="elapsed over total window from authorizations.issued_at/expires_at",
    ),
    "authorization_age_seconds": FeatureSpec(
        source=FeatureSource.AUTHORIZATION_ROW,
        authority=AuthorityLevel.AUTHORIZATION,
        trust=TrustLevel.TRUSTED,
        detail="seconds since authorizations.issued_at",
    ),
    # ---- payment --------------------------------------------------------- #
    "payment_attempts": FeatureSpec(
        source=FeatureSource.PAYMENT_INTENT_ROW,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail="payment_intents.attempts for this mission's intent",
    ),
    "provider_timeout_events": _audit("PAYMENT_PROVIDER_TIMEOUT events on this mission"),
    "provider_response_mismatch_events": _audit(
        "audit events whose payload reason_code is PROVIDER_RESPONSE_MISMATCH — "
        "written by _mark_uncertain when a provider response did not describe "
        "the requested transaction",
        untrusted_evidence=True,
    ),
    "idempotency_conflict_events": _audit(
        "IDEMPOTENCY_CONFLICT events on this mission",
        untrusted_evidence=True,
    ),
    "webhook_anomaly_events": _audit(
        "DUPLICATE_WEBHOOK_IGNORED + WEBHOOK_OUT_OF_ORDER_IGNORED events on this mission",
        untrusted_evidence=True,
    ),
    "reconciliation_events": _audit("PAYMENT_RECONCILED events on this mission"),
    # ---- integrity ------------------------------------------------------- #
    "audit_chain_valid": _audit(
        "verify_events over this mission's chain — the same pure verifier "
        "GET /audit/verify uses, run over events already loaded here"
    ),
    "invalid_offer_ratio": FeatureSpec(
        source=FeatureSource.MISSION_ROW,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        detail="offers.valid == false over total offers, as recorded by normalization",
    ),
    # ---- anomaly --------------------------------------------------------- #
    "amount_vs_merchant_median_ratio": FeatureSpec(
        source=FeatureSource.AUTHORIZATION_ROW,
        authority=AuthorityLevel.AUTHORIZATION,
        trust=TrustLevel.TRUSTED,
        detail=(
            "this amount over the median authorizations.bound_amount_inr for this "
            "merchant across prior missions; gated on min_history_observations"
        ),
    ),
    "merchant_amount_observations": FeatureSpec(
        source=FeatureSource.AUTHORIZATION_ROW,
        authority=AuthorityLevel.AUTHORIZATION,
        trust=TrustLevel.TRUSTED,
        detail="count of prior authorized amounts for this merchant",
    ),
}


@dataclass
class MissionFacts:
    """Everything one assessment read, kept together for the explanation.

    A plain dataclass rather than a model: it never crosses a process boundary,
    and the ``FeatureValue`` map built from it is what gets serialized.
    """

    mission_id: uuid.UUID
    mission: Mission | None = None
    constraints: MissionConstraintsRow | None = None
    policy_decision: PolicyDecisionRow | None = None
    authorization: AuthorizationRow | None = None
    payment_intent: PaymentIntentRow | None = None
    offers: list[Offer] = field(default_factory=list)
    events: list[AuditEventRow] = field(default_factory=list)
    merchant_id: str | None = None
    merchant_trust: float = 0.0
    merchant_known: bool = False
    history: MerchantHistory | None = None
    audit_chain_valid: bool = True
    audit_events_checked: int = 0


class MissionNotFound(Exception):
    """No such mission. Raised rather than returning a zero-risk assessment.

    An assessment for a mission that does not exist would be a score with no
    subject, and ``LOW`` is exactly the wrong default to hand a caller who asked
    about something that is not there.
    """

    def __init__(self, mission_id: uuid.UUID) -> None:
        super().__init__(f"mission {mission_id} does not exist")
        self.mission_id = mission_id


def _value(
    name: str,
    value: float | int | bool | None,
    *,
    unavailable: FeatureUnavailableReason | None = None,
) -> FeatureValue:
    """Build a ``FeatureValue`` from the declared spec.

    Going through ``FEATURE_SPECS`` rather than passing provenance at each call
    site is what makes "every feature has a documented source" enforceable: a
    name with no entry raises here, at extraction time, rather than producing a
    number whose origin nobody recorded.
    """
    spec = FEATURE_SPECS.get(name)
    if spec is None:  # pragma: no cover - guarded by test_every_feature_is_declared
        raise KeyError(f"feature {name!r} has no declared source in FEATURE_SPECS")
    available = unavailable is None
    return FeatureValue(
        name=name,
        value=value if available else None,
        source=spec.source,
        authority=spec.authority,
        trust=spec.trust,
        derived_from_untrusted_evidence=spec.derived_from_untrusted_evidence,
        available=available,
        unavailable_reason=unavailable,
        source_detail=spec.detail,
    )


def _payload_reason(event: AuditEventRow) -> str | None:
    payload: Any = event.payload
    if not isinstance(payload, dict):
        return None
    reason = payload.get("reason_code")
    return reason if isinstance(reason, str) else None


def _count_type(events: list[AuditEventRow], *types: EventType) -> int:
    wanted = {t.value for t in types}
    return sum(1 for event in events if event.event_type in wanted)


async def _load_selected_merchant(
    session: AsyncSession,
    *,
    authorization: AuthorizationRow | None,
    decision: PolicyDecisionRow | None,
) -> str | None:
    """The AUTHENTICATED merchant this mission settled on, if any.

    Preference order matters. The authorization's ``bound_merchant_id`` is the
    strongest statement available — it is inside the transaction digest, so it
    is the merchant the approval actually commits to. The policy decision's
    selected offer is the fallback for a mission that was denied or has not
    reached issuance. ``Offer.merchant_id`` is itself the transport-authenticated
    identity (the claim is kept separately in ``Offer.raw``), so neither path can
    return an impersonated id.
    """
    if authorization is not None:
        return authorization.bound_merchant_id
    if decision is not None and decision.selected_offer_id is not None:
        offer = await session.get(Offer, decision.selected_offer_id)
        if offer is not None:
            return offer.merchant_id
    return None


async def _merchant_violation_counts(session: AsyncSession, merchant_id: str) -> tuple[int, int]:
    """(identity mismatches, authority escalations) naming this merchant.

    Filtered in Python over a bounded, ordered window rather than with a JSON
    predicate in SQL. ``audit_events.payload`` is a portable ``JSON`` column and
    the two backends disagree on how to index into one; a dialect-specific
    predicate here would silently return different counts on SQLite and
    PostgreSQL, and a risk score that depends on the database engine is not a
    risk score.
    """
    rows = await session.execute(
        select(AuditEventRow)
        .where(AuditEventRow.event_type == EventType.SECURITY_VIOLATION.value)
        .order_by(AuditEventRow.created_at.desc())
        .limit(SECURITY_HISTORY_WINDOW)
    )
    mismatches = 0
    escalations = 0
    for event in rows.scalars().all():
        payload = event.payload if isinstance(event.payload, dict) else {}
        reason = payload.get("reason_code")
        if reason == ReasonCode.MERCHANT_IDENTITY_MISMATCH.value:
            if payload.get(_AUTHENTICATED_MERCHANT_KEY) == merchant_id:
                mismatches += 1
        elif reason == ReasonCode.AUTHORITY_ESCALATION.value:
            if payload.get(_MERCHANT_KEY) == merchant_id:
                escalations += 1
    return mismatches, escalations


async def load_mission_facts(
    session: AsyncSession,
    mission_id: uuid.UUID,
    *,
    config: RiskConfig,
    registry: MerchantRegistry | None = None,
) -> MissionFacts:
    """Load every row an assessment reads. SELECT only.

    One pass, one place. Extraction and scoring are separated so the scorer is a
    pure function of ``MissionFacts`` — which is what lets
    ``tests/test_risk_heuristic.py`` exercise every factor without a database
    and ``tests/test_risk_properties.py`` fuzz them with Hypothesis.
    """
    mission = await session.get(Mission, mission_id)
    if mission is None:
        raise MissionNotFound(mission_id)

    constraints = (
        await session.execute(
            select(MissionConstraintsRow).where(MissionConstraintsRow.mission_id == mission_id)
        )
    ).scalar_one_or_none()

    decision = (
        await session.execute(
            select(PolicyDecisionRow)
            .where(PolicyDecisionRow.mission_id == mission_id)
            .order_by(PolicyDecisionRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    authorization = (
        await session.execute(
            select(AuthorizationRow)
            .where(AuthorizationRow.mission_id == mission_id)
            .order_by(AuthorizationRow.issued_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    payment_intent = (
        await session.execute(
            select(PaymentIntentRow)
            .where(PaymentIntentRow.mission_id == mission_id)
            .order_by(PaymentIntentRow.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    offers = list(
        (await session.execute(select(Offer).where(Offer.mission_id == mission_id))).scalars().all()
    )

    events = await list_events(session, mission_id)
    # The SAME verifier the /audit/verify route uses, over events already in
    # memory. Deliberately not a second implementation: a risk engine that
    # disagreed with the verifier about whether history is intact would be worse
    # than one that never looked.
    verification = verify_events(mission_id, events)

    merchant_id = await _load_selected_merchant(
        session, authorization=authorization, decision=decision
    )
    merchant_registry = registry or default_merchant_registry()
    record = None if merchant_id is None else merchant_registry.record_for(merchant_id)

    history = (
        empty_history(NO_MERCHANT)
        if merchant_id is None
        else await load_merchant_history(
            session,
            merchant_id=merchant_id,
            exclude_mission_id=mission_id,
            min_observations=config.min_history_observations,
        )
    )

    return MissionFacts(
        mission_id=mission_id,
        mission=mission,
        constraints=constraints,
        policy_decision=decision,
        authorization=authorization,
        payment_intent=payment_intent,
        offers=offers,
        events=events,
        merchant_id=merchant_id,
        merchant_trust=0.0 if record is None else record.trust_score,
        merchant_known=False if record is None else record.known,
        history=history,
        audit_chain_valid=verification.valid,
        audit_events_checked=verification.events_checked,
    )


def extract_features(
    facts: MissionFacts,
    *,
    config: RiskConfig,
    now: Any = None,
) -> dict[str, FeatureValue]:
    """Turn loaded rows into declared, provenance-carrying features. Pure.

    No I/O, no clock unless one is handed in. ``now`` is a parameter rather than
    a call to ``utcnow()`` so that the authorization-age feature — the only
    time-dependent value here — is reproducible: a scorer that reads the wall
    clock cannot satisfy "same input, same score", which is invariant #1 of the
    Phase 7 test matrix.
    """
    features: dict[str, FeatureValue] = {}
    decision = facts.policy_decision
    constraints = facts.constraints
    events = facts.events

    # ---- amount ---------------------------------------------------------- #
    amount = None if decision is None else decision.requested_amount
    # Narrowed on BOTH: an amount exists only when a decision does, and saying so
    # explicitly is what lets the else-branch read the decision's own budgets as
    # a fallback when the constraints row is absent.
    if decision is None or amount is None:
        for name in (
            "requested_amount_inr",
            "amount_to_hard_limit_ratio",
            "amount_to_soft_budget_ratio",
        ):
            features[name] = _value(
                name, None, unavailable=FeatureUnavailableReason.NO_POLICY_DECISION
            )
    else:
        features["requested_amount_inr"] = _value("requested_amount_inr", amount)
        hard = constraints.hard_limit_inr if constraints is not None else decision.hard_limit
        soft = constraints.soft_budget_inr if constraints is not None else decision.soft_budget
        features["amount_to_hard_limit_ratio"] = _value(
            "amount_to_hard_limit_ratio", (amount / hard) if hard else None
        )
        features["amount_to_soft_budget_ratio"] = _value(
            "amount_to_soft_budget_ratio", (amount / soft) if soft else None
        )

    features["quantity"] = _value(
        "quantity", None if facts.mission is None else facts.mission.quantity
    )

    # ---- merchant -------------------------------------------------------- #
    if facts.merchant_id is None:
        for name in ("merchant_trust", "merchant_known"):
            features[name] = _value(
                name, None, unavailable=FeatureUnavailableReason.NO_SELECTED_MERCHANT
            )
    else:
        features["merchant_trust"] = _value("merchant_trust", facts.merchant_trust)
        features["merchant_known"] = _value("merchant_known", facts.merchant_known)

    history = facts.history or empty_history(facts.merchant_id or "")
    features["merchant_payment_observations"] = _value(
        "merchant_payment_observations", history.payment_observations
    )
    if history.payment_observations >= config.min_merchant_payment_history:
        features["merchant_failed_payment_ratio"] = _value(
            "merchant_failed_payment_ratio", history.failure_ratio
        )
    else:
        features["merchant_failed_payment_ratio"] = _value(
            "merchant_failed_payment_ratio",
            None,
            unavailable=FeatureUnavailableReason.INSUFFICIENT_HISTORY,
        )

    # ---- authorization --------------------------------------------------- #
    features["authorization_replay_attempts"] = _value(
        "authorization_replay_attempts",
        _count_type(events, EventType.AUTHORIZATION_REPLAY_DETECTED),
    )
    features["transaction_binding_failures"] = _value(
        "transaction_binding_failures",
        _count_type(events, EventType.TRANSACTION_BINDING_FAILURE),
    )
    features["mission_authority_escalation_attempts"] = _value(
        "mission_authority_escalation_attempts",
        sum(
            1
            for event in events
            if event.event_type == EventType.SECURITY_VIOLATION.value
            and _payload_reason(event) == ReasonCode.AUTHORITY_ESCALATION.value
        ),
    )

    authorization = facts.authorization
    if authorization is None or now is None:
        for name in ("authorization_age_seconds", "authorization_lifetime_used_ratio"):
            features[name] = _value(
                name, None, unavailable=FeatureUnavailableReason.NO_AUTHORIZATION
            )
    else:
        issued = as_utc(authorization.issued_at)
        expires = as_utc(authorization.expires_at)
        moment = as_utc(now)
        window = (expires - issued).total_seconds()
        elapsed = (moment - issued).total_seconds()
        features["authorization_age_seconds"] = _value(
            "authorization_age_seconds", max(0.0, elapsed)
        )
        features["authorization_lifetime_used_ratio"] = _value(
            "authorization_lifetime_used_ratio",
            # A non-positive window cannot be produced by the kernel, but a
            # ratio over one would be a division that only fails on impossible
            # data — which still fails.
            max(0.0, elapsed / window) if window > 0 else None,
        )

    # ---- payment --------------------------------------------------------- #
    if facts.payment_intent is None:
        features["payment_attempts"] = _value(
            "payment_attempts", None, unavailable=FeatureUnavailableReason.NO_PAYMENT_INTENT
        )
    else:
        features["payment_attempts"] = _value("payment_attempts", facts.payment_intent.attempts)

    features["provider_timeout_events"] = _value(
        "provider_timeout_events", _count_type(events, EventType.PAYMENT_PROVIDER_TIMEOUT)
    )
    features["provider_response_mismatch_events"] = _value(
        "provider_response_mismatch_events",
        sum(
            1
            for event in events
            if _payload_reason(event) == ReasonCode.PROVIDER_RESPONSE_MISMATCH.value
        ),
    )
    features["idempotency_conflict_events"] = _value(
        "idempotency_conflict_events", _count_type(events, EventType.IDEMPOTENCY_CONFLICT)
    )
    features["webhook_anomaly_events"] = _value(
        "webhook_anomaly_events",
        _count_type(
            events,
            EventType.DUPLICATE_WEBHOOK_IGNORED,
            EventType.WEBHOOK_OUT_OF_ORDER_IGNORED,
        ),
    )
    features["reconciliation_events"] = _value(
        "reconciliation_events", _count_type(events, EventType.PAYMENT_RECONCILED)
    )

    # ---- integrity ------------------------------------------------------- #
    features["audit_chain_valid"] = _value("audit_chain_valid", facts.audit_chain_valid)
    total_offers = len(facts.offers)
    if total_offers < config.min_offers_for_ratio:
        features["invalid_offer_ratio"] = _value(
            "invalid_offer_ratio", None, unavailable=FeatureUnavailableReason.NO_OFFERS
        )
    else:
        invalid = sum(1 for offer in facts.offers if not offer.valid)
        features["invalid_offer_ratio"] = _value("invalid_offer_ratio", invalid / total_offers)

    # ---- anomaly (history-gated) ----------------------------------------- #
    features["merchant_amount_observations"] = _value(
        "merchant_amount_observations", history.amount_observations
    )
    ratio = None if amount is None else history.amount_ratio(amount)
    if ratio is None:
        features["amount_vs_merchant_median_ratio"] = _value(
            "amount_vs_merchant_median_ratio",
            None,
            unavailable=(
                FeatureUnavailableReason.NO_POLICY_DECISION
                if amount is None
                else FeatureUnavailableReason.INSUFFICIENT_HISTORY
            ),
        )
    else:
        features["amount_vs_merchant_median_ratio"] = _value(
            "amount_vs_merchant_median_ratio", ratio
        )

    return features


async def extract_merchant_history_features(
    session: AsyncSession, facts: MissionFacts
) -> dict[str, FeatureValue]:
    """Cross-mission merchant violation counts. SELECT only.

    Separated from ``extract_features`` because it needs the database and
    ``extract_features`` deliberately does not — keeping the pure scorer pure is
    worth one extra call at the seam.
    """
    if facts.merchant_id is None:
        return {
            name: _value(name, None, unavailable=FeatureUnavailableReason.NO_SELECTED_MERCHANT)
            for name in (
                "merchant_identity_mismatch_events",
                "merchant_authority_escalation_events",
            )
        }
    mismatches, escalations = await _merchant_violation_counts(session, facts.merchant_id)
    return {
        "merchant_identity_mismatch_events": _value(
            "merchant_identity_mismatch_events", mismatches
        ),
        "merchant_authority_escalation_events": _value(
            "merchant_authority_escalation_events", escalations
        ),
    }
