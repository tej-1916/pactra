"""Metric arithmetic, including the cases where a metric must refuse to exist.

The formulas are simple; what these tests actually pin down is the discipline
around them:

* ERROR and INCONCLUSIVE runs are excluded from every denominator, so a block
  rate can never be inflated by runs that proved nothing.
* A rate over an empty denominator is ``None``, never 1.0. "Zero attacks
  succeeded out of zero valid runs" is not perfect security, and emitting 1.0
  there is how a harness reports a flawless score for a run that did nothing.
* Percentiles are nearest-rank and therefore deterministic: the same multiset
  gives the same answer, and every reported value was really observed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from services.attack_lab.metrics import (
    compute_metrics,
    percentile,
)
from services.attack_lab.models import (
    AttackCategory,
    AttackResult,
    AttackStatus,
    Backend,
    Severity,
)

pytestmark = pytest.mark.attack_lab


def _result(
    *,
    scenario_id: str = "synthetic",
    category: AttackCategory = AttackCategory.TRANSACTION,
    status: AttackStatus = AttackStatus.BLOCKED,
    expected_status: AttackStatus = AttackStatus.BLOCKED,
    execute_ms: float = 1.0,
    invariant_preserved: bool | None = None,
    observed_effects: dict | None = None,
    reason_match: bool | None = None,
    severity: Severity = Severity.HIGH,
    critical: bool = False,
    iteration: int = 1,
) -> AttackResult:
    return AttackResult(
        scenario_id=scenario_id,
        scenario_name=scenario_id,
        category=category,
        severity=severity,
        target_invariants=["SYNTHETIC -> METRIC"],
        backend=Backend.SQLITE,
        run_id="test-run",
        iteration=iteration,
        started_at=datetime.now(timezone.utc),
        duration_ms=execute_ms,
        execute_ms=execute_ms,
        status=status,
        expected_status=expected_status,
        blocked=status is AttackStatus.BLOCKED
        if status.name in ("BLOCKED", "NOT_BLOCKED")
        else None,
        reason_match=reason_match,
        invariant_preserved=invariant_preserved,
        observed_effects=observed_effects or {},
        critical=critical,
    )


# --------------------------------------------------------------------------- #
# Block / success rates
# --------------------------------------------------------------------------- #
def test_block_rate_counts_only_decisive_attack_runs():
    metrics = compute_metrics(
        [
            _result(scenario_id="a", status=AttackStatus.BLOCKED),
            _result(scenario_id="b", status=AttackStatus.BLOCKED),
            _result(scenario_id="c", status=AttackStatus.NOT_BLOCKED),
            _result(scenario_id="d", status=AttackStatus.ERROR),
            _result(scenario_id="e", status=AttackStatus.INCONCLUSIVE),
        ]
    )

    # 2 blocked of 3 decisive runs — the ERROR and INCONCLUSIVE are excluded
    # from the denominator, not counted on the safe side.
    assert metrics.valid_attack_runs == 3
    assert metrics.attack_block_rate == pytest.approx(2 / 3)
    assert metrics.attack_success_rate == pytest.approx(1 / 3)
    assert metrics.errors == 1
    assert metrics.inconclusive == 1


def test_an_errored_run_is_never_counted_as_blocked():
    metrics = compute_metrics([_result(status=AttackStatus.ERROR)])
    assert metrics.attacks_blocked == 0
    assert metrics.valid_attack_runs == 0
    assert metrics.attack_block_rate is None


def test_an_inconclusive_run_is_never_counted_as_secure():
    metrics = compute_metrics([_result(status=AttackStatus.INCONCLUSIVE)])
    assert metrics.attacks_blocked == 0
    assert metrics.attack_block_rate is None
    assert metrics.inconclusive == 1


def test_a_rate_with_no_denominator_is_none_not_one():
    """The difference between 'perfect' and 'unmeasured'."""
    metrics = compute_metrics([])
    assert metrics.attack_block_rate is None
    assert metrics.attack_success_rate is None
    assert metrics.false_positive_rate is None
    assert metrics.false_negative_rate is None
    assert metrics.duplicate_payment_rate is None
    assert metrics.replay_attack_success_rate is None


# --------------------------------------------------------------------------- #
# False positive / negative
# --------------------------------------------------------------------------- #
def test_false_positive_rate_comes_from_benign_controls():
    metrics = compute_metrics(
        [
            _result(
                scenario_id="c1",
                category=AttackCategory.BENIGN_CONTROL,
                expected_status=AttackStatus.NOT_BLOCKED,
                status=AttackStatus.NOT_BLOCKED,
            ),
            _result(
                scenario_id="c2",
                category=AttackCategory.BENIGN_CONTROL,
                expected_status=AttackStatus.NOT_BLOCKED,
                status=AttackStatus.NOT_BLOCKED,
            ),
            _result(
                scenario_id="c3",
                category=AttackCategory.BENIGN_CONTROL,
                expected_status=AttackStatus.NOT_BLOCKED,
                status=AttackStatus.BLOCKED,
            ),
        ]
    )

    assert metrics.valid_control_runs == 3
    assert metrics.controls_blocked == 1
    assert metrics.false_positive_rate == pytest.approx(1 / 3)
    assert metrics.false_positive_scenarios == ["c3"]
    # Controls are not attacks and must not enter the attack denominator.
    assert metrics.attack_runs == 0


def test_false_negative_rate_equals_attack_success_rate_by_definition():
    metrics = compute_metrics(
        [
            _result(scenario_id="a", status=AttackStatus.BLOCKED),
            _result(scenario_id="b", status=AttackStatus.NOT_BLOCKED),
        ]
    )
    assert metrics.false_negative_rate == metrics.attack_success_rate == pytest.approx(0.5)


def test_false_positive_rate_is_none_without_controls():
    """FP/FN cannot be computed from attack scenarios alone."""
    metrics = compute_metrics([_result(status=AttackStatus.BLOCKED)])
    assert metrics.false_positive_rate is None
    assert metrics.false_negative_rate == 0.0


# --------------------------------------------------------------------------- #
# Replay / duplicate payment
# --------------------------------------------------------------------------- #
def test_replay_success_rate_counts_unauthorized_effects():
    metrics = compute_metrics(
        [
            _result(
                scenario_id="authorization_replay",
                status=AttackStatus.BLOCKED,
                observed_effects={"unauthorized_effect": False},
            ),
            _result(
                scenario_id="webhook_replay",
                status=AttackStatus.BLOCKED,
                observed_effects={"unauthorized_effect": True},
            ),
        ]
    )
    assert metrics.replay_attempts == 2
    assert metrics.replay_unauthorized_effects == 1
    assert metrics.replay_attack_success_rate == pytest.approx(0.5)


def test_an_unblocked_replay_counts_as_a_successful_replay():
    metrics = compute_metrics(
        [_result(scenario_id="authorization_replay", status=AttackStatus.NOT_BLOCKED)]
    )
    assert metrics.replay_attack_success_rate == 1.0


def test_duplicate_payment_rate_reads_measured_counts():
    metrics = compute_metrics(
        [
            _result(
                scenario_id="duplicate_payment",
                observed_effects={"logical_payments": 1, "provider_payments": 1},
            ),
            _result(
                scenario_id="provider_timeout_after_create",
                observed_effects={"logical_payments": 1, "provider_payments": 2},
            ),
        ]
    )
    assert metrics.duplicate_payment_attempts == 2
    assert metrics.duplicate_payment_observations == 1
    assert metrics.duplicate_payment_rate == pytest.approx(0.5)


def test_more_than_one_logical_payment_also_counts_as_a_duplicate():
    metrics = compute_metrics(
        [
            _result(
                scenario_id="duplicate_payment",
                observed_effects={"logical_payments": 2, "provider_payments": 1},
            )
        ]
    )
    assert metrics.duplicate_payment_rate == 1.0


def test_a_duplicate_scenario_that_reports_no_counts_contributes_no_numerator():
    """'We did not count' must never read as 'we counted and found none'."""
    metrics = compute_metrics([_result(scenario_id="duplicate_payment", observed_effects={})])
    assert metrics.duplicate_payment_attempts == 1
    assert metrics.duplicate_payment_observations == 0


# --------------------------------------------------------------------------- #
# Invariant preservation and reason matching
# --------------------------------------------------------------------------- #
def test_invariant_preservation_ignores_runs_that_measured_nothing():
    metrics = compute_metrics(
        [
            _result(scenario_id="a", invariant_preserved=True),
            _result(scenario_id="b", invariant_preserved=False),
            _result(scenario_id="c", invariant_preserved=None),
        ]
    )
    assert metrics.invariant_checked_runs == 2
    assert metrics.invariant_preservation_rate == pytest.approx(0.5)


def test_reason_match_rate_ignores_runs_with_no_expectation():
    metrics = compute_metrics(
        [
            _result(scenario_id="a", reason_match=True),
            _result(scenario_id="b", reason_match=False),
            _result(scenario_id="c", reason_match=None),
        ]
    )
    assert metrics.reason_code_checked_runs == 2
    assert metrics.reason_match_rate == pytest.approx(0.5)


# --------------------------------------------------------------------------- #
# Percentiles
# --------------------------------------------------------------------------- #
def test_percentiles_are_nearest_rank_and_deterministic():
    samples = [float(n) for n in range(1, 101)]
    assert percentile(samples, 0.50) == 50.0
    assert percentile(samples, 0.95) == 95.0
    assert percentile(samples, 0.99) == 99.0
    # Order of presentation cannot change the answer.
    assert percentile(list(reversed(samples)), 0.95) == 95.0


def test_percentile_always_returns_an_observed_value():
    samples = [1.0, 2.0, 100.0]
    for fraction in (0.0, 0.5, 0.95, 0.99, 1.0):
        assert percentile(samples, fraction) in samples


def test_percentile_of_nothing_is_none():
    assert percentile([], 0.5) is None


def test_percentile_of_one_sample_is_that_sample():
    assert percentile([7.5], 0.99) == 7.5


def test_latency_excludes_runs_that_never_executed():
    """A 0.0 from a run that never happened would drag every percentile down."""
    metrics = compute_metrics(
        [
            _result(scenario_id="a", status=AttackStatus.BLOCKED, execute_ms=10.0),
            _result(scenario_id="b", status=AttackStatus.INCONCLUSIVE, execute_ms=0.0),
        ]
    )
    assert metrics.latency.samples == 1
    assert metrics.latency.p50_ms == 10.0
    assert metrics.latency.min_ms == 10.0


# --------------------------------------------------------------------------- #
# Bookkeeping
# --------------------------------------------------------------------------- #
def test_known_limitation_runs_are_excluded_from_attack_rates():
    metrics = compute_metrics(
        [
            _result(scenario_id="a", status=AttackStatus.BLOCKED),
            _result(
                scenario_id="audit_tail_truncation",
                category=AttackCategory.KNOWN_LIMITATION,
                status=AttackStatus.NOT_BLOCKED,
                expected_status=AttackStatus.NOT_BLOCKED,
            ),
        ]
    )
    assert metrics.known_limitation_runs == 1
    # The limitation neither inflates nor deflates the block rate.
    assert metrics.valid_attack_runs == 1
    assert metrics.attack_block_rate == 1.0
    assert metrics.bypassed_scenarios == []


def test_a_critical_scenario_that_errors_is_a_critical_failure():
    metrics = compute_metrics(
        [_result(scenario_id="critical_one", status=AttackStatus.ERROR, critical=True)]
    )
    assert metrics.critical_failures == ["critical_one"]


def test_a_scenario_bypassed_in_any_iteration_is_listed():
    """'Usually blocked' is not blocked."""
    metrics = compute_metrics(
        [
            _result(scenario_id="flaky", status=AttackStatus.BLOCKED, iteration=1),
            _result(scenario_id="flaky", status=AttackStatus.NOT_BLOCKED, iteration=2),
            _result(scenario_id="flaky", status=AttackStatus.BLOCKED, iteration=3),
        ],
        iterations=3,
    )
    assert metrics.bypassed_scenarios == ["flaky"]
    assert metrics.attack_block_rate == pytest.approx(2 / 3)
