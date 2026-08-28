"""The deterministic scorer. A table of rules, not a wall of if-statements.

WHY THE RULES ARE DATA
----------------------
Every factor is a ``FactorRule`` row rather than a branch. Four things fall out
of that which do not fall out of imperative scoring code:

* **The rule set is enumerable.** A report can print exactly what the engine
  looks at; a test can walk every rule and assert its config fields exist, its
  ramp bounds are ordered, and its feature is declared in ``FEATURE_SPECS``. A
  factor with a hardcoded weight, or one reading an undeclared feature, fails a
  test instead of shipping.
* **There are no magic numbers here at all.** Every number a rule uses is read
  from ``RiskConfig`` by field NAME, so the weights live in exactly one auditable
  place and a typo is an ``AttributeError`` at test time rather than a silently
  different score.
* **Monotonicity is a property of the shape, not of each rule.** Four shapes,
  each provably non-decreasing in its input, mean the whole engine inherits
  "more of a risky thing never contributes less risk" without checking nineteen
  functions.
* **The explanation cannot drift from the score.** Both come out of the same
  loop, from the same numbers, in the same pass.

WHAT THE SCORER DELIBERATELY DOES NOT DO
-----------------------------------------
**No negative contributions.** Nothing here can lower the score. A "good"
signal cancelling a hostile one is how a scoring system gets talked out of a
finding: a merchant with a long clean record and one identity-spoof event should
not net out to unremarkable. Reasons to be reassured belong in the recommendation
a human forms, not in the arithmetic.

**No policy re-adjudication.** The scorer never reads ``PolicyOutcome`` and has
no branch on it. It cannot "agree" with a DENY or "disagree" with an ALLOW,
because it never sees one. The decision is copied onto the assessment afterwards
for context only.

**No I/O and no clock.** ``score`` is a pure function of
``(features, config)``. That is what makes "same input, same score" checkable by
equality rather than by inspection, and what lets Hypothesis fuzz the whole
input space without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from services.risk_engine.config import RiskConfig, ramp
from services.risk_engine.models import FeatureValue, RiskFactor


class Shape(str, Enum):
    """How an observation becomes a fraction of the available weight.

    All four are non-decreasing in the direction of risk, which is the property
    ``tests/test_risk_properties.py`` fuzzes.
    """

    #: ``ramp(observed, lo, hi)`` — a proportion or a multiple.
    RATIO = "RATIO"
    #: ``ramp(observed, 0, saturates_at)`` — an occurrence count. Zero scores
    #: nothing; the configured count scores full weight.
    COUNT = "COUNT"
    #: ``ramp(reference - observed, 0, reference)`` — distance BELOW a preferred
    #: level. Used for trust, where risk rises as the value falls.
    SHORTFALL = "SHORTFALL"
    #: Full weight when the observation is falsy. Used where the finding is
    #: binary and there is nothing to grade.
    ABSENT_FLAG = "ABSENT_FLAG"


@dataclass(frozen=True)
class FactorRule:
    """One scoring rule. Every numeric input is a ``RiskConfig`` field name."""

    code: str
    feature: str
    shape: Shape
    weight_field: str
    #: RATIO only.
    lo_field: str | None = None
    hi_field: str | None = None
    #: COUNT only.
    saturates_field: str | None = None
    #: SHORTFALL only.
    reference_field: str | None = None
    #: Rule applies only when this feature is present AND truthy. Used for
    #: mutual exclusion: an unknown merchant has trust 0.0 by construction, so
    #: scoring both MERCHANT_UNKNOWN and MERCHANT_TRUST_BELOW_PREFERRED would
    #: count one fact twice.
    requires_feature_true: str | None = None
    #: Sentence template. Formatted from the observation and the ramp bounds —
    #: never from anything the engine did not measure.
    template: str = ""

    def config_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                self.weight_field,
                self.lo_field,
                self.hi_field,
                self.saturates_field,
                self.reference_field,
            )
            if name is not None
        )


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _num(value: float) -> str:
    """Render a count or multiple without a misleading decimal tail."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


