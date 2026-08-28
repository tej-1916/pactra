"""Rendering. Prints what was measured, and says so when nothing was.

TWO RULES
---------
**A rate with no denominator prints as "n/a", never as a number.** ``None`` from
``metrics`` means nothing was measured, and formatting it as 0.0% or 100.0%
would turn an absence of evidence into a claim. Every rate is printed with the
counts it was computed from beside it, so a block rate over three runs cannot be
mistaken for one over forty.

**Failures are never below the fold.** NOT_BLOCKED, ERROR and INCONCLUSIVE runs
get their own sections, printed before the summary, whether or not anyone asked
for verbose output. A report that buries its failures is a report that will be
skimmed to the green line at the bottom.

No secret is ever rendered: no nonce, no webhook secret, no signature, no full
transaction digest. Scenarios do not put them in ``observed_effects`` and this
module does not go looking for them elsewhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from services.attack_lab.evaluation import AttackRunReport
from services.attack_lab.metrics import AttackMetrics
from services.attack_lab.models import (
    AttackCategory,
    AttackResult,
    AttackStatus,
)

_STATUS_LABEL = {
    AttackStatus.BLOCKED: "BLOCKED",
    AttackStatus.NOT_BLOCKED: "NOT BLOCKED",
    AttackStatus.ERROR: "ERROR",
    AttackStatus.INCONCLUSIVE: "INCONCLUSIVE",
}

RULE = "=" * 78
THIN = "-" * 78


def _pct(value: float | None) -> str:
    """A rate as a percentage, or ``n/a`` when there was nothing to divide by."""
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f} ms"


def _first_run_per_scenario(report: AttackRunReport) -> list[AttackResult]:
    """One representative run per scenario, in registration order.

    The per-scenario listing is about WHICH controls answered, not how many
    times. Repetition is what the metrics section is for.
    """
    seen: dict[str, AttackResult] = {}
    for result in report.results:
        seen.setdefault(result.scenario_id, result)
    return list(seen.values())


def _scenario_lines(result: AttackResult, *, worst: AttackStatus | None = None) -> list[str]:
    status = worst or result.status
    lines = [f"[{_STATUS_LABEL[status]}] {result.scenario_id}"]
    for invariant in result.target_invariants:
        lines.append(f"  invariant: {invariant}")
    if result.reason_code:
        suffix = ""
        if result.expected_reason_code and result.reason_match is False:
            suffix = f"   (expected {result.expected_reason_code})"
        lines.append(f"  reason: {result.reason_code}{suffix}")
    elif result.expected_reason_code:
        lines.append(f"  reason: none observed (expected {result.expected_reason_code})")
    if result.error:
        lines.append(f"  error: {result.error}")
    return lines


def render_text(report: AttackRunReport) -> str:
    """The human-readable report."""
    metrics = report.metrics
    out: list[str] = [
        RULE,
        "PACTRA ADVERSARIAL EVALUATION",
        RULE,
        f"run_id      {report.run_id}",
        f"harness     {report.harness_version}",
        f"started     {report.started_at.isoformat()}",
        f"iterations  {report.iterations}   scenarios {report.scenarios_selected}   "
        f"runs {metrics.total_runs}",
        f"postgres    requested={report.postgres_included} exercised={report.postgres_exercised}",
        "",
    ]

    # ---- per-scenario, grouped by benchmark category ---------------------- #
    worst_by_scenario: dict[str, AttackStatus] = {}
    for result in report.results:
        current = worst_by_scenario.get(result.scenario_id)
        # A scenario that failed in ANY iteration is shown as failed. "Usually
        # blocked" is not blocked.
        rank = {
            AttackStatus.NOT_BLOCKED: 0,
            AttackStatus.ERROR: 1,
            AttackStatus.INCONCLUSIVE: 2,
            AttackStatus.BLOCKED: 3,
        }
        if current is None or rank[result.status] < rank[current]:
            worst_by_scenario[result.scenario_id] = result.status

    for category in AttackCategory:
        rows = [r for r in _first_run_per_scenario(report) if r.category == category]
        if not rows:
            continue
        out.append(f"{category.value}")
        out.append(THIN)
        for result in rows:
            out.extend(_scenario_lines(result, worst=worst_by_scenario[result.scenario_id]))
        out.append("")

    # ---- failures first, before any summary ------------------------------- #
    out.extend(_failure_sections(report))

    # ---- metrics ----------------------------------------------------------- #
    out.append("MEASURED METRICS")
    out.append(THIN)
    out.extend(_metric_lines(metrics))
    out.append("")

    out.append("LATENCY (attack execution only; harness-local, not production)")
    out.append(THIN)
    latency = metrics.latency
    out.append(
        f"  samples {latency.samples}   p50 {_ms(latency.p50_ms)}   "
        f"p95 {_ms(latency.p95_ms)}   p99 {_ms(latency.p99_ms)}"
    )
    out.append(
        f"  min {_ms(latency.min_ms)}   max {_ms(latency.max_ms)}   mean {_ms(latency.mean_ms)}"
    )
    out.append("")

    # ---- findings and limitations, kept apart ------------------------------ #
    out.append("SECURITY FINDINGS")
    out.append(THIN)
    if not report.findings:
        out.append("  none — no malicious scenario went through in any iteration")
    for finding in report.findings:
        out.append(f"  [{finding.severity.value}] {finding.id}  (x{finding.occurrences})")
        out.append(f"    {finding.description}")
        out.append(f"    reproduce: {finding.reproduction}")
    out.append("")

    out.append("KNOWN LIMITATIONS (not findings; outside the claimed contract)")
    out.append(THIN)
    for limitation in report.known_limitations:
        demo = (
            f" [demonstrated by {limitation.demonstrated_by}]" if limitation.demonstrated_by else ""
        )
        out.append(f"  {limitation.id}: {limitation.title}{demo}")
    out.append("")

    out.append(RULE)
    out.append(
        "RESULT: "
        + (
            "no malicious scenario went through"
            if report.clean
            else "SECURITY FAILURE — see findings above"
        )
    )
    out.append(RULE)
    return "\n".join(out)


def _failure_sections(report: AttackRunReport) -> list[str]:
    """NOT_BLOCKED / ERROR / INCONCLUSIVE, always printed, always before the summary."""
    out: list[str] = []

    bypasses = [
        r for r in report.results if r.is_malicious and r.status is AttackStatus.NOT_BLOCKED
    ]
    false_positives = [
        r
        for r in report.results
        if r.category is AttackCategory.BENIGN_CONTROL and r.status is AttackStatus.BLOCKED
    ]
    errors = [r for r in report.results if r.status is AttackStatus.ERROR]
    inconclusive = [r for r in report.results if r.status is AttackStatus.INCONCLUSIVE]

    if bypasses:
        out.append("!! ATTACKS THAT WERE NOT BLOCKED")
        out.append(THIN)
        for result in bypasses:
            out.append(
                f"  {result.scenario_id} (iteration {result.iteration}, "
                f"severity {result.severity.value})"
            )
            out.append(f"    effects: {json.dumps(result.observed_effects, default=str)}")
        out.append("")

    if false_positives:
        out.append("!! BENIGN CONTROLS THAT WERE BLOCKED (false positives)")
        out.append(THIN)
        for result in false_positives:
            out.append(f"  {result.scenario_id} (iteration {result.iteration})")
            out.append(f"    reason: {result.reason_code}")
        out.append("")

    if errors:
        out.append("!! ERRORS — an exception is NOT a block; these proved nothing")
        out.append(THIN)
        for result in errors:
            out.append(f"  {result.scenario_id} (iteration {result.iteration}): {result.error}")
        out.append("")

    if inconclusive:
        out.append("!! INCONCLUSIVE — preconditions absent; NOT counted as secure")
        out.append(THIN)
        # Collapsed by scenario: a backend that is missing is missing for every
        # iteration, and printing it N times says nothing new.
        seen: dict[str, tuple[int, str | None]] = {}
        for result in inconclusive:
            count, _ = seen.get(result.scenario_id, (0, None))
            seen[result.scenario_id] = (count + 1, result.error)
        for scenario_id, (count, error) in seen.items():
            out.append(f"  {scenario_id} (x{count}): {error}")
        out.append("")

    return out


def _metric_lines(metrics: AttackMetrics) -> list[str]:
    return [
        f"  total runs                    {metrics.total_runs}",
        f"  distinct scenarios            {metrics.total_scenarios}",
        "",
        f"  attack runs                   {metrics.attack_runs}"
        f"  (decisive {metrics.valid_attack_runs})",
        f"  attacks blocked               {metrics.attacks_blocked}",
        f"  attacks NOT blocked           {metrics.attacks_not_blocked}",
        f"  errors                        {metrics.errors}",
        f"  inconclusive                  {metrics.inconclusive}",
        f"  known-limitation runs         {metrics.known_limitation_runs}"
        "  (excluded from attack rates)",
        "",
        f"  benign control runs           {metrics.control_runs}"
        f"  (decisive {metrics.valid_control_runs})",
        f"  controls correctly allowed    {metrics.controls_allowed}",
        f"  controls wrongly blocked      {metrics.controls_blocked}",
        "",
        f"  attack_block_rate             {_pct(metrics.attack_block_rate)}"
        f"   = {metrics.attacks_blocked}/{metrics.valid_attack_runs}",
        f"  attack_success_rate           {_pct(metrics.attack_success_rate)}"
        f"   = {metrics.attacks_not_blocked}/{metrics.valid_attack_runs}",
        f"  invariant_preservation_rate   {_pct(metrics.invariant_preservation_rate)}"
        f"   (over {metrics.invariant_checked_runs} runs that measured one)",
        f"  replay_attack_success_rate    {_pct(metrics.replay_attack_success_rate)}"
        f"   = {metrics.replay_unauthorized_effects}/{metrics.replay_attempts}",
        f"  duplicate_payment_rate        {_pct(metrics.duplicate_payment_rate)}"
        f"   = {metrics.duplicate_payment_observations}/{metrics.duplicate_payment_attempts}",
        f"  false_positive_rate           {_pct(metrics.false_positive_rate)}"
        f"   = {metrics.controls_blocked}/{metrics.valid_control_runs}",
        f"  false_negative_rate           {_pct(metrics.false_negative_rate)}"
        f"   = {metrics.attacks_not_blocked}/{metrics.valid_attack_runs}"
        "  (identical to attack_success_rate by definition)",
        f"  reason_match_rate             {_pct(metrics.reason_match_rate)}"
        f"   = {metrics.reason_code_matches}/{metrics.reason_code_checked_runs}",
    ]


def render_json(report: AttackRunReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=False)


def write_report(report: AttackRunReport, path: Path) -> Path:
    """Persist the JSON report. Filesystem only — Phase 6 adds no table.

    A database table for evaluation runs would be schema with no invariant
    behind it: nothing in the kernel reads these, and a migration whose only
    purpose is to look thorough is decoration.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_json(report), encoding="utf-8")
    return path
