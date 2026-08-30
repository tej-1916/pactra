"""The evaluation harness must measure honestly, including when it measures badly.

The tests here are mostly about the METRICS rather than the scores: a harness
that computes a detection rate over the wrong denominator, or that quietly
rescues an errored run, reports a number nobody can rely on. Several tests
deliberately drive the harness with fabricated outcomes so a metric can be
checked against arithmetic done by hand.
"""

from __future__ import annotations

import dataclasses

import pytest
from services.risk_engine.config import DEFAULT_RISK_CONFIG, RiskConfig
from services.risk_engine.evaluation import (
    HARNESS_VERSION,
    ScenarioOutcome,
    compute_metrics,
    evaluate,
    percentile,
    run_scenario,
)
from services.risk_engine.models import RiskBand, RiskRecommendation
from services.risk_engine.scenarios import (
    RISK_SCENARIOS,
    RISK_SCENARIOS_BY_ID,
    SYNTHETIC_DATA_DISCLOSURE,
    RiskCategory,
    RiskLabel,
    RiskScenario,
)

CONFIG = DEFAULT_RISK_CONFIG


def outcome(
    scenario_id: str,
    label: RiskLabel,
    score: float,
    *,
    iteration: int = 1,
    error: str | None = None,
    category: str = "BASELINE",
) -> ScenarioOutcome:
    return ScenarioOutcome(
        scenario_id=scenario_id,
        scenario_name=scenario_id,
        label=label,
        category=category,
        iteration=iteration,
        score=score,
        band=CONFIG.band_for(score),
        recommendation=CONFIG.recommendation_for(CONFIG.band_for(score)),
        history_available=True,
        cold_start=False,
        audit_chain_verified=True,
        assess_ms=1.0,
        error=error,
    )


# --------------------------------------------------------------------------- #
# The corpus itself
# --------------------------------------------------------------------------- #
def test_the_corpus_has_both_labels_and_enough_of_each():
    """A detection rate needs risky cases; a false-positive rate needs benign
    ones. A corpus missing either half silently produces an ``n/a``."""
    benign = [s for s in RISK_SCENARIOS if s.label is RiskLabel.BENIGN]
    risky = [s for s in RISK_SCENARIOS if s.label is RiskLabel.RISKY]
    assert len(benign) >= 5
    assert len(risky) >= 5


def test_scenario_ids_are_unique():
    ids = [s.id for s in RISK_SCENARIOS]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(RISK_SCENARIOS_BY_ID)


def test_every_scenario_declares_a_label_a_category_and_a_description():
    for scenario in RISK_SCENARIOS:
        assert scenario.label in RiskLabel
        assert scenario.category in RiskCategory
        assert len(scenario.description) > 30, scenario.id


def test_the_corpus_covers_every_required_evaluation_dimension():
    """The Phase 7 brief names the case families the evaluation must contain."""
    covered = {scenario.category for scenario in RISK_SCENARIOS}
    for required in (
        RiskCategory.BASELINE,
        RiskCategory.HIGH_VALUE,
        RiskCategory.COLD_START,
        RiskCategory.MERCHANT_TRUST,
        RiskCategory.SECURITY_HISTORY,
        RiskCategory.PAYMENT_ANOMALY,
        RiskCategory.AUDIT_INTEGRITY,
        RiskCategory.BEHAVIOURAL_ANOMALY,
    ):
        assert required in covered, f"no scenario covers {required.value}"


def test_scenarios_are_frozen_so_a_label_cannot_be_revised_at_runtime():
    """Labels must not be adjustable to match a score.

    ``FrozenInstanceError`` specifically, not a bare ``Exception``: a blind
    catch here would also pass if the assignment raised for some unrelated
    reason, which would leave the property untested while looking tested.
    """
    with pytest.raises(dataclasses.FrozenInstanceError):
        RISK_SCENARIOS[0].label = RiskLabel.BENIGN


