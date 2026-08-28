"""The risk evaluation harness. Every number here comes from an executed run.

WHAT THIS MEASURES, AND WHAT IT EMPHATICALLY DOES NOT
------------------------------------------------------
``risk_detection_rate`` is NOT ``attack_block_rate``. They answer different
questions over different corpora and are computed by different code:

    attack_block_rate    (Phase 6)  did the DETERMINISTIC KERNEL refuse a
                                    hostile action? A security guarantee.
    risk_detection_rate  (Phase 7)  did the ADVISORY layer score a case a
                                    reviewer would want to see at or above the
                                    review threshold? A quality measurement.

Conflating them is the single most misleading thing this phase could do — it
would let an advisory heuristic's accuracy be read as a security property. The
Phase 6 registry is untouched, its numbers are unchanged, and nothing in this
module can affect whether an attack is labelled BLOCKED.

DEFINITIONS, STATED BEFORE THE NUMBERS
---------------------------------------
Let ``T`` be ``RiskConfig.review_threshold`` (the score at and above which the
engine stops saying PROCEED — the operating point the system actually uses, not
one chosen to flatter a chart).

    risk_detection_rate  = RISKY  cases scoring >= T  /  all RISKY  cases
    false_positive_rate  = BENIGN cases scoring >= T  /  all BENIGN cases
    false_negative_rate  = RISKY  cases scoring <  T  /  all RISKY  cases

``false_negative_rate == 1 - risk_detection_rate`` by construction. Both are
reported because both are asked for, and the identity is stated here rather than
disguised by computing them over subtly different denominators.

A rate over an empty denominator is ``None`` and renders as ``n/a`` — never 0%
and never 100%. Same rule as Phase 6, for the same reason.

THRESHOLDS ARE SWEPT, NOT TUNED
--------------------------------
``threshold_sweep`` reports the tradeoff at several operating points so a reader
can see the shape of it. The headline rates are computed at the CONFIGURED
threshold only. Nothing in this module picks a threshold from the results, and
nothing writes one back into ``RiskConfig`` — tuning an operating point against
the corpus you then report on is how a benchmark becomes a advertisement.

LATENCY IS ASSESSMENT-ONLY
---------------------------
Timing covers ``assess_mission`` alone: feature extraction, scoring, explanation.
Scenario construction — running whole missions, seeding history, driving a
payment — is excluded, because it is corpus-building cost, not engine cost. Like
Phase 6's, these figures are harness-local: in-process, in-memory SQLite, no
network, no concurrent load (KL-07 applies unchanged).
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.attack_lab.context import make_sqlite_context
from services.risk_engine.config import (
    DEFAULT_RISK_CONFIG,
    ENGINE_VERSION,
    HEURISTIC_VERSION,
    RiskConfig,
)
from services.risk_engine.engine import assess_mission
from services.risk_engine.models import RiskBand, RiskRecommendation
from services.risk_engine.scenarios import (
    RISK_SCENARIOS,
    SYNTHETIC_DATA_DISCLOSURE,
    RiskLabel,
    RiskScenario,
)

#: Bumped when the harness's own scoring rules change, so two reports can be
#: compared and a difference attributed to the engine rather than the harness.
HARNESS_VERSION = "pactra-risk-eval-v1"

#: Operating points reported in the sweep. The configured threshold is inserted
#: automatically, so the table always contains the point the system runs at.
SWEEP_THRESHOLDS: tuple[float, ...] = (0.10, 0.25, 0.50, 0.75)


def _rate(numerator: int, denominator: int) -> float | None:
    """A rate, or ``None`` when there was nothing to divide by."""
    if denominator == 0:
        return None
    return numerator / denominator


def percentile(samples: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile. Returns a duration some run really took.

    The same implementation Phase 6 uses, restated rather than imported: the
    attack lab is a peer harness, not a library this one depends on, and a
    shared helper would couple two reports that must remain independently
    readable.
    """
    if not samples:
        return None
    ordered = sorted(samples)
    count = len(ordered)
    rank = -(-int(round(fraction * 100)) * count // 100)
    return ordered[max(1, min(count, rank)) - 1]


class ScenarioOutcome(BaseModel):
    """One assessment of one scenario. The row every metric is folded from."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_name: str
    label: RiskLabel
    category: str
    iteration: int = Field(ge=1)
    score: float = Field(ge=0.0, le=1.0)
    band: RiskBand
    recommendation: RiskRecommendation
    factor_codes: list[str] = Field(default_factory=list)
    #: The authoritative decision, carried so a reader can see that a RISKY
    #: advisory score sits beside an unchanged deterministic outcome.
    policy_decision: str | None = None
    history_available: bool
    cold_start: bool
    audit_chain_verified: bool
    #: ``assess_mission`` only. Excludes scenario construction.
    assess_ms: float = Field(ge=0.0)
    #: Set when the scenario could not be built or assessed. An errored run is
    #: excluded from every rate's denominator and reported separately — never
    #: counted as a detection and never as a miss.
    error: str | None = None

    @property
    def measured(self) -> bool:
        return self.error is None


class ThresholdPoint(BaseModel):
    """The detection/false-positive tradeoff at one operating point."""

    model_config = ConfigDict(extra="forbid")

    threshold: float
    risky_flagged: int = Field(ge=0)
    risky_total: int = Field(ge=0)
    benign_flagged: int = Field(ge=0)
    benign_total: int = Field(ge=0)
    detection_rate: float | None = None
    false_positive_rate: float | None = None
    #: True for the threshold the engine is actually configured with.
    configured: bool = False


class CategoryScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    label: RiskLabel
    runs: int = Field(ge=0)
    mean_score: float | None = None
    min_score: float | None = None
    max_score: float | None = None


class LatencyMetrics(BaseModel):
    """Assessment latency in milliseconds. Harness-local (KL-07)."""

    model_config = ConfigDict(extra="forbid")

    samples: int = Field(ge=0)
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    min_ms: float | None = None
    max_ms: float | None = None
    mean_ms: float | None = None


class RiskMetrics(BaseModel):
    """Everything measured across one batch. Raw counts beside every rate."""

    model_config = ConfigDict(extra="forbid")

    total_assessments: int = Field(ge=0)
    measured_assessments: int = Field(ge=0)
    errors: int = Field(ge=0)
    errored_scenarios: list[str] = Field(default_factory=list)

    benign_runs: int = Field(ge=0)
    risky_runs: int = Field(ge=0)

    mean_score: float | None = None
    median_score: float | None = None
    benign_mean_score: float | None = None
    risky_mean_score: float | None = None
    #: risky_mean - benign_mean. The plainest statement of whether the heuristic
    #: separates the two halves of the corpus at all.
    mean_separation: float | None = None

    review_threshold: float
    risk_detection_rate: float | None = None
    false_positive_rate: float | None = None
    false_negative_rate: float | None = None
    risky_flagged: int = Field(ge=0)
    risky_missed: int = Field(ge=0)
    benign_flagged: int = Field(ge=0)
    #: Scenario ids whose label and flagged-state disagreed at least once.
    missed_risky_scenarios: list[str] = Field(default_factory=list)
    false_positive_scenarios: list[str] = Field(default_factory=list)

    band_distribution: dict[str, int] = Field(default_factory=dict)
    recommendation_distribution: dict[str, int] = Field(default_factory=dict)
    by_category: list[CategoryScores] = Field(default_factory=list)
    threshold_sweep: list[ThresholdPoint] = Field(default_factory=list)
    latency: LatencyMetrics

    #: True when the engine produced identical scores across iterations for
    #: every scenario. Determinism is a claim this harness can check for free,
    #: so it does, rather than leaving it to a unit test alone.
    deterministic_across_iterations: bool = True
    nondeterministic_scenarios: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    """One batch of risk evaluation, with its data disclosure attached."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    system: str = "PACTRA"
    harness_version: str = HARNESS_VERSION
    engine_version: str = ENGINE_VERSION
    model_type: str
    model_version: str
    #: Machine-readable disclosure. Pinned literals rather than free text so a
    #: consumer parsing the JSON cannot miss them, and so neither can be
    #: quietly changed to imply observed real-world labels.
    dataset_type: Literal["SYNTHETIC"] = "SYNTHETIC"
    label_source: Literal["AUTHORED"] = "AUTHORED"
    #: Human-readable form of the same disclosure. Carried on the report itself
    #: so it cannot be separated from the numbers it qualifies.
    data_disclosure: str = SYNTHETIC_DATA_DISCLOSURE
    score_semantics: str = (
        "Scores are a normalized risk index in [0,1], NOT a fraud probability. "
        "No calibration data exists to support a probabilistic reading."
    )
    iterations: int = Field(ge=1)
    scenarios_selected: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0.0)
    outcomes: list[ScenarioOutcome]
    metrics: RiskMetrics


