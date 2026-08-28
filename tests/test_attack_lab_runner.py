"""Runner semantics: the fail-closed status rules.

These are the tests that make every other result in the harness trustworthy. If
an exception could be recorded as a block, or a bypass as a success, then every
"36/36 attacks blocked" line elsewhere is unfounded. So each rule is proven
against a synthetic scenario whose behaviour is known exactly:

    setup raises      -> INCONCLUSIVE   (the attack never ran)
    execute raises    -> ERROR          (an exception is NOT a block)
    blocked=True      -> BLOCKED
    blocked=False     -> NOT_BLOCKED    (for a hostile scenario, a bypass)
    backend absent    -> INCONCLUSIVE, never BLOCKED
"""

from __future__ import annotations

from typing import Any

import pytest
from services.attack_lab.models import (
    BACKEND_UNAVAILABLE,
    AttackCategory,
    AttackScenario,
    AttackStatus,
    Backend,
    Observation,
    Severity,
)
from services.attack_lab.runner import ScenarioExecutor, run_once

pytestmark = pytest.mark.attack_lab


def _scenario(
    *,
    scenario_id: str,
    setup: Any = None,
    execute: Any = None,
    category: AttackCategory = AttackCategory.TRANSACTION,
    expected_status: AttackStatus = AttackStatus.BLOCKED,
    expected_reason_code: str | None = None,
    backend: Backend = Backend.SQLITE,
    critical: bool = False,
) -> AttackScenario:
    async def default_setup(_context: Any) -> dict:
        return {}

    async def default_execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=True)

    return AttackScenario(
        id=scenario_id,
        name=f"synthetic {scenario_id}",
        category=category,
        severity=Severity.HIGH,
        description="A synthetic scenario used to prove the runner's status rules hold.",
        target_invariants=("SYNTHETIC -> RUNNER STATUS RULE",),
        backend=backend,
        expected_status=expected_status,
        expected_reason_code=expected_reason_code,
        critical=critical,
        setup=setup or default_setup,
        execute=execute or default_execute,
    )