def test_the_synthetic_disclosure_is_explicit():
    assert "SYNTHETIC" in SYNTHETIC_DATA_DISCLOSURE
    assert "No real fraud data" in SYNTHETIC_DATA_DISCLOSURE
    assert "not observed" in SYNTHETIC_DATA_DISCLOSURE


# --------------------------------------------------------------------------- #
# Metric definitions
# --------------------------------------------------------------------------- #
def test_detection_and_false_positive_rates_use_the_definitions_as_written():
    """Hand-checkable arithmetic at the configured threshold of 0.25.

    risky at/above threshold -> detected; benign at/above -> false positive.
    """
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.60),
        outcome("r2", RiskLabel.RISKY, 0.30),
        outcome("r3", RiskLabel.RISKY, 0.10),  # missed
        outcome("r4", RiskLabel.RISKY, 0.05),  # missed
        outcome("b1", RiskLabel.BENIGN, 0.00),
        outcome("b2", RiskLabel.BENIGN, 0.10),
        outcome("b3", RiskLabel.BENIGN, 0.40),  # false positive
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)

    assert metrics.review_threshold == 0.25
    assert metrics.risky_flagged == 2
    assert metrics.risky_missed == 2
    assert metrics.benign_flagged == 1
    assert metrics.risk_detection_rate == pytest.approx(0.5)
    assert metrics.false_negative_rate == pytest.approx(0.5)
    assert metrics.false_positive_rate == pytest.approx(1 / 3)
    assert metrics.missed_risky_scenarios == ["r3", "r4"]
    assert metrics.false_positive_scenarios == ["b3"]


def test_the_threshold_boundary_is_inclusive_at_the_bottom():
    """A case scoring EXACTLY the threshold is flagged, matching the band rule."""
    metrics = compute_metrics(
        [outcome("r", RiskLabel.RISKY, CONFIG.review_threshold)], config=CONFIG
    )
    assert metrics.risky_flagged == 1


def test_false_negative_rate_is_exactly_one_minus_detection():
    """Stated in the module docstring; checked rather than trusted."""
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.9),
        outcome("r2", RiskLabel.RISKY, 0.01),
        outcome("r3", RiskLabel.RISKY, 0.4),
        outcome("b1", RiskLabel.BENIGN, 0.0),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)
    assert metrics.false_negative_rate == pytest.approx(1 - metrics.risk_detection_rate)


def test_a_rate_over_an_empty_denominator_is_none_not_a_number():
    """ "No benign cases were flagged out of zero" is not a 0% false-positive
    rate, and emitting 0.0 there is how a harness prints a perfect score for a
    run that measured nothing."""
    only_risky = compute_metrics([outcome("r", RiskLabel.RISKY, 0.9)], config=CONFIG)
    assert only_risky.false_positive_rate is None
    assert only_risky.risk_detection_rate == pytest.approx(1.0)

    empty = compute_metrics([], config=CONFIG)
    assert empty.risk_detection_rate is None
    assert empty.false_positive_rate is None
    assert empty.false_negative_rate is None
    assert empty.mean_score is None
    assert empty.mean_separation is None


def test_mean_separation_reports_the_gap_between_the_halves():
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.8),
        outcome("r2", RiskLabel.RISKY, 0.6),
        outcome("b1", RiskLabel.BENIGN, 0.1),
        outcome("b2", RiskLabel.BENIGN, 0.1),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)
    assert metrics.risky_mean_score == pytest.approx(0.7)
    assert metrics.benign_mean_score == pytest.approx(0.1)
    assert metrics.mean_separation == pytest.approx(0.6)


# --------------------------------------------------------------------------- #
# Errors are excluded, never rescued
# --------------------------------------------------------------------------- #
def test_an_errored_run_is_excluded_from_every_denominator():
    """A case that did not execute proved nothing, in either direction.

    Counting it as a detection would inflate the rate; counting it as a miss
    would invent a weakness.
    """
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.9),
        outcome("r2", RiskLabel.RISKY, 0.0, error="boom"),
        outcome("b1", RiskLabel.BENIGN, 0.0),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)

    assert metrics.total_assessments == 3
    assert metrics.measured_assessments == 2
    assert metrics.errors == 1
    assert metrics.errored_scenarios == ["r2"]
    assert metrics.risky_runs == 1
    assert metrics.risk_detection_rate == pytest.approx(1.0)
    assert metrics.risky_missed == 0