def _latency(outcomes: Sequence[ScenarioOutcome]) -> LatencyMetrics:
    samples = [o.assess_ms for o in outcomes if o.measured]
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


def _sweep(outcomes: Sequence[ScenarioOutcome], *, configured: float) -> list[ThresholdPoint]:
    """The tradeoff at each operating point, configured one included and marked."""
    risky = [o for o in outcomes if o.measured and o.label is RiskLabel.RISKY]
    benign = [o for o in outcomes if o.measured and o.label is RiskLabel.BENIGN]
    thresholds = sorted({*SWEEP_THRESHOLDS, configured})
    points: list[ThresholdPoint] = []
    for threshold in thresholds:
        risky_hit = sum(o.score >= threshold for o in risky)
        benign_hit = sum(o.score >= threshold for o in benign)
        points.append(
            ThresholdPoint(
                threshold=threshold,
                risky_flagged=risky_hit,
                risky_total=len(risky),
                benign_flagged=benign_hit,
                benign_total=len(benign),
                detection_rate=_rate(risky_hit, len(risky)),
                false_positive_rate=_rate(benign_hit, len(benign)),
                configured=abs(threshold - configured) < 1e-12,
            )
        )
    return points


def _by_category(outcomes: Sequence[ScenarioOutcome]) -> list[CategoryScores]:
    grouped: dict[tuple[str, RiskLabel], list[float]] = {}
    for outcome in outcomes:
        if not outcome.measured:
            continue
        grouped.setdefault((outcome.category, outcome.label), []).append(outcome.score)
    return [
        CategoryScores(
            category=category,
            label=label,
            runs=len(scores),
            mean_score=sum(scores) / len(scores),
            min_score=min(scores),
            max_score=max(scores),
        )
        for (category, label), scores in sorted(grouped.items(), key=lambda kv: kv[0][0])
    ]


