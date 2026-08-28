"""Scoring is pure, traceable, and monotone. No database, no clock.

Every test here builds a feature map by hand, which is only possible because
extraction and scoring are separate. That separation is the thing being
exercised as much as the arithmetic.
"""

from __future__ import annotations

import pytest
from services.risk_engine.config import DEFAULT_RISK_CONFIG, RiskConfig
from services.risk_engine.features import FEATURE_SPECS
from services.risk_engine.heuristic import FACTOR_RULES, normalize, score
from services.risk_engine.models import (
    FeatureUnavailableReason,
    FeatureValue,
    RiskBand,
)

CONFIG = DEFAULT_RISK_CONFIG


def feature(name: str, value, *, available: bool = True, untrusted: bool = False) -> FeatureValue:
    spec = FEATURE_SPECS[name]
    return FeatureValue(
        name=name,
        value=value if available else None,
        source=spec.source,
        authority=spec.authority,
        trust=spec.trust,
        derived_from_untrusted_evidence=untrusted or spec.derived_from_untrusted_evidence,
        available=available,
        unavailable_reason=None if available else FeatureUnavailableReason.INSUFFICIENT_HISTORY,
        source_detail=spec.detail,
    )


def features(**values) -> dict[str, FeatureValue]:
    return {name: feature(name, value) for name, value in values.items()}


# --------------------------------------------------------------------------- #
# Determinism and range
# --------------------------------------------------------------------------- #
def test_same_features_produce_the_same_score():
    payload = features(amount_to_hard_limit_ratio=0.96, merchant_trust=0.5, merchant_known=True)
    first_factors, first_points = score(payload, config=CONFIG)
    second_factors, second_points = score(payload, config=CONFIG)
    assert first_points == second_points
    assert [f.model_dump() for f in first_factors] == [f.model_dump() for f in second_factors]


def test_score_is_always_within_range():
    for points in (0.0, 0.01, 0.5, 1.0, 3.0, 1e9):
        value = normalize(points, config=CONFIG)
        assert 0.0 <= value <= 1.0


def test_no_features_scores_zero():
    factors, points = score({}, config=CONFIG)
    assert factors == []
    assert points == 0.0
    assert normalize(points, config=CONFIG) == 0.0


# --------------------------------------------------------------------------- #
# Traceability: the explanation IS the arithmetic
# --------------------------------------------------------------------------- #
def test_contributions_sum_to_raw_points_by_exact_equality_not_approximation():
    """Strict ``==``, not ``approx``. The claim is that a reader can add the
    printed column up and get the number, and ``approx`` would not check that.

    This holds because ``score`` sums the factors AFTER sorting them, using
    ``math.fsum``. Accumulating in rule order while presenting in sorted order
    left the two differing in the last bits — floating-point addition is not
    associative — which made the documented claim false in exactly the cases
    with the most factors.
    """
    payload = features(
        amount_to_hard_limit_ratio=0.96,
        amount_to_soft_budget_ratio=1.3,
        merchant_trust=0.4,
        merchant_known=True,
        authorization_replay_attempts=1,
        transaction_binding_failures=1,
        provider_timeout_events=2,
        payment_attempts=3,
        webhook_anomaly_events=2,
        reconciliation_events=2,
    )
    factors, points = score(payload, config=CONFIG)
    assert len(factors) >= 8, "the interesting case is many factors, not few"
    assert sum(f.contribution for f in factors) == points


def test_contributions_sum_exactly_to_the_raw_points():
    payload = features(
        amount_to_hard_limit_ratio=0.96,
        amount_to_soft_budget_ratio=1.3,
        merchant_trust=0.4,
        merchant_known=True,
        authorization_replay_attempts=1,
        provider_timeout_events=2,
        payment_attempts=3,
    )
    factors, points = score(payload, config=CONFIG)
    assert sum(f.contribution for f in factors) == pytest.approx(points, abs=1e-12)


def test_every_factor_names_a_feature_that_was_measured():
    payload = features(
        amount_to_hard_limit_ratio=0.99,
        merchant_known=False,
        transaction_binding_failures=1,
    )
    factors, _ = score(payload, config=CONFIG)
    assert factors
    for factor in factors:
        assert factor.feature in payload
        assert payload[factor.feature].available