#: The complete ``heuristic-v1`` rule set, grouped as the Phase 7 brief groups
#: them. Order here is the order factors appear in an explanation, so the
#: strongest evidence is read first.
FACTOR_RULES: tuple[FactorRule, ...] = (
    # ---- security history: no benign explanation ------------------------- #
    FactorRule(
        code="MERCHANT_IDENTITY_MISMATCH_HISTORY",
        feature="merchant_identity_mismatch_events",
        shape=Shape.COUNT,
        weight_field="merchant_identity_mismatch_weight",
        saturates_field="merchant_identity_mismatch_saturates_at",
        template=(
            "this merchant has asserted an identity other than the one it "
            "authenticated as on {observed} recorded occasion(s)"
        ),
    ),
    FactorRule(
        code="AUTHORIZATION_REPLAY_HISTORY",
        feature="authorization_replay_attempts",
        shape=Shape.COUNT,
        weight_field="replay_attempt_weight",
        saturates_field="replay_attempt_saturates_at",
        template=(
            "{observed} authorization replay attempt(s) were detected and refused on this mission"
        ),
    ),
    FactorRule(
        code="TRANSACTION_BINDING_FAILURE_HISTORY",
        feature="transaction_binding_failures",
        shape=Shape.COUNT,
        weight_field="binding_failure_weight",
        saturates_field="binding_failure_saturates_at",
        template=(
            "{observed} transaction-binding failure(s) on this mission — the "
            "transaction changed after approval"
        ),
    ),
    FactorRule(
        code="AUDIT_CHAIN_INVALID",
        feature="audit_chain_valid",
        shape=Shape.ABSENT_FLAG,
        weight_field="audit_integrity_weight",
        template=(
            "this mission's hash-chained audit history does not verify, so every "
            "audit-derived feature above was read from untrustworthy history"
        ),
    ),
    # ---- adversarial or malfunctioning behaviour ------------------------- #
    FactorRule(
        code="MERCHANT_AUTHORITY_ESCALATION_HISTORY",
        feature="merchant_authority_escalation_events",
        shape=Shape.COUNT,
        weight_field="merchant_escalation_weight",
        saturates_field="merchant_escalation_saturates_at",
        template=(
            "this merchant has attempted to write user-policy state on {observed} "
            "recorded occasion(s); the authority lattice refused each one"
        ),
    ),
    FactorRule(
        code="MISSION_AUTHORITY_ESCALATION_ATTEMPTS",
        feature="mission_authority_escalation_attempts",
        shape=Shape.COUNT,
        weight_field="mission_escalation_weight",
        saturates_field="mission_escalation_saturates_at",
        template=("{observed} authority-escalation attempt(s) were refused on this mission"),
    ),
    FactorRule(
        code="PROVIDER_RESPONSE_MISMATCH_HISTORY",
        feature="provider_response_mismatch_events",
        shape=Shape.COUNT,
        weight_field="provider_mismatch_weight",
        saturates_field="provider_mismatch_saturates_at",
        template=(
            "{observed} provider response(s) did not describe the transaction "
            "PACTRA requested; the payment was held uncertain rather than settled"
        ),
    ),
    FactorRule(
        code="IDEMPOTENCY_CONFLICT_HISTORY",
        feature="idempotency_conflict_events",
        shape=Shape.COUNT,
        weight_field="idempotency_conflict_weight",
        saturates_field="idempotency_conflict_saturates_at",
        template=(
            "an idempotency key was presented {observed} time(s) for a materially different request"
        ),
    ),
    FactorRule(
        code="MERCHANT_UNKNOWN",
        feature="merchant_known",
        shape=Shape.ABSENT_FLAG,
        weight_field="merchant_unknown_weight",
        template=(
            "the authenticated merchant is not in the server-owned registry, so "
            "it carries no reputation at all"
        ),
    ),
    # ---- genuine concerns ------------------------------------------------ #
    FactorRule(
        code="MERCHANT_TRUST_BELOW_PREFERRED",
        feature="merchant_trust",
        shape=Shape.SHORTFALL,
        weight_field="merchant_trust_weight",
        reference_field="preferred_merchant_trust",
        requires_feature_true="merchant_known",
        template=(
            "registry trust for this merchant is {observed} against an advisory "
            "preference of {reference} (the user's own minimum-trust policy is "
            "enforced separately and is unaffected)"
        ),
    ),
    FactorRule(
        code="AMOUNT_NEAR_HARD_LIMIT",
        feature="amount_to_hard_limit_ratio",
        shape=Shape.RATIO,
        weight_field="amount_hard_limit_weight",
        lo_field="amount_hard_limit_ramp_lo",
        hi_field="amount_hard_limit_ramp_hi",
        template=(
            "the amount is {observed_pct} of the hard limit, leaving little "
            "headroom before the absolute ceiling"
        ),
    ),
    FactorRule(
        code="MERCHANT_FAILED_PAYMENT_RATIO",
        feature="merchant_failed_payment_ratio",
        shape=Shape.RATIO,
        weight_field="merchant_failure_ratio_weight",
        lo_field="merchant_failure_ratio_ramp_lo",
        hi_field="merchant_failure_ratio_ramp_hi",
        template="{observed_pct} of this merchant's prior settled payments failed terminally",
    ),
    FactorRule(
        code="PAYMENT_RETRY_PRESSURE",
        feature="payment_attempts",
        shape=Shape.RATIO,
        weight_field="payment_attempt_weight",
        lo_field="payment_attempt_ramp_lo",
        hi_field="payment_attempt_ramp_hi",
        template="the payment has been attempted {observed} times",
    ),
    FactorRule(
        code="PROVIDER_TIMEOUT_HISTORY",
        feature="provider_timeout_events",
        shape=Shape.COUNT,
        weight_field="provider_timeout_weight",
        saturates_field="provider_timeout_saturates_at",
        template="{observed} provider timeout(s) left this payment's outcome unknown",
    ),
    FactorRule(
        code="AMOUNT_ABOVE_MERCHANT_HISTORY_MEDIAN",
        feature="amount_vs_merchant_median_ratio",
        shape=Shape.RATIO,
        weight_field="amount_anomaly_weight",
        lo_field="amount_anomaly_ramp_lo",
        hi_field="amount_anomaly_ramp_hi",
        template=("the amount is {observed}x this merchant's historical median authorized amount"),
    ),
    # ---- mild signals ---------------------------------------------------- #
    FactorRule(
        code="AMOUNT_ABOVE_SOFT_BUDGET",
        feature="amount_to_soft_budget_ratio",
        shape=Shape.RATIO,
        weight_field="amount_soft_budget_weight",
        lo_field="amount_soft_budget_ramp_lo",
        hi_field="amount_soft_budget_ramp_hi",
        template=(
            "the amount is {observed_pct} of the soft budget; the deterministic "
            "policy engine already requires approval for this"
        ),
    ),
    FactorRule(
        code="AUTHORIZATION_NEAR_EXPIRY",
        feature="authorization_lifetime_used_ratio",
        shape=Shape.RATIO,
        weight_field="authorization_age_weight",
        lo_field="authorization_age_ramp_lo",
        hi_field="authorization_age_ramp_hi",
        template=(
            "{observed_pct} of the authorization window has elapsed; expiry itself "
            "is enforced deterministically"
        ),
    ),
    FactorRule(
        code="WEBHOOK_ANOMALY_HISTORY",
        feature="webhook_anomaly_events",
        shape=Shape.COUNT,
        weight_field="webhook_anomaly_weight",
        saturates_field="webhook_anomaly_saturates_at",
        template=(
            "{observed} duplicate or out-of-order webhook(s) were ignored; some "
            "are normal under at-least-once delivery"
        ),
    ),
    FactorRule(
        code="RECONCILIATION_PRESSURE",
        feature="reconciliation_events",
        shape=Shape.RATIO,
        weight_field="reconciliation_weight",
        lo_field="reconciliation_ramp_lo",
        hi_field="reconciliation_ramp_hi",
        template="this payment required reconciliation {observed} times",
    ),
    FactorRule(
        code="HIGH_INVALID_OFFER_RATIO",
        feature="invalid_offer_ratio",
        shape=Shape.RATIO,
        weight_field="invalid_offer_weight",
        lo_field="invalid_offer_ramp_lo",
        hi_field="invalid_offer_ramp_hi",
        template="{observed_pct} of the offers received were rejected by the kernel",
    ),
)


