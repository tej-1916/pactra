"""Measured metrics. Every number here is computed from executed runs.

DENOMINATORS ARE THE HONEST PART
--------------------------------
A rate is only as truthful as what it divides by. Two rules govern every
denominator in this module:

* **ERROR and INCONCLUSIVE runs are excluded from rates and reported
  separately.** A scenario that crashed produced no security verdict. Counting
  it as blocked would inflate the block rate with runs that proved nothing;
  counting it as a bypass would invent a vulnerability. It is counted as what it
  is — an unproven run — and the counts are printed next to every rate so a
  block rate computed over three of fifteen scenarios cannot look like one
  computed over fifteen.
* **A rate over an empty denominator is ``None``, never 1.0 and never 0.0.**
  "No attacks succeeded out of zero valid attack runs" is not 100% security, and
  emitting 1.0 there is how a harness ends up printing a perfect score for a run
  that did nothing.

FALSE NEGATIVE vs ATTACK SUCCESS
--------------------------------
``false_negative_rate`` and ``attack_success_rate`` are THE SAME QUANTITY under
these definitions: a false negative is malicious behaviour incorrectly allowed,
which is exactly a hostile scenario that came back NOT_BLOCKED. Both names are
reported because both are asked for, and the equality is stated here rather than
disguised by computing them from slightly different subsets to make them look
independent. ``false_positive_rate`` is genuinely different: it needs the benign
controls, which is why the controls exist.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from services.attack_lab.models import (
    AttackCategory,
    AttackResult,
    AttackStatus,
    Severity,
)

#: Scenario ids whose runs define the replay-attack denominator. Listed
#: explicitly rather than pattern-matched on the id, so renaming a scenario
#: cannot silently empty a metric's denominator.
REPLAY_SCENARIO_IDS: frozenset[str] = frozenset(
    {
        "authorization_replay",
        "pg_concurrent_authorization_consumption",
        "webhook_replay",
    }
)

#: Scenario ids whose runs define the duplicate-payment denominator.
DUPLICATE_PAYMENT_SCENARIO_IDS: frozenset[str] = frozenset(
    {
        "duplicate_payment",
        "provider_timeout_after_create",
        "pg_concurrent_same_key_payment",
        "pg_outbox_double_claim",
    }
)

#: Effect keys a duplicate-payment scenario must publish so the metric can be
#: computed from measurements rather than from the scenario's own verdict.
LOGICAL_PAYMENT_KEY = "logical_payments"
PROVIDER_PAYMENT_KEY = "provider_payments"
#: Set by a replay-category scenario when the replayed action DID produce an
#: effect it should not have.
UNAUTHORIZED_EFFECT_KEY = "unauthorized_effect"


def _rate(numerator: int, denominator: int) -> float | None:
    """A rate, or ``None`` when nothing was measured.

    Returning ``None`` rather than a number is the point: a metric with an empty
    denominator has no value, and any float placed there would be read as one.
    """
    if denominator == 0:
        return None
    return numerator / denominator


def percentile(samples: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile over a sorted copy of ``samples``.

    Nearest-rank rather than an interpolating variant: it always returns a value
    that was actually observed, so a reported p99 is a duration some run really
    took. Deterministic for a given multiset of samples, which is what makes the
    percentile assertions in the test suite meaningful.
    """
    if not samples:
        return None
    ordered = sorted(samples)
    # Nearest rank: ceil(fraction x N), clamped into [1, N]. Integer arithmetic
    # rather than math.ceil on a float, so the rank cannot shift because
    # fraction * N landed a fraction of an ULP either side of an integer.
    count = len(ordered)
    numerator = int(round(fraction * 100)) * count
    rank = -(-numerator // 100)  # ceiling division
    rank = max(1, min(count, rank))
    return ordered[rank - 1]


class LatencyMetrics(BaseModel):
    """Attack-execution latency, in milliseconds.

    HONEST SCOPE: this is how long the hostile action plus the enforcement that
    refused it took inside the harness, against an in-memory SQLite database (or
    a local PostgreSQL for the concurrency scenarios). It is NOT a production
    enforcement-latency figure and is never presented as one — there is no
    network, no connection pool, and no concurrent load here.
    """

    model_config = ConfigDict(extra="forbid")

    samples: int = Field(ge=0)
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    mean_ms: float | None = None


class CategoryMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: AttackCategory
    runs: int = Field(ge=0)
    blocked: int = Field(ge=0)
    not_blocked: int = Field(ge=0)
    errors: int = Field(ge=0)
    inconclusive: int = Field(ge=0)
    block_rate: float | None = None


class AttackMetrics(BaseModel):
    """Everything measured across one batch of runs."""

    model_config = ConfigDict(extra="forbid")

    total_runs: int = Field(ge=0)
    total_scenarios: int = Field(ge=0)
    iterations: int = Field(ge=1)

    # ---- raw counts, so every rate can be re-derived by the reader ------- #
    attack_runs: int = Field(ge=0)
    valid_attack_runs: int = Field(ge=0)
    attacks_blocked: int = Field(ge=0)
    attacks_not_blocked: int = Field(ge=0)
    control_runs: int = Field(ge=0)
    valid_control_runs: int = Field(ge=0)
    controls_allowed: int = Field(ge=0)
    controls_blocked: int = Field(ge=0)
    errors: int = Field(ge=0)
    inconclusive: int = Field(ge=0)
    known_limitation_runs: int = Field(ge=0)

    # ---- rates (None where the denominator is empty) --------------------- #
    attack_block_rate: float | None = None
    attack_success_rate: float | None = None
    invariant_preservation_rate: float | None = None
    replay_attack_success_rate: float | None = None
    duplicate_payment_rate: float | None = None
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    reason_match_rate: float | None = None

    # ---- denominators, printed beside the rates -------------------------- #
    invariant_checked_runs: int = Field(ge=0)
    replay_attempts: int = Field(ge=0)
    replay_unauthorized_effects: int = Field(ge=0)
    duplicate_payment_attempts: int = Field(ge=0)
    duplicate_payment_observations: int = Field(ge=0)
    reason_code_checked_runs: int = Field(ge=0)
    reason_code_matches: int = Field(ge=0)

    latency: LatencyMetrics
    by_category: list[CategoryMetrics] = Field(default_factory=list)
    #: Ids of hostile scenarios that came back NOT_BLOCKED at least once.
    bypassed_scenarios: list[str] = Field(default_factory=list)
    #: Ids of benign controls that were blocked at least once.
    false_positive_scenarios: list[str] = Field(default_factory=list)
    errored_scenarios: list[str] = Field(default_factory=list)
    inconclusive_scenarios: list[str] = Field(default_factory=list)
    critical_failures: list[str] = Field(default_factory=list)


def _latency(results: Sequence[AttackResult]) -> LatencyMetrics:
    """Percentiles over decisive runs only.

    A run that never executed contributes a 0.0 duration, and including those
    would drag every percentile toward zero — reporting speed the enforcement
    path never achieved.
    """
    samples = [r.execute_ms for r in results if r.is_decisive]
    if not samples:
        return LatencyMetrics(samples=0)
    return LatencyMetrics(
        samples=len(samples),
        p50_ms=percentile(samples, 0.50),
        p95_ms=percentile(samples, 0.95),
        p99_ms=percentile(samples, 0.99),
        min_ms=min(samples),
        max_ms=max(samples),
        mean_ms=sum(samples) / len(samples),
    )


def _by_category(results: Sequence[AttackResult]) -> list[CategoryMetrics]:
    ordered: list[CategoryMetrics] = []
    for category in AttackCategory:
        runs = [r for r in results if r.category == category]
        if not runs:
            continue
        blocked = sum(r.status is AttackStatus.BLOCKED for r in runs)
        not_blocked = sum(r.status is AttackStatus.NOT_BLOCKED for r in runs)
        ordered.append(
            CategoryMetrics(
                category=category,
                runs=len(runs),
                blocked=blocked,
                not_blocked=not_blocked,
                errors=sum(r.status is AttackStatus.ERROR for r in runs),
                inconclusive=sum(r.status is AttackStatus.INCONCLUSIVE for r in runs),
                block_rate=_rate(blocked, blocked + not_blocked),
            )
        )
    return ordered


def _duplicate_payment_counts(results: Sequence[AttackResult]) -> tuple[int, int]:
    """(attempts, observations of more than one payment).

    An attempt counts only when the run was decisive AND actually published the
    counts, because "no duplicate observed" must mean "we counted and found
    one", never "the scenario did not report". A decisive run in this set that
    omits both keys is treated as an attempt with no observation — visible in
    the denominator, contributing nothing to the numerator it cannot support.
    """
    attempts = 0
    duplicates = 0
    for result in results:
        if result.scenario_id not in DUPLICATE_PAYMENT_SCENARIO_IDS or not result.is_decisive:
            continue
        attempts += 1
        effects = result.observed_effects
        logical = effects.get(LOGICAL_PAYMENT_KEY)
        provider = effects.get(PROVIDER_PAYMENT_KEY)
        if (isinstance(logical, int) and logical > 1) or (
            isinstance(provider, int) and provider > 1
        ):
            duplicates += 1
    return attempts, duplicates


def _replay_counts(results: Sequence[AttackResult]) -> tuple[int, int]:
    """(replay attempts, replays that produced an unauthorized effect).

    A replay counts as successful when the scenario measured an unauthorized
    effect, or when the hostile replay simply was not blocked. Both are read
    from the record; neither is inferred from the scenario's name.
    """
    attempts = 0
    successes = 0
    for result in results:
        if result.scenario_id not in REPLAY_SCENARIO_IDS or not result.is_decisive:
            continue
        attempts += 1
        if result.observed_effects.get(UNAUTHORIZED_EFFECT_KEY) is True:
            successes += 1
        elif result.status is AttackStatus.NOT_BLOCKED:
            successes += 1
    return attempts, successes


def compute_metrics(results: Sequence[AttackResult], *, iterations: int = 1) -> AttackMetrics:
    """Fold a batch of executed runs into measured metrics."""
    attack_runs = [r for r in results if r.is_malicious]
    control_runs = [r for r in results if r.category is AttackCategory.BENIGN_CONTROL]
    limitation_runs = [r for r in results if r.category is AttackCategory.KNOWN_LIMITATION]

    valid_attacks = [r for r in attack_runs if r.is_decisive]
    blocked = sum(r.status is AttackStatus.BLOCKED for r in valid_attacks)
    not_blocked = sum(r.status is AttackStatus.NOT_BLOCKED for r in valid_attacks)

    valid_controls = [r for r in control_runs if r.is_decisive]
    controls_blocked = sum(r.status is AttackStatus.BLOCKED for r in valid_controls)
    controls_allowed = sum(r.status is AttackStatus.NOT_BLOCKED for r in valid_controls)

    # Invariant preservation spans attacks AND controls: an invariant that only
    # holds while nothing legitimate is happening is not an invariant.
    invariant_runs = [r for r in results if r.invariant_preserved is not None]
    invariant_held = sum(bool(r.invariant_preserved) for r in invariant_runs)

    reason_checked = [r for r in results if r.reason_match is not None]
    reason_matched = sum(bool(r.reason_match) for r in reason_checked)

    replay_attempts, replay_successes = _replay_counts(results)
    duplicate_attempts, duplicate_observations = _duplicate_payment_counts(results)

    attack_success = _rate(not_blocked, len(valid_attacks))

    return AttackMetrics(
        total_runs=len(results),
        total_scenarios=len({r.scenario_id for r in results}),
        iterations=iterations,
        attack_runs=len(attack_runs),
        valid_attack_runs=len(valid_attacks),
        attacks_blocked=blocked,
        attacks_not_blocked=not_blocked,
        control_runs=len(control_runs),
        valid_control_runs=len(valid_controls),
        controls_allowed=controls_allowed,
        controls_blocked=controls_blocked,
        errors=sum(r.status is AttackStatus.ERROR for r in results),
        inconclusive=sum(r.status is AttackStatus.INCONCLUSIVE for r in results),
        known_limitation_runs=len(limitation_runs),
        attack_block_rate=_rate(blocked, len(valid_attacks)),
        attack_success_rate=attack_success,
        invariant_preservation_rate=_rate(invariant_held, len(invariant_runs)),
        replay_attack_success_rate=_rate(replay_successes, replay_attempts),
        duplicate_payment_rate=_rate(duplicate_observations, duplicate_attempts),
        false_positive_rate=_rate(controls_blocked, len(valid_controls)),
        # Identical to attack_success_rate by definition; see the module
        # docstring. Reported under both names, computed once.
        false_negative_rate=attack_success,
        reason_match_rate=_rate(reason_matched, len(reason_checked)),
        invariant_checked_runs=len(invariant_runs),
        replay_attempts=replay_attempts,
        replay_unauthorized_effects=replay_successes,
        duplicate_payment_attempts=duplicate_attempts,
        duplicate_payment_observations=duplicate_observations,
        reason_code_checked_runs=len(reason_checked),
        reason_code_matches=reason_matched,
        latency=_latency(results),
        by_category=_by_category(results),
        bypassed_scenarios=sorted(
            {r.scenario_id for r in attack_runs if r.status is AttackStatus.NOT_BLOCKED}
        ),
        false_positive_scenarios=sorted(
            {r.scenario_id for r in control_runs if r.status is AttackStatus.BLOCKED}
        ),
        errored_scenarios=sorted(
            {r.scenario_id for r in results if r.status is AttackStatus.ERROR}
        ),
        inconclusive_scenarios=sorted(
            {r.scenario_id for r in results if r.status is AttackStatus.INCONCLUSIVE}
        ),
        critical_failures=sorted(
            {r.scenario_id for r in results if r.critical and r.status is not r.expected_status}
        ),
    )


#: Severity ordering for sorting findings. Not a score — an order.
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}