def test_an_errored_run_contributes_no_latency_sample():
    """A run that never assessed took no assessment time."""
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.9),
        outcome("r2", RiskLabel.RISKY, 0.0, error="boom"),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)
    assert metrics.latency.samples == 1


# --------------------------------------------------------------------------- #
# The sweep reports, it does not tune
# --------------------------------------------------------------------------- #
def test_the_sweep_always_contains_the_configured_operating_point():
    metrics = compute_metrics(
        [outcome("r", RiskLabel.RISKY, 0.9), outcome("b", RiskLabel.BENIGN, 0.0)],
        config=CONFIG,
    )
    configured = [point for point in metrics.threshold_sweep if point.configured]
    assert len(configured) == 1
    assert configured[0].threshold == pytest.approx(CONFIG.review_threshold)


def test_detection_is_non_increasing_as_the_threshold_rises():
    outcomes = [outcome(f"r{i}", RiskLabel.RISKY, i / 10) for i in range(11)]
    outcomes += [outcome(f"b{i}", RiskLabel.BENIGN, i / 20) for i in range(11)]
    metrics = compute_metrics(outcomes, config=CONFIG)

    detections = [point.detection_rate for point in metrics.threshold_sweep]
    assert detections == sorted(detections, reverse=True)
    positives = [point.false_positive_rate for point in metrics.threshold_sweep]
    assert positives == sorted(positives, reverse=True)


def test_the_headline_rates_match_the_configured_sweep_row():
    """A headline computed at a different point from the one marked configured
    would be a number measured somewhere the system never operates."""
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.6),
        outcome("r2", RiskLabel.RISKY, 0.1),
        outcome("b1", RiskLabel.BENIGN, 0.3),
        outcome("b2", RiskLabel.BENIGN, 0.0),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)
    row = next(point for point in metrics.threshold_sweep if point.configured)
    assert row.detection_rate == pytest.approx(metrics.risk_detection_rate)
    assert row.false_positive_rate == pytest.approx(metrics.false_positive_rate)


def test_a_custom_threshold_moves_the_operating_point_and_the_headline_together():
    outcomes = [
        outcome("r1", RiskLabel.RISKY, 0.6),
        outcome("r2", RiskLabel.RISKY, 0.3),
        outcome("b1", RiskLabel.BENIGN, 0.4),
    ]
    strict = compute_metrics(outcomes, config=RiskConfig(review_threshold=0.5))
    assert strict.risky_flagged == 1
    assert strict.benign_flagged == 0
    assert strict.false_positive_rate == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Determinism is checked by the harness, not assumed
# --------------------------------------------------------------------------- #
def test_identical_scores_across_iterations_report_deterministic():
    outcomes = [
        outcome("s", RiskLabel.RISKY, 0.4, iteration=1),
        outcome("s", RiskLabel.RISKY, 0.4, iteration=2),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)
    assert metrics.deterministic_across_iterations is True
    assert metrics.nondeterministic_scenarios == []


def test_drifting_scores_are_reported_by_name():
    outcomes = [
        outcome("drifter", RiskLabel.RISKY, 0.40, iteration=1),
        outcome("drifter", RiskLabel.RISKY, 0.41, iteration=2),
        outcome("stable", RiskLabel.BENIGN, 0.00, iteration=1),
        outcome("stable", RiskLabel.BENIGN, 0.00, iteration=2),
    ]
    metrics = compute_metrics(outcomes, config=CONFIG)
    assert metrics.deterministic_across_iterations is False
    assert metrics.nondeterministic_scenarios == ["drifter"]


# --------------------------------------------------------------------------- #
# Percentiles
# --------------------------------------------------------------------------- #
def test_percentiles_return_an_observed_value():
    samples = [1.0, 2.0, 3.0, 4.0, 5.0]
    for fraction in (0.5, 0.95, 0.99):
        assert percentile(samples, fraction) in samples