def test_every_factor_reports_the_observation_that_produced_it():
    payload = features(amount_to_hard_limit_ratio=0.96)
    factors, _ = score(payload, config=CONFIG)
    assert len(factors) == 1
    assert factors[0].observed == pytest.approx(0.96)
    assert "96%" in factors[0].explanation


def test_factors_are_ordered_strongest_first():
    payload = features(
        amount_to_soft_budget_ratio=1.5,
        authorization_replay_attempts=1,
        provider_timeout_events=2,
    )
    factors, _ = score(payload, config=CONFIG)
    contributions = [f.contribution for f in factors]
    assert contributions == sorted(contributions, reverse=True)


def test_a_contribution_never_exceeds_its_weight():
    payload = features(
        amount_to_hard_limit_ratio=50.0,
        authorization_replay_attempts=999,
        provider_timeout_events=999,
    )
    factors, _ = score(payload, config=CONFIG)
    for factor in factors:
        assert factor.contribution <= factor.weight + 1e-12


def test_a_denormal_observation_is_skipped_not_crashed():
    """Regression: guard the contribution, not the fraction.

    ``ramp(5e-324, 0, 1)`` is positive but subnormal, and multiplying it by a
    weight underflows to exactly 0.0. The loop guarded the FRACTION, so the pair
    slipped through to ``RiskFactor``, whose ``contribution > 0`` validator
    refused it — turning a factor that should simply have been skipped into a
    ValidationError out of the scorer. Found by Hypothesis, not by an example.
    """
    payload = features(idempotency_conflict_events=5e-324)
    factors, points = score(payload, config=CONFIG)
    assert factors == []
    assert points == 0.0


def test_the_smallest_observation_that_still_scores_produces_a_positive_factor():
    """The other side of the same boundary: a real contribution is not skipped."""
    payload = features(idempotency_conflict_events=0.5)
    factors, points = score(payload, config=CONFIG)
    assert len(factors) == 1
    assert factors[0].contribution > 0.0
    assert points > 0.0


# --------------------------------------------------------------------------- #
# Absent is not zero
# --------------------------------------------------------------------------- #
def test_an_unavailable_feature_produces_no_factor():
    payload = {
        "merchant_failed_payment_ratio": feature(
            "merchant_failed_payment_ratio", None, available=False
        )
    }
    factors, points = score(payload, config=CONFIG)
    assert factors == []
    assert points == 0.0


def test_an_unavailable_anomaly_feature_does_not_fabricate_a_baseline():
    """Cold start must be indistinguishable from 'nothing anomalous'."""
    cold = {
        "amount_vs_merchant_median_ratio": feature(
            "amount_vs_merchant_median_ratio", None, available=False
        )
    }
    typical = features(amount_vs_merchant_median_ratio=1.0)
    assert score(cold, config=CONFIG)[1] == score(typical, config=CONFIG)[1] == 0.0


# --------------------------------------------------------------------------- #
# Mutual exclusion and gating
# --------------------------------------------------------------------------- #
def test_unknown_merchant_suppresses_the_trust_shortfall_factor():
    """An unknown merchant's trust is 0.0 by construction; scoring both would
    count one fact twice."""
    payload = features(merchant_known=False, merchant_trust=0.0)
    codes = {f.code for f in score(payload, config=CONFIG)[0]}
    assert "MERCHANT_UNKNOWN" in codes
    assert "MERCHANT_TRUST_BELOW_PREFERRED" not in codes


def test_known_merchant_below_preference_scores_the_shortfall_only():
    payload = features(merchant_known=True, merchant_trust=0.4)
    codes = {f.code for f in score(payload, config=CONFIG)[0]}
    assert codes == {"MERCHANT_TRUST_BELOW_PREFERRED"}


def test_trust_at_or_above_the_preference_scores_nothing():
    payload = features(merchant_known=True, merchant_trust=0.9)
    assert score(payload, config=CONFIG)[0] == []


