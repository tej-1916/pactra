"""Scenario execution: isolation, timing, and the fail-closed status rules.

THE STATUS RULES ARE THE WHOLE MODULE
------------------------------------
Everything else here is plumbing. These four rules are the contract:

1. ``setup`` raised          -> INCONCLUSIVE. The attack never ran.
2. declared backend absent   -> INCONCLUSIVE (``BACKEND_UNAVAILABLE``).
3. ``execute`` raised        -> ERROR. An unexpected exception is not a block:
   "expected AUTHORIZATION_REPLAY_DETECTED, got a TypeError" is a scenario that
   proved nothing, and recording it as a success would be the exact fabrication
   this phase exists to prevent.
4. ``execute`` returned      -> BLOCKED if the hostile action was refused,
   NOT_BLOCKED if it went through. The scenario reports what it MEASURED; the
   direction that counts as correct comes from ``expected_status``.

A benign control uses the same four rules. Its ``expected_status`` is
NOT_BLOCKED, so a control that comes back BLOCKED is a false positive and is
counted as one, not quietly re-labelled.

TIMING
------
``time.perf_counter_ns`` — monotonic, unaffected by wall-clock adjustment.
``execute_ms`` times only the hostile action and the enforcement that answered
it; ``duration_ms`` adds fixture construction. Percentiles use ``execute_ms``,
because a scenario that runs a whole mission in setup would otherwise report
mission-construction cost as enforcement latency.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine

from services.attack_lab.context import (
    PostgresUnavailable,
    ScenarioContext,
    make_postgres_context,
    make_postgres_engine,
    make_sqlite_context,
    postgres_target,
)
from services.attack_lab.models import (
    BACKEND_UNAVAILABLE,
    AttackResult,
    AttackScenario,
    AttackStatus,
    Backend,
    Observation,
    new_run_id,
)
from services.attack_lab.registry import ScenarioRegistry, load_registry

#: Truncation for an exception message carried into a report. Long enough to
#: identify the failure, short enough that a stack trace or a payload dump
#: cannot ride along into a file somebody shares.
MAX_ERROR_CHARS = 300


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS]


def _ms(start_ns: int, end_ns: int) -> float:
    return (end_ns - start_ns) / 1_000_000


def _result(
    scenario: AttackScenario,
    *,
    run_id: str,
    iteration: int,
    started_at: datetime,
    duration_ms: float,
    execute_ms: float,
    status: AttackStatus,
    observation: Observation | None = None,
    error: str | None = None,
) -> AttackResult:
    """Assemble one result. The ONLY place a status becomes a record.

    ``reason_match`` is three-valued on purpose. True/False require both an
    expected code and an observed one; ``None`` means no expectation was
    declared, which is neither a match nor a mismatch and must not be averaged
    into a rate as though it were either.
    """
    observed_reason = observation.reason_code if observation else None
    expected_reason = scenario.expected_reason_code
    reason_match: bool | None = None
    if expected_reason is not None and observed_reason is not None:
        reason_match = observed_reason == expected_reason
    elif expected_reason is not None and status in (
        AttackStatus.BLOCKED,
        AttackStatus.NOT_BLOCKED,
    ):
        # A decisive run that produced no reason code where one was expected is
        # a MISMATCH, not an absence of information: the declared control did
        # not announce itself.
        reason_match = False

    return AttackResult(
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        category=scenario.category,
        severity=scenario.severity,
        target_invariants=list(scenario.target_invariants),
        backend=scenario.backend,
        run_id=run_id,
        iteration=iteration,
        started_at=started_at,
        duration_ms=duration_ms,
        execute_ms=execute_ms,
        status=status,
        expected_status=scenario.expected_status,
        blocked=observation.blocked if observation else None,
        reason_code=observed_reason,
        expected_reason_code=expected_reason,
        reason_match=reason_match,
        invariant_preserved=observation.invariant_preserved if observation else None,
        observed_effects=dict(observation.observed_effects) if observation else {},
        evidence=observation.evidence if observation else None,
        error=error,
        critical=scenario.critical,
    )


async def run_scenario(
    scenario: AttackScenario,
    context: ScenarioContext,
    *,
    run_id: str,
    iteration: int = 1,
) -> AttackResult:
    """Execute one scenario against one already-isolated context."""
    started_at = datetime.now(timezone.utc)
    total_start = time.perf_counter_ns()

    try:
        state = await scenario.setup(context)
    except Exception as exc:  # noqa: BLE001 - a failed fixture is data, not a crash
        total_end = time.perf_counter_ns()
        return _result(
            scenario,
            run_id=run_id,
            iteration=iteration,
            started_at=started_at,
            duration_ms=_ms(total_start, total_end),
            execute_ms=0.0,
            status=AttackStatus.INCONCLUSIVE,
            error=f"setup failed: {_describe(exc)}",
        )

    execute_start = time.perf_counter_ns()
    try:
        observation = await scenario.execute(context, state)
    except Exception as exc:  # noqa: BLE001 - an unexpected raise is ERROR, never BLOCKED
        execute_end = time.perf_counter_ns()
        return _result(
            scenario,
            run_id=run_id,
            iteration=iteration,
            started_at=started_at,
            duration_ms=_ms(total_start, execute_end),
            execute_ms=_ms(execute_start, execute_end),
            status=AttackStatus.ERROR,
            error=f"execute raised: {_describe(exc)}",
        )
    execute_end = time.perf_counter_ns()

    status = AttackStatus.BLOCKED if observation.blocked else AttackStatus.NOT_BLOCKED
    return _result(
        scenario,
        run_id=run_id,
        iteration=iteration,
        started_at=started_at,
        duration_ms=_ms(total_start, execute_end),
        execute_ms=_ms(execute_start, execute_end),
        status=status,
        observation=observation,
    )


def _unavailable(
    scenario: AttackScenario, *, run_id: str, iteration: int, detail: str
) -> AttackResult:
    """A scenario whose declared backend is not present.

    INCONCLUSIVE, never BLOCKED. A concurrency control that was not exercised
    must not be reported as one that was, and these results are excluded from
    every rate's denominator rather than counted on the safe side.
    """
    return _result(
        scenario,
        run_id=run_id,
        iteration=iteration,
        started_at=datetime.now(timezone.utc),
        duration_ms=0.0,
        execute_ms=0.0,
        status=AttackStatus.INCONCLUSIVE,
        error=f"{BACKEND_UNAVAILABLE}: {detail}",
    )


class ScenarioExecutor:
    """Provisions an isolated backend per run and executes scenarios on it.

    PostgreSQL is opened lazily and at most once per executor: creating a schema
    per scenario would dominate the runtime, while truncating between scenarios
    gives the same isolation. SQLite gets a brand-new in-memory database per run,
    which is both cheaper and stricter.
    """

    def __init__(self, *, include_postgres: bool = True) -> None:
        self.include_postgres = include_postgres
        self._pg_engine: AsyncEngine | None = None
        self._pg_error: str | None = None

    async def _postgres_engine(self) -> AsyncEngine:
        if self._pg_engine is not None:
            return self._pg_engine
        if self._pg_error is not None:
            raise PostgresUnavailable(self._pg_error)
        try:
            self._pg_engine = await make_postgres_engine()
        except PostgresUnavailable as exc:
            self._pg_error = str(exc) or postgres_target()
            raise
        return self._pg_engine

    async def execute(
        self, scenario: AttackScenario, *, run_id: str, iteration: int = 1
    ) -> AttackResult:
        if scenario.backend is Backend.POSTGRES:
            if not self.include_postgres:
                return _unavailable(
                    scenario,
                    run_id=run_id,
                    iteration=iteration,
                    detail="PostgreSQL scenarios were excluded from this run",
                )
            try:
                engine = await self._postgres_engine()
                context = await make_postgres_context(engine)
            except PostgresUnavailable as exc:
                return _unavailable(
                    scenario,
                    run_id=run_id,
                    iteration=iteration,
                    detail=(
                        f"no PostgreSQL server reachable at {exc}. Start one with "
                        "`docker compose -f infra/docker-compose.yml up -d` or set "
                        "PACTRA_TEST_DATABASE_URL"
                    ),
                )
            return await run_scenario(scenario, context, run_id=run_id, iteration=iteration)

        context, engine = await make_sqlite_context()
        try:
            return await run_scenario(scenario, context, run_id=run_id, iteration=iteration)
        finally:
            # Disposed unconditionally: a leaked in-memory engine per scenario
            # per iteration is how a 100-iteration run runs out of connections.
            await engine.dispose()

    async def close(self) -> None:
        if self._pg_engine is not None:
            await self._pg_engine.dispose()
            self._pg_engine = None


async def run_once(
    scenarios: Sequence[AttackScenario],
    *,
    run_id: str | None = None,
    include_postgres: bool = True,
) -> list[AttackResult]:
    """Run each scenario once, each in its own isolated state."""
    batch_id = run_id or new_run_id()
    executor = ScenarioExecutor(include_postgres=include_postgres)
    try:
        return [
            await executor.execute(scenario, run_id=batch_id, iteration=1) for scenario in scenarios
        ]
    finally:
        await executor.close()


def resolve_scenarios(
    *,
    registry: ScenarioRegistry | None = None,
    scenario_ids: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
) -> list[AttackScenario]:
    """Select scenarios by id and/or category, preserving registration order."""
    from services.attack_lab.models import AttackCategory

    reg = registry or load_registry()
    if scenario_ids:
        return [reg.get(scenario_id) for scenario_id in scenario_ids]
    if categories:
        wanted = {AttackCategory(name.upper()) for name in categories}
        return [s for s in reg.list() if s.category in wanted]
    return reg.list()