def _determinism(outcomes: Sequence[ScenarioOutcome]) -> tuple[bool, list[str]]:
    """Did every scenario score identically on every iteration?

    Checked over the whole batch rather than trusted. Each iteration rebuilds
    its scenario in a fresh database, so agreement across iterations is a
    stronger statement than re-scoring one fixed mission twice: it says the
    CONSTRUCTION is reproducible too, not just the arithmetic.
    """
    scores: dict[str, set[float]] = {}
    for outcome in outcomes:
        if outcome.measured:
            scores.setdefault(outcome.scenario_id, set()).add(round(outcome.score, 9))
    drifting = sorted(sid for sid, values in scores.items() if len(values) > 1)
    return (not drifting), drifting


def compute_metrics(outcomes: Sequence[ScenarioOutcome], *, config: RiskConfig) -> RiskMetrics:
    """Fold executed assessments into measured metrics."""
    measured = [o for o in outcomes if o.measured]
    risky = [o for o in measured if o.label is RiskLabel.RISKY]
    benign = [o for o in measured if o.label is RiskLabel.BENIGN]
    threshold = config.review_threshold

    risky_flagged = sum(o.score >= threshold for o in risky)
    benign_flagged = sum(o.score >= threshold for o in benign)
    detection = _rate(risky_flagged, len(risky))

    scores = [o.score for o in measured]
    benign_mean = (sum(o.score for o in benign) / len(benign)) if benign else None
    risky_mean = (sum(o.score for o in risky) / len(risky)) if risky else None

    bands: dict[str, int] = {}
    recommendations: dict[str, int] = {}
    for outcome in measured:
        bands[outcome.band.value] = bands.get(outcome.band.value, 0) + 1
        key = outcome.recommendation.value
        recommendations[key] = recommendations.get(key, 0) + 1

    deterministic, drifting = _determinism(outcomes)

    return RiskMetrics(
        total_assessments=len(outcomes),
        measured_assessments=len(measured),
        errors=len(outcomes) - len(measured),
        errored_scenarios=sorted({o.scenario_id for o in outcomes if not o.measured}),
        benign_runs=len(benign),
        risky_runs=len(risky),
        mean_score=(sum(scores) / len(scores)) if scores else None,
        median_score=statistics.median(scores) if scores else None,
        benign_mean_score=benign_mean,
        risky_mean_score=risky_mean,
        mean_separation=(
            None if benign_mean is None or risky_mean is None else risky_mean - benign_mean
        ),
        review_threshold=threshold,
        risk_detection_rate=detection,
        false_positive_rate=_rate(benign_flagged, len(benign)),
        # Identical to 1 - detection_rate by definition; see the module
        # docstring. Computed from the same subset rather than a different one.
        false_negative_rate=_rate(len(risky) - risky_flagged, len(risky)),
        risky_flagged=risky_flagged,
        risky_missed=len(risky) - risky_flagged,
        benign_flagged=benign_flagged,
        missed_risky_scenarios=sorted({o.scenario_id for o in risky if o.score < threshold}),
        false_positive_scenarios=sorted({o.scenario_id for o in benign if o.score >= threshold}),
        band_distribution=bands,
        recommendation_distribution=recommendations,
        by_category=_by_category(measured),
        threshold_sweep=_sweep(measured, configured=threshold),
        latency=_latency(outcomes),
        deterministic_across_iterations=deterministic,
        nondeterministic_scenarios=drifting,
    )