# --------------------------------------------------------------------------- #
# Direction: more risk is never less risk
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,low,high",
    [
        ("amount_to_hard_limit_ratio", 0.80, 0.99),
        ("amount_to_soft_budget_ratio", 1.05, 1.45),
        ("authorization_replay_attempts", 0, 1),
        ("transaction_binding_failures", 0, 1),
        ("provider_timeout_events", 1, 2),
        ("provider_response_mismatch_events", 0, 1),
        ("idempotency_conflict_events", 0, 1),
        ("payment_attempts", 2, 4),
        ("webhook_anomaly_events", 1, 3),
        ("reconciliation_events", 2, 3),
        ("invalid_offer_ratio", 0.5, 1.0),
        ("amount_vs_merchant_median_ratio", 2.0, 3.0),
        ("merchant_identity_mismatch_events", 0, 1),
        ("merchant_authority_escalation_events", 0, 2),
        ("mission_authority_escalation_attempts", 0, 2),
        ("authorization_lifetime_used_ratio", 0.85, 1.0),
    ],
)
def test_more_of_a_risky_signal_never_scores_less(name, low, high):
    lower = score({name: feature(name, low)}, config=CONFIG)[1]
    higher = score({name: feature(name, high)}, config=CONFIG)[1]
    assert higher >= lower


def test_lower_merchant_trust_never_scores_less():
    """Trust runs the other way: risk rises as the value falls."""
    payload_high = features(merchant_known=True, merchant_trust=0.7)
    payload_low = features(merchant_known=True, merchant_trust=0.1)
    assert score(payload_low, config=CONFIG)[1] >= score(payload_high, config=CONFIG)[1]


# --------------------------------------------------------------------------- #
# Calibration claims, checked
# --------------------------------------------------------------------------- #
def test_one_severe_signal_reaches_high_and_not_critical():
    payload = features(authorization_replay_attempts=1)
    value = normalize(score(payload, config=CONFIG)[1], config=CONFIG)
    assert CONFIG.band_for(value) is RiskBand.HIGH


def test_two_severe_signals_reach_critical():
    payload = features(authorization_replay_attempts=1, transaction_binding_failures=1)
    value = normalize(score(payload, config=CONFIG)[1], config=CONFIG)
    assert CONFIG.band_for(value) is RiskBand.CRITICAL


def test_a_legitimately_approved_high_value_transaction_stays_low():
    """The false positive that would make the whole layer unreadable."""
    payload = features(
        amount_to_hard_limit_ratio=4299 / 4500,
        amount_to_soft_budget_ratio=4299 / 4000,
        merchant_known=True,
        merchant_trust=0.9,
    )
    value = normalize(score(payload, config=CONFIG)[1], config=CONFIG)
    assert CONFIG.band_for(value) is RiskBand.LOW


def test_a_clearly_risky_case_scores_above_a_benign_one():
    benign = features(amount_to_hard_limit_ratio=0.2, merchant_known=True, merchant_trust=0.9)
    risky = features(
        amount_to_hard_limit_ratio=0.2,
        merchant_known=True,
        merchant_trust=0.9,
        merchant_identity_mismatch_events=1,
        authorization_replay_attempts=1,
    )
    assert score(risky, config=CONFIG)[1] > score(benign, config=CONFIG)[1]


# --------------------------------------------------------------------------- #
# Provenance survives scoring
# --------------------------------------------------------------------------- #
def test_untrusted_evidence_provenance_reaches_the_factor():
    """A count of merchant misbehaviour must not be laundered into a plain number."""
    payload = features(merchant_identity_mismatch_events=1)
    factors, _ = score(payload, config=CONFIG)
    assert factors[0].derived_from_untrusted_evidence is True


def test_registry_sourced_features_are_not_marked_untrusted():
    payload = features(merchant_known=True, merchant_trust=0.2)
    factors, _ = score(payload, config=CONFIG)
    assert factors[0].derived_from_untrusted_evidence is False


# --------------------------------------------------------------------------- #
# The rule table itself
# --------------------------------------------------------------------------- #
def test_every_rule_reads_a_declared_feature():
    """A rule scoring an undeclared feature would score a number with no source."""
    for rule in FACTOR_RULES:
        assert rule.feature in FEATURE_SPECS, f"{rule.code} reads undeclared {rule.feature}"


def test_every_rule_has_a_template_that_mentions_its_observation():
    for rule in FACTOR_RULES:
        assert rule.template, rule.code
        assert "{observed" in rule.template or rule.shape.name == "ABSENT_FLAG", rule.code


def test_a_custom_config_changes_the_score_only_through_declared_fields():
    """Proves the weights genuinely live in the config, not in the code."""
    payload = features(authorization_replay_attempts=1)
    baseline = score(payload, config=CONFIG)[1]
    softened = score(payload, config=RiskConfig(replay_attempt_weight=0.01))[1]
    assert softened < baseline