def test_percentile_of_nothing_is_none():
    assert percentile([], 0.5) is None


def test_latency_percentiles_are_ordered():
    outcomes = [outcome(f"s{i}", RiskLabel.RISKY, 0.5) for i in range(10)]
    for index, item in enumerate(outcomes):
        outcomes[index] = item.model_copy(update={"assess_ms": float(index)})
    metrics = compute_metrics(outcomes, config=CONFIG)
    assert metrics.latency.p50_ms <= metrics.latency.p95_ms <= metrics.latency.p99_ms
    assert metrics.latency.min_ms == 0.0
    assert metrics.latency.max_ms == 9.0


# --------------------------------------------------------------------------- #
# Real runs
# --------------------------------------------------------------------------- #
async def test_a_single_scenario_runs_end_to_end():
    scenario = RISK_SCENARIOS_BY_ID["benign_low_value"]
    result = await run_scenario(scenario, iteration=1, config=CONFIG)
    assert result.error is None, result.error
    assert result.label is RiskLabel.BENIGN
    assert 0.0 <= result.score <= 1.0
    assert result.assess_ms > 0.0


async def test_a_failing_scenario_becomes_an_error_outcome_not_a_score():
    """Fabricating 0.0 for a case that did not run would be counted as a clean
    benign result or a missed detection — a number with nothing behind it."""

    async def _broken(_context):
        raise RuntimeError("scenario construction failed")

    scenario = RiskScenario(
        id="broken",
        name="broken",
        label=RiskLabel.RISKY,
        category=RiskCategory.BASELINE,
        description="deliberately raises during construction",
        build=_broken,
    )
    result = await run_scenario(scenario, iteration=1, config=CONFIG)
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert result.measured is False


async def test_the_full_corpus_evaluates_with_no_errors():
    """The corpus must actually execute; an errored case is a coverage hole."""
    report = await evaluate(iterations=1)
    assert report.metrics.errors == 0, report.metrics.errored_scenarios
    assert report.metrics.measured_assessments == len(RISK_SCENARIOS)
    assert report.scenarios_selected == len(RISK_SCENARIOS)


async def test_the_report_carries_its_disclosures_inline():
    """The qualification must not be separable from the numbers."""
    report = await evaluate(iterations=1, scenarios=RISK_SCENARIOS[:2])
    assert report.data_disclosure == SYNTHETIC_DATA_DISCLOSURE
    assert "NOT a fraud probability" in report.score_semantics
    assert report.harness_version == HARNESS_VERSION
    assert report.model_type == "DETERMINISTIC_HEURISTIC"


async def test_risky_cases_score_above_benign_ones_on_the_real_corpus():
    """The single claim the heuristic has to earn."""
    report = await evaluate(iterations=1)
    metrics = report.metrics
    assert metrics.benign_mean_score is not None
    assert metrics.risky_mean_score is not None
    assert metrics.risky_mean_score > metrics.benign_mean_score


async def test_the_real_corpus_reproduces_across_iterations():
    """Each iteration rebuilds its scenario in a fresh database, so agreement is
    a statement about construction as well as arithmetic."""
    report = await evaluate(iterations=2)
    assert report.metrics.deterministic_across_iterations is True, (
        report.metrics.nondeterministic_scenarios
    )


async def test_evaluation_rejects_a_zero_iteration_count():
    with pytest.raises(ValueError):
        await evaluate(iterations=0)


async def test_a_benign_high_value_transaction_is_not_flagged():
    """The false positive that would make the advisory layer unreadable: a
    legitimately approved purchase sitting just under the ceiling."""
    scenario = RISK_SCENARIOS_BY_ID["benign_high_value_authorized"]
    result = await run_scenario(scenario, iteration=1, config=CONFIG)
    assert result.error is None
    assert result.score < CONFIG.review_threshold
    assert result.band is RiskBand.LOW
    assert result.recommendation is RiskRecommendation.PROCEED


