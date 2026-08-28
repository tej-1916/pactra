"""Rendering for assessments and evaluation reports.

TWO RULES, INHERITED FROM PHASE 6 BECAUSE THEY WERE RIGHT THERE
-----------------------------------------------------------------
**A rate with no denominator prints ``n/a``.** ``None`` from the metrics means
nothing was measured; formatting it as 0% or 100% turns an absence of evidence
into a claim.

**The qualifications are not below the fold.** The synthetic-data disclosure and
the "this is an index, not a probability" statement are printed at the TOP of
every evaluation report, before a single number. A reader who skims to the
headline rate has still read them.

Nothing rendered here contains a nonce, a webhook secret, a full transaction
digest, a weight table, or a raw merchant payload. Assessments carry a truncated
digest prefix at most, and the audit payload carries factor CODES rather than
the observations behind them.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.risk_engine.evaluation import EvaluationReport, RiskMetrics
from services.risk_engine.limitations import RISK_LIMITATIONS
from services.risk_engine.models import RiskAssessment

RULE = "=" * 78
THIN = "-" * 78


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f} ms"


# --------------------------------------------------------------------------- #
# One assessment
# --------------------------------------------------------------------------- #
def render_assessment(assessment: RiskAssessment) -> str:
    """A single mission's assessment, verdict first, then the arithmetic.

    The factor column sums to ``raw_points``, and both are printed, so a reader
    can check the score rather than accept it.
    """
    lines = [
        RULE,
        f"PACTRA RISK ASSESSMENT  ({assessment.engine_version} / {assessment.model_version})",
        RULE,
        f"mission           {assessment.mission_id}",
        f"assessment        {assessment.assessment_id}",
        f"evaluated_at      {assessment.evaluated_at.isoformat()}",
        f"transaction       {assessment.transaction_digest_prefix or 'no authorization'}",
        "",
        f"risk index        {assessment.score:.4f}   ({assessment.band.value})",
        f"raw points        {assessment.raw_points:.4f} / "
        f"{assessment.saturation_points:.2f} saturation",
        f"recommendation    {assessment.recommendation.value}",
        f"score semantics   {assessment.score_semantics} — NOT a fraud probability",
        "",
        "ADVISORY ONLY. This assessment authorizes nothing, refuses nothing, and "
        "changes no policy.",
        f"deterministic policy decision: {assessment.policy_decision or 'none recorded'}"
        + (
            f"  ({', '.join(assessment.policy_reason_codes)})"
            if assessment.policy_reason_codes
            else ""
        ),
        "",
        THIN,
        "CONTRIBUTING FACTORS",
        THIN,
    ]

    if assessment.factors:
        for factor in assessment.factors:
            lines.append(f"  +{factor.contribution:.4f}  {factor.code}")
            lines.append(f"      {factor.explanation}")
            lines.append(
                f"      feature={factor.feature}  observed={factor.observed}  "
                f"weight={factor.weight:.2f}"
            )
            if factor.derived_from_untrusted_evidence:
                lines.append(
                    "      provenance: a kernel-written record OF untrusted "
                    "behaviour; the record is trusted, the behaviour was not"
                )
    else:
        lines.append("  none — every configured factor was below threshold or had no data")

    quality = assessment.data_quality
    lines += [
        "",
        THIN,
        "DATA QUALITY",
        THIN,
        f"  history_available    {quality.history_available}",
        f"  history_observations {quality.history_observations} (scope: {quality.history_scope})",
        f"  cold_start           {quality.cold_start}",
        f"  features             {quality.features_available} measured, "
        f"{quality.features_unavailable} unavailable",
        f"  audit_chain_verified {quality.audit_chain_verified}",
        "",
        THIN,
        "EXPLANATION",
        THIN,
    ]
    lines.extend(f"  {line}" for line in assessment.explanation)
    lines.append(RULE)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# An evaluation batch
# --------------------------------------------------------------------------- #
def _metric_lines(metrics: RiskMetrics) -> list[str]:
    lines = [
        THIN,
        "MEASURED METRICS",
        THIN,
        f"  assessments            {metrics.total_assessments} "
        f"({metrics.measured_assessments} measured, {metrics.errors} errored)",
        f"  benign / risky runs    {metrics.benign_runs} / {metrics.risky_runs}",
        "",
        f"  mean score             {_score(metrics.mean_score)}",
        f"  median score           {_score(metrics.median_score)}",
        f"  benign mean score      {_score(metrics.benign_mean_score)}",
        f"  risky mean score       {_score(metrics.risky_mean_score)}",
        f"  mean separation        {_score(metrics.mean_separation)}",
        "",
        f"  review threshold       {metrics.review_threshold:.2f} "
        "(the operating point the engine actually uses)",
        f"  risk detection rate    {_pct(metrics.risk_detection_rate)}   "
        f"({metrics.risky_flagged}/{metrics.risky_runs} risky cases flagged)",
        f"  false positive rate    {_pct(metrics.false_positive_rate)}   "
        f"({metrics.benign_flagged}/{metrics.benign_runs} benign cases flagged)",
        f"  false negative rate    {_pct(metrics.false_negative_rate)}   "
        f"({metrics.risky_missed}/{metrics.risky_runs} risky cases missed)",
        "",
        "  NOTE: risk_detection_rate is NOT attack_block_rate. The block rate is a",
        "  Phase 6 security guarantee about the deterministic kernel; this is a",
        "  quality measurement of an advisory heuristic over a synthetic corpus.",
    ]

    if metrics.missed_risky_scenarios:
        lines += ["", "  MISSED (risky, scored below threshold):"]
        lines += [f"    {sid}" for sid in metrics.missed_risky_scenarios]
    if metrics.false_positive_scenarios:
        lines += ["", "  FALSE POSITIVES (benign, scored at or above threshold):"]
        lines += [f"    {sid}" for sid in metrics.false_positive_scenarios]
    if metrics.errored_scenarios:
        lines += ["", "  ERRORED (excluded from every rate's denominator):"]
        lines += [f"    {sid}" for sid in metrics.errored_scenarios]

    lines += ["", THIN, "THRESHOLD SWEEP (reported, not tuned)", THIN]
    lines.append("  threshold   detection      false positives")
    for point in metrics.threshold_sweep:
        marker = "  <- configured" if point.configured else ""
        lines.append(
            f"  {point.threshold:>9.2f}   "
            f"{_pct(point.detection_rate):>7} ({point.risky_flagged}/{point.risky_total})   "
            f"{_pct(point.false_positive_rate):>7} "
            f"({point.benign_flagged}/{point.benign_total}){marker}"
        )

    lines += ["", THIN, "SCORE BY CATEGORY", THIN]
    for row in metrics.by_category:
        lines.append(
            f"  {row.category:<22} {row.label.value:<7} n={row.runs:<3} "
            f"mean={_score(row.mean_score)}  "
            f"range=[{_score(row.min_score)}, {_score(row.max_score)}]"
        )

    lines += ["", THIN, "BAND / RECOMMENDATION DISTRIBUTION", THIN]
    for band, count in sorted(metrics.band_distribution.items()):
        lines.append(f"  {band:<22} {count}")
    for recommendation, count in sorted(metrics.recommendation_distribution.items()):
        lines.append(f"  {recommendation:<22} {count}")

    latency = metrics.latency
    lines += [
        "",
        THIN,
        "ASSESSMENT LATENCY (harness-local — see KL-07)",
        THIN,
        f"  samples  {latency.samples}",
        f"  p50      {_ms(latency.p50_ms)}",
        f"  p95      {_ms(latency.p95_ms)}",
        f"  p99      {_ms(latency.p99_ms)}",
        f"  min/max  {_ms(latency.min_ms)} / {_ms(latency.max_ms)}",
        "  Scope: assess_mission only, in-process against in-memory SQLite. No",
        "  network, no connection pool, no concurrent load. Scenario construction",
        "  is excluded. This detects a regression in this harness; it is not a",
        "  deployed-enforcement figure.",
        "",
        f"  deterministic across iterations: {metrics.deterministic_across_iterations}",
    ]
    if metrics.nondeterministic_scenarios:
        lines += ["  SCENARIOS THAT DID NOT REPRODUCE:"]
        lines += [f"    {sid}" for sid in metrics.nondeterministic_scenarios]
    return lines


def render_text(report: EvaluationReport) -> str:
    """The full evaluation report. Disclosures first, numbers after."""
    lines = [
        RULE,
        "PACTRA ADVISORY RISK ENGINE — EVALUATION REPORT",
        RULE,
        f"run              {report.run_id}",
        f"engine           {report.engine_version}",
        f"model            {report.model_type} / {report.model_version}",
        f"harness          {report.harness_version}",
        f"scenarios        {report.scenarios_selected} x {report.iterations} iteration(s)",
        f"duration         {report.duration_ms:.0f} ms",
        "",
        "DATA DISCLOSURE",
        f"  DATASET_TYPE = {report.dataset_type}      LABEL_SOURCE = {report.label_source}",
        f"  {report.data_disclosure}",
        "",
        "SCORE SEMANTICS",
        f"  {report.score_semantics}",
        "",
        "ADVISORY BOUNDARY",
        "  Nothing measured here authorizes, executes, or refuses anything. The",
        "  deterministic kernel decided every one of these missions before the",
        "  risk engine was consulted, and its decisions are unchanged.",
        "",
        THIN,
        "PER-SCENARIO RESULTS",
        THIN,
        f"  {'label':<7} {'scenario':<36} {'score':>7}  {'band':<9} recommendation",
    ]

    seen: set[str] = set()
    for outcome in report.outcomes:
        if outcome.scenario_id in seen:
            continue
        seen.add(outcome.scenario_id)
        if outcome.error:
            lines.append(
                f"  {outcome.label.value:<7} {outcome.scenario_id:<36} "
                f"{'ERROR':>7}  {outcome.error}"
            )
            continue
        lines.append(
            f"  {outcome.label.value:<7} {outcome.scenario_id:<36} "
            f"{outcome.score:>7.3f}  {outcome.band.value:<9} "
            f"{outcome.recommendation.value}"
        )
        lines.append(
            f"  {'':<7} {'':<36} {'':>7}  policy={outcome.policy_decision or 'none'} "
            f"(unchanged)  factors={len(outcome.factor_codes)}"
        )

    lines.append("")
    lines.extend(_metric_lines(report.metrics))
    lines.extend(_limitation_lines())
    lines.append(RULE)
    return "\n".join(lines)


def _limitation_lines() -> list[str]:
    """Printed on every run, not filed in a document nobody opens.

    These are boundaries of the MEASUREMENT, kept separate from the Phase 6
    security limitations (KL-01..KL-07), which Phase 7 neither fixes nor
    changes. A security limitation says an attacker could do something
    undetected; a risk limitation says a number means less than it looks like it
    means. Reporting them in one list would blur the difference.
    """
    lines = [
        "",
        THIN,
        "KNOWN LIMITATIONS OF THIS MEASUREMENT (not findings)",
        THIN,
    ]
    for limitation in RISK_LIMITATIONS:
        lines.append(f"  {limitation.id}: {limitation.title}")
    lines.append(
        "  Phase 6 security limitations KL-01..KL-07 are unchanged and unfixed by Phase 7;"
    )
    lines.append("  see the attack-lab report for those.")
    return lines


def render_json(report: EvaluationReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True)


def write_report(report: EvaluationReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_json(report), encoding="utf-8")
    return path