async def test_a_blocked_attack_is_recorded_as_blocked():
    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(
            blocked=True,
            reason_code="AUTHORIZATION_REPLAY_DETECTED",
            invariant_preserved=True,
            observed_effects={"payment_intents_after": 1},
        )

    result = (
        await run_once(
            [
                _scenario(
                    scenario_id="synthetic_blocked",
                    execute=execute,
                    expected_reason_code="AUTHORIZATION_REPLAY_DETECTED",
                )
            ],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.BLOCKED
    assert result.blocked is True
    assert result.reason_match is True
    assert result.outcome_as_expected
    assert result.observed_effects == {"payment_intents_after": 1}


async def test_an_attack_that_goes_through_is_recorded_as_not_blocked():
    """A bypass must never be smoothed into anything else."""

    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(
            blocked=False,
            invariant_preserved=False,
            observed_effects={"payment_intents_after": 2},
        )

    result = (
        await run_once(
            [_scenario(scenario_id="synthetic_bypass", execute=execute)],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.NOT_BLOCKED
    assert result.blocked is False
    assert result.invariant_preserved is False
    assert not result.outcome_as_expected


async def test_an_unexpected_exception_is_error_and_never_blocked():
    """The single most important rule in the harness."""

    async def execute(_context: Any, _state: Any) -> Observation:
        raise RuntimeError("the database went away mid-attack")

    result = (
        await run_once(
            [
                _scenario(
                    scenario_id="synthetic_crash",
                    execute=execute,
                    expected_reason_code="AUTHORIZATION_REPLAY_DETECTED",
                )
            ],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.ERROR
    assert result.status is not AttackStatus.BLOCKED
    # No verdict was reached, so no verdict is recorded.
    assert result.blocked is None
    assert result.reason_code is None
    assert not result.is_decisive
    assert "RuntimeError" in (result.error or "")
    assert "the database went away" in (result.error or "")


async def test_a_failed_setup_is_inconclusive_not_error():
    """A broken fixture must not masquerade as a crashed attack."""

    async def setup(_context: Any) -> dict:
        raise ValueError("could not establish an authorized mission")

    result = (
        await run_once(
            [_scenario(scenario_id="synthetic_setup_failure", setup=setup)],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.INCONCLUSIVE
    assert result.blocked is None
    assert not result.is_decisive
    assert (result.error or "").startswith("setup failed:")
    # Nothing ran, so nothing was timed.
    assert result.execute_ms == 0.0


async def test_a_missing_backend_is_inconclusive_never_blocked():
    """A guarantee that was not exercised must not look like one that was."""
    executor = ScenarioExecutor(include_postgres=False)
    try:
        result = await executor.execute(
            _scenario(scenario_id="synthetic_pg", backend=Backend.POSTGRES),
            run_id="test-run",
        )
    finally:
        await executor.close()

    assert result.status is AttackStatus.INCONCLUSIVE
    assert result.status is not AttackStatus.BLOCKED
    assert BACKEND_UNAVAILABLE in (result.error or "")


async def test_a_reason_code_mismatch_is_visible():
    """Proving the right control stopped the attack, not merely some control."""

    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=True, reason_code="SOMETHING_ELSE_ENTIRELY")

    result = (
        await run_once(
            [
                _scenario(
                    scenario_id="synthetic_wrong_reason",
                    execute=execute,
                    expected_reason_code="TRANSACTION_BINDING_FAILURE",
                )
            ],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.BLOCKED
    assert result.reason_match is False
    assert result.reason_code == "SOMETHING_ELSE_ENTIRELY"
    assert result.expected_reason_code == "TRANSACTION_BINDING_FAILURE"


async def test_a_decisive_run_with_no_reason_code_where_one_was_expected_mismatches():
    """Silence is not agreement: the declared control did not announce itself."""

    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=True, reason_code=None)

    result = (
        await run_once(
            [
                _scenario(
                    scenario_id="synthetic_silent_control",
                    execute=execute,
                    expected_reason_code="CAPABILITY_DENIED",
                )
            ],
            include_postgres=False,
        )
    )[0]

    assert result.reason_match is False


async def test_no_expectation_means_neither_match_nor_mismatch():
    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=True, reason_code="ANYTHING")

    result = (
        await run_once(
            [_scenario(scenario_id="synthetic_no_expectation", execute=execute)],
            include_postgres=False,
        )
    )[0]

    assert result.reason_match is None


async def test_a_benign_control_that_is_allowed_matches_its_expectation():
    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=False, invariant_preserved=True)

    result = (
        await run_once(
            [
                _scenario(
                    scenario_id="synthetic_control",
                    execute=execute,
                    category=AttackCategory.BENIGN_CONTROL,
                    expected_status=AttackStatus.NOT_BLOCKED,
                )
            ],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.NOT_BLOCKED
    assert result.outcome_as_expected
    assert not result.is_malicious


async def test_a_benign_control_that_is_blocked_is_a_false_positive():
    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=True, reason_code="OVER_EAGER_POLICY")

    result = (
        await run_once(
            [
                _scenario(
                    scenario_id="synthetic_false_positive",
                    execute=execute,
                    category=AttackCategory.BENIGN_CONTROL,
                    expected_status=AttackStatus.NOT_BLOCKED,
                )
            ],
            include_postgres=False,
        )
    )[0]

    assert result.status is AttackStatus.BLOCKED
    assert not result.outcome_as_expected


async def test_each_run_gets_isolated_state():
    """Scenario N must not be able to observe what scenario N-1 left behind."""
    seen: list[int] = []

    async def execute(context: Any, _state: Any) -> Observation:
        census = await context.census()
        seen.append(census["missions"])
        await context.make_mission()
        return Observation(blocked=True, observed_effects=census)

    scenarios = [
        _scenario(scenario_id=f"synthetic_isolation_{i}", execute=execute) for i in range(3)
    ]
    await run_once(scenarios, include_postgres=False)

    assert seen == [0, 0, 0], f"state leaked between scenario runs: {seen}"


async def test_durations_are_measured_not_assumed():
    async def execute(_context: Any, _state: Any) -> Observation:
        return Observation(blocked=True)

    result = (
        await run_once(
            [_scenario(scenario_id="synthetic_timing", execute=execute)],
            include_postgres=False,
        )
    )[0]

    assert result.execute_ms > 0.0
    assert result.duration_ms >= result.execute_ms