async def test_a_cold_start_scenario_reports_cold_start_and_scores_nothing():
    scenario = RISK_SCENARIOS_BY_ID["benign_cold_start_merchant"]
    result = await run_scenario(scenario, iteration=1, config=CONFIG)
    assert result.error is None
    assert result.cold_start is True
    assert result.history_available is False
    assert result.score == 0.0


async def test_the_compound_security_scenario_reaches_critical():
    """Two independent severe signals must saturate the scale, as claimed."""
    scenario = RISK_SCENARIOS_BY_ID["risky_compound_security_history"]
    result = await run_scenario(scenario, iteration=1, config=CONFIG)
    assert result.error is None
    assert result.band is RiskBand.CRITICAL
    assert result.recommendation is RiskRecommendation.ESCALATE


async def test_a_risky_scenario_leaves_the_deterministic_decision_untouched():
    """Every risky case is one the kernel already adjudicated; the advisory
    score sits beside that outcome and does not replace it."""
    for scenario_id in ("risky_replay_attempt", "risky_binding_failure"):
        result = await run_scenario(RISK_SCENARIOS_BY_ID[scenario_id], iteration=1, config=CONFIG)
        assert result.error is None, result.error
        assert result.policy_decision in {"ALLOW", "REQUIRE_APPROVAL", "DENY"}
        assert result.recommendation.value not in {"ALLOW", "DENY"}


# --------------------------------------------------------------------------- #
# Limitations are reported, and kept apart from the security ones
# --------------------------------------------------------------------------- #
def test_the_risk_limitations_are_distinct_from_the_phase_6_security_ones():
    """A security limitation says an attacker could do something undetected; a
    risk limitation says a number means less than it looks like. One list would
    blur that, and would also change what every Phase 6 report prints."""
    from services.attack_lab.limitations import KNOWN_LIMITATIONS
    from services.risk_engine.limitations import RISK_LIMITATIONS

    security_ids = {limitation.id for limitation in KNOWN_LIMITATIONS}
    risk_ids = {limitation.id for limitation in RISK_LIMITATIONS}
    assert security_ids.isdisjoint(risk_ids)
    assert all(rid.startswith("RL-") for rid in risk_ids)
    assert all(kid.startswith("KL-") for kid in security_ids)


def test_the_current_security_limitations_are_all_still_present():
    """C1 updates one closed replay gap without hiding the remaining limits."""
    from services.attack_lab.limitations import KNOWN_LIMITATIONS

    ids = {limitation.id for limitation in KNOWN_LIMITATIONS}
    for expected in (
        "KL-01-audit-tail-truncation",
        "KL-02-semantic-intent-infidelity",
        "KL-03-audit-canonicalization-is-weaker",
        "KL-04-no-cryptographic-user-authorization",
        "KL-05-no-cryptographic-merchant-authentication",
        "KL-06-reconciliation-trusts-a-negative-provider-answer",
        "KL-07-latency-is-harness-local",
    ):
        assert expected in ids


def test_the_absence_of_user_history_is_disclosed_as_a_limitation():
    """The most conspicuous thing a transaction-risk engine is expected to know."""
    from services.risk_engine.limitations import RISK_LIMITATIONS

    entry = next(
        limitation
        for limitation in RISK_LIMITATIONS
        if limitation.id == "RL-01-no-user-identity-no-behavioural-baseline"
    )
    assert "no user identity" in entry.detail
    assert "ABSENT rather than approximated" in entry.detail


def test_the_index_is_never_described_as_a_probability_anywhere():
    """Swept across the whole package rather than spot-checked."""
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[1] / "services/risk_engine"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        for offending in ("fraud probability", "probability of fraud", "likelihood of fraud"):
            # The phrase may only appear inside an explicit denial.
            for index in range(len(text)):
                position = text.find(offending, index)
                if position == -1:
                    break
                window = text[max(0, position - 40) : position]
                assert any(
                    negation in window for negation in ("not a ", "not an ", "never a ", "not ")
                ), f"{path.name} calls the score a {offending}"
                index = position + 1
