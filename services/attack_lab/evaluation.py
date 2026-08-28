"""The evaluation harness: repeated runs, derived findings, one report object.

WHAT REPEATING BUYS
-------------------
A single run of a deterministic scenario tells you the control held once. It
does not tell you the control holds RELIABLY — a race that resolves correctly
nine times in ten is a race that fails in production, and one iteration cannot
see the difference. So ``--iterations N`` re-runs every selected scenario in
freshly isolated state N times, and the metrics are computed across all runs
rather than across scenarios. ``bypassed_scenarios`` lists any scenario that
came back NOT_BLOCKED even once, because "usually blocked" is not blocked.

FINDINGS ARE DERIVED, NEVER AUTHORED
------------------------------------
``derive_findings`` builds a ``SecurityFinding`` only from a hostile run that
actually came back NOT_BLOCKED, and copies that run's own measured effects into
it as the evidence. There is no path in this module that produces a finding from
anything other than an observed bypass, and no path that produces one when the
attack set comes back clean. "Do not invent findings if none exist" is enforced
by there being no function that could.

Iterations run SEQUENTIALLY. Running them concurrently would let two SQLite
in-memory databases and two PostgreSQL truncations interleave, and a scenario
whose evidence is a row census cannot share a database with another scenario.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from services.attack_lab.limitations import KNOWN_LIMITATIONS
from services.attack_lab.metrics import SEVERITY_ORDER, AttackMetrics, compute_metrics
from services.attack_lab.models import (
    AttackResult,
    AttackScenario,
    AttackStatus,
    Backend,
    KnownLimitation,
    SecurityFinding,
    new_run_id,
)
from services.attack_lab.registry import ScenarioRegistry
from services.attack_lab.runner import ScenarioExecutor, resolve_scenarios

SYSTEM_NAME = "PACTRA"
#: Bumped when the scoring rules change, so two reports can be compared and a
#: difference attributed to the system rather than to the harness.
HARNESS_VERSION = "pactra-attack-lab-v1"


class AttackRunReport(BaseModel):
    """One batch: what ran, what happened, and what it measures."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    system: str = SYSTEM_NAME
    harness_version: str = HARNESS_VERSION
    iterations: int = Field(ge=1)
    scenarios_selected: int = Field(ge=0)
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0.0)
    postgres_included: bool
    #: True when at least one PostgreSQL scenario ran to a verdict. Reported
    #: separately from ``postgres_included`` because asking for PostgreSQL and
    #: getting it are different facts.
    postgres_exercised: bool
    results: list[AttackResult]
    metrics: AttackMetrics
    findings: list[SecurityFinding] = Field(default_factory=list)
    known_limitations: list[KnownLimitation] = Field(default_factory=list)

    @property
    def clean(self) -> bool:
        """True when no hostile scenario got through and no critical run failed.

        Deliberately NOT "no errors at all": an INCONCLUSIVE PostgreSQL scenario
        on a machine with no server is a gap in coverage, reported loudly, but it
        is not a security failure. A CRITICAL scenario that errored IS, because a
        critical control that could not be exercised is a critical control that
        was not proven.
        """
        return not self.findings and not self.metrics.critical_failures


def derive_findings(results: Sequence[AttackResult]) -> list[SecurityFinding]:
    """Build findings from bypasses that actually occurred. Nothing else.

    Runs of the same scenario are folded into ONE finding with an occurrence
    count: ten iterations of one bypass is one vulnerability observed ten times,
    and listing it ten times would make a single defect look like a wave of them.
    """
    by_scenario: dict[str, list[AttackResult]] = {}
    for result in results:
        if result.is_malicious and result.status is AttackStatus.NOT_BLOCKED:
            by_scenario.setdefault(result.scenario_id, []).append(result)

    findings: list[SecurityFinding] = []
    for scenario_id, runs in by_scenario.items():
        first = runs[0]
        backend_flag = (
            " --include-postgres" if first.backend is Backend.POSTGRES else " --sqlite-only"
        )
        findings.append(
            SecurityFinding(
                id=f"PACTRA-ATTACK-{scenario_id.upper().replace('_', '-')}",
                scenario_id=scenario_id,
                severity=first.severity,
                category=first.category,
                invariants=list(first.target_invariants),
                description=(
                    f"{first.scenario_name} was NOT blocked. Expected "
                    f"{first.expected_status.value}, observed "
                    f"{first.status.value}"
                    + (
                        f" (expected reason code {first.expected_reason_code}, "
                        f"observed {first.reason_code})"
                        if first.expected_reason_code
                        else ""
                    )
                    + "."
                ),
                reproduction=(
                    f"python -m services.attack_lab.run --scenario {scenario_id}{backend_flag}"
                ),
                # The bypassing run's OWN measurements, not a summary of them.
                observed_effect=dict(first.observed_effects),
                occurrences=len(runs),
            )
        )

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.scenario_id))
    return findings


async def evaluate(
    *,
    registry: ScenarioRegistry | None = None,
    scenario_ids: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    iterations: int = 1,
    include_postgres: bool = True,
    run_id: str | None = None,
) -> AttackRunReport:
    """Run the selected scenarios ``iterations`` times and measure the result."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    scenarios: list[AttackScenario] = resolve_scenarios(
        registry=registry, scenario_ids=scenario_ids, categories=categories
    )
    batch_id = run_id or new_run_id()
    started_at = datetime.now(timezone.utc)

    executor = ScenarioExecutor(include_postgres=include_postgres)
    results: list[AttackResult] = []
    try:
        for iteration in range(1, iterations + 1):
            for scenario in scenarios:
                results.append(
                    await executor.execute(scenario, run_id=batch_id, iteration=iteration)
                )
    finally:
        await executor.close()

    completed_at = datetime.now(timezone.utc)
    postgres_exercised = any(
        result.backend is Backend.POSTGRES and result.is_decisive for result in results
    )

    return AttackRunReport(
        run_id=batch_id,
        iterations=iterations,
        scenarios_selected=len(scenarios),
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        postgres_included=include_postgres,
        postgres_exercised=postgres_exercised,
        results=results,
        metrics=compute_metrics(results, iterations=iterations),
        findings=derive_findings(results),
        known_limitations=list(KNOWN_LIMITATIONS),
    )