def _read(rule: FactorRule, config: RiskConfig, field: str | None, what: str) -> float:
    """Read a config field this rule's shape REQUIRES.

    ``test_every_factor_has_the_bounds_its_shape_requires`` asserts every rule
    declares the bounds its shape needs; this is the runtime half of that
    contract. A ``None`` here means the rule TABLE is malformed, and raising
    names the offending rule rather than letting ``getattr(config, None)`` fail
    somewhere less obvious — or, worse, letting a shape silently score against a
    bound it never declared.
    """
    if field is None:
        raise ValueError(f"factor rule {rule.code} ({rule.shape.value}) declares no {what}")
    return float(getattr(config, field))


def _bounds(rule: FactorRule, config: RiskConfig) -> tuple[float | None, float | None]:
    """(threshold, saturation) for the rule, in the feature's own units.

    Reported on the factor so a reader can see how much of the available weight
    the observation earned and what it would have taken to earn all of it.
    """
    if rule.shape is Shape.RATIO:
        return (
            _read(rule, config, rule.lo_field, "ramp lower bound"),
            _read(rule, config, rule.hi_field, "ramp upper bound"),
        )
    if rule.shape is Shape.COUNT:
        return 0.0, _read(rule, config, rule.saturates_field, "saturation count")
    if rule.shape is Shape.SHORTFALL:
        return _read(rule, config, rule.reference_field, "reference level"), 0.0
    return None, None