async def run_scenario(
    scenario: RiskScenario,
    *,
    iteration: int,
    config: RiskConfig,
) -> ScenarioOutcome:
    """Build one scenario in an isolated database and assess it once.

    Isolation is per run, reusing Phase 6's ``make_sqlite_context``: a scenario
    that could see rows another scenario left behind would have its merchant
    history — the whole basis of the anomaly layer — silently polluted by its
    predecessor.

    A build or assessment failure becomes an ``error`` outcome, never a score.
    Fabricating a 0.0 for a scenario that did not run would be counted as a
    missed detection or a clean benign case, and either would be a number with
    nothing behind it.
    """
    context, engine = await make_sqlite_context()
    try:
        case = await scenario.build(context)
        async with context.sessionmaker() as session:
            start = time.perf_counter_ns()
            assessment = await assess_mission(
                session,
                case.mission_id,
                config=config,
                registry=case.registry,
                now=case.now,
            )
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        return ScenarioOutcome(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            label=scenario.label,
            category=scenario.category.value,
            iteration=iteration,
            score=assessment.score,
            band=assessment.band,
            recommendation=assessment.recommendation,
            factor_codes=[factor.code for factor in assessment.factors],
            policy_decision=assessment.policy_decision,
            history_available=assessment.data_quality.history_available,
            cold_start=assessment.data_quality.cold_start,
            audit_chain_verified=assessment.data_quality.audit_chain_verified,
            assess_ms=elapsed_ms,
        )
    except Exception as exc:  # noqa: BLE001 - a failed run is data, not a crash
        return ScenarioOutcome(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            label=scenario.label,
            category=scenario.category.value,
            iteration=iteration,
            score=0.0,
            band=RiskBand.LOW,
            recommendation=RiskRecommendation.PROCEED,
            history_available=False,
            cold_start=True,
            audit_chain_verified=False,
            assess_ms=0.0,
            error=f"{type(exc).__name__}: {exc}"[:300],
        )
    finally:
        # Disposed unconditionally: a leaked in-memory engine per scenario per
        # iteration is how a 100-iteration run runs out of connections.
        await engine.dispose()


async def evaluate(
    *,
    scenarios: Sequence[RiskScenario] | None = None,
    iterations: int = 1,
    config: RiskConfig | None = None,
    run_id: str | None = None,
) -> EvaluationReport:
    """Run the corpus ``iterations`` times and measure the result.

    Sequential on purpose: each run owns an in-memory database, and two
    concurrent runs would contend for the event loop while timing each other's
    latency.
    """
    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    settings = config or DEFAULT_RISK_CONFIG
    selected = list(scenarios if scenarios is not None else RISK_SCENARIOS)
    batch_id = run_id or f"risk-eval-{int(time.time() * 1000)}"
    started_at = datetime.now(timezone.utc)

    outcomes: list[ScenarioOutcome] = []
    for iteration in range(1, iterations + 1):
        for scenario in selected:
            outcomes.append(await run_scenario(scenario, iteration=iteration, config=settings))

    completed_at = datetime.now(timezone.utc)
    return EvaluationReport(
        run_id=batch_id,
        model_type="DETERMINISTIC_HEURISTIC",
        model_version=HEURISTIC_VERSION,
        iterations=iterations,
        scenarios_selected=len(selected),
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        outcomes=outcomes,
        metrics=compute_metrics(outcomes, config=settings),
    )