def _fraction(rule: FactorRule, observed: float, config: RiskConfig) -> float:
    """The fraction of ``weight`` this observation earns. Always in ``[0, 1]``."""
    if rule.shape is Shape.RATIO:
        return ramp(
            observed,
            _read(rule, config, rule.lo_field, "ramp lower bound"),
            _read(rule, config, rule.hi_field, "ramp upper bound"),
        )
    if rule.shape is Shape.COUNT:
        return ramp(observed, 0.0, _read(rule, config, rule.saturates_field, "saturation count"))
    if rule.shape is Shape.SHORTFALL:
        reference = _read(rule, config, rule.reference_field, "reference level")
        if reference <= 0.0:
            # A preference of zero cannot be fallen short of. Returning 0 rather
            # than dividing is the only honest reading.
            return 0.0
        return ramp(reference - observed, 0.0, reference)
    # ABSENT_FLAG: the observation is the finding; there is nothing to grade.
    return 0.0 if observed else 1.0


def _describe(
    rule: FactorRule,
    *,
    observed: float,
    config: RiskConfig,
    fraction: float,
) -> str:
    """Render the factor's sentence from the numbers that produced it.

    Deliberately mechanical. There is no natural-language generation and no
    model anywhere in this path: an explanation that could say something the
    arithmetic did not is an explanation that will, and a hallucinated risk
    reason is worse than no explanation at all.
    """
    reference = (
        f"{_read(rule, config, rule.reference_field, 'reference level'):.2f}"
        if rule.reference_field
        else ""
    )
    body = rule.template.format(
        observed=_num(observed),
        observed_pct=_pct(observed),
        reference=reference,
    )
    return f"{body} ({_pct(fraction)} of the available weight for this factor)"


def score(
    features: dict[str, FeatureValue],
    *,
    config: RiskConfig,
) -> tuple[list[RiskFactor], float]:
    """Apply every rule. Returns ``(factors, raw_points)``. Pure.

    A rule is skipped — producing no factor and no points — when its feature is
    absent, unavailable, or earns a zero fraction. Skipping rather than emitting
    a zero-contribution factor keeps the explanation to lines that actually moved
    the number, which is the only thing that makes an explanation worth reading.
    """
    factors: list[RiskFactor] = []

    for rule in FACTOR_RULES:
        feature = features.get(rule.feature)
        if feature is None or not feature.available:
            continue

        if rule.requires_feature_true is not None:
            gate = features.get(rule.requires_feature_true)
            if gate is None or not gate.available or not gate.value:
                continue

        observed = feature.numeric
        if observed is None:
            continue

        fraction = _fraction(rule, observed, config)
        weight = float(getattr(config, rule.weight_field))
        contribution = weight * fraction
        # Guard the CONTRIBUTION, not the fraction. A denormal observation can
        # produce a fraction that is positive but subnormal, whose product with
        # the weight underflows to exactly 0.0 — and a zero-contribution factor
        # is precisely what this loop exists not to emit. Guarding the fraction
        # instead let that pair through and the RiskFactor validator refused it,
        # which is a crash rather than a skip. Found by Hypothesis; pinned by
        # `test_a_denormal_observation_is_skipped_not_crashed`.
        if contribution <= 0.0:
            continue

        threshold, saturates = _bounds(rule, config)
        factors.append(
            RiskFactor(
                code=rule.code,
                feature=rule.feature,
                contribution=contribution,
                weight=weight,
                observed=feature.value,
                threshold=threshold,
                saturates_at=saturates,
                explanation=_describe(rule, observed=observed, config=config, fraction=fraction),
                derived_from_untrusted_evidence=feature.derived_from_untrusted_evidence,
            )
        )

    # Strongest first. Ties keep rule order, which groups related evidence.
    factors.sort(key=lambda factor: -factor.contribution)

    # Summed AFTER sorting, in the published order, with plain left-to-right
    # addition. Both halves of that are deliberate.
    #
    # Floating-point addition is not associative, so accumulating in RULE order
    # while presenting in SORTED order left `raw_points` and the printed column
    # differing in the last bits — the documented claim ("add the column up and
    # you get the number") was false in exactly the cases with the most factors.
    #
    # And plain `sum` rather than `math.fsum`: fsum is exactly correct, which is
    # a DIFFERENT number from the one a reader gets adding the printed rows
    # left to right. The claim is about what a reader can reproduce, so the
    # engine reproduces the reader's arithmetic rather than the ideal one.
    # Pinned by strict equality in the unit and Hypothesis property tests.
    total = sum(factor.contribution for factor in factors)
    return factors, total


def normalize(raw_points: float, *, config: RiskConfig) -> float:
    """Points to a normalized risk index in ``[0, 1]``.

    A saturating division, not a division by the theoretical maximum. Dividing
    by "everything that could possibly fire" would mean a transaction with two
    unambiguous security findings scored around 0.25, because seventeen other
    factors happened not to apply — the index would measure how many rules
    exist, not how much risk was observed.
    """
    if raw_points <= 0.0:
        return 0.0
    return min(1.0, raw_points / config.saturation_points)
