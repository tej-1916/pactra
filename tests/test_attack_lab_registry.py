"""Registry integrity: the attack set cannot silently shrink.

These tests exist because the most dangerous failure mode of a security harness
is not a wrong answer — it is a scenario that stopped running while the report
kept saying "all attacks blocked". A renamed module, a dropped registration, an
id typo: each would reduce coverage invisibly. So the required set is asserted
by name, ids are asserted unique, and every hostile scenario is required to
declare what it is testing.
"""

from __future__ import annotations

import pytest
from services.attack_lab.models import (
    MALICIOUS_CATEGORIES,
    AttackCategory,
    AttackStatus,
    Backend,
    Severity,
)
from services.attack_lab.registry import (
    REGISTRY,
    DuplicateScenario,
    ScenarioRegistry,
    UnknownScenario,
    load_registry,
)
from services.attack_lab.scenarios import (
    PHASE6_CANONICAL_SCENARIOS,
    REQUIRED_ADAPTER_SCENARIOS,
    REQUIRED_SCENARIOS,
)

pytestmark = pytest.mark.attack_lab


def test_registry_contains_every_required_scenario():
    """All fifteen named Phase 6 scenarios are registered."""
    registry = load_registry()
    missing = {
        requirement: scenario_id
        for requirement, scenario_id in REQUIRED_SCENARIOS.items()
        if not registry.has(scenario_id)
    }
    assert not missing, f"required scenarios are not registered: {missing}"
    assert len(REQUIRED_SCENARIOS) >= 15


def test_registry_contains_every_required_phase8_adapter_scenario():
    registry = load_registry()
    missing = {
        requirement: scenario_id
        for requirement, scenario_id in REQUIRED_ADAPTER_SCENARIOS.items()
        if not registry.has(scenario_id)
    }
    assert not missing, f"required adapter scenarios are not registered: {missing}"
    assert len(REQUIRED_ADAPTER_SCENARIOS) >= 13
    assert all(
        registry.get(scenario_id).category is AttackCategory.ADAPTER
        for scenario_id in REQUIRED_ADAPTER_SCENARIOS.values()
    )


def test_phase6_canonical_baseline_is_still_exactly_47_original_scenarios():
    registry = load_registry()
    assert len(PHASE6_CANONICAL_SCENARIOS) == 47
    assert len(set(PHASE6_CANONICAL_SCENARIOS)) == 47
    scenarios = [registry.get(scenario_id) for scenario_id in PHASE6_CANONICAL_SCENARIOS]
    assert sum(s.category in MALICIOUS_CATEGORIES for s in scenarios) == 36
    assert sum(s.category is AttackCategory.BENIGN_CONTROL for s in scenarios) == 10
    assert sum(s.category is AttackCategory.KNOWN_LIMITATION for s in scenarios) == 1
    assert all(s.category is not AttackCategory.ADAPTER for s in scenarios)


def test_at_least_fifteen_malicious_scenarios_exist():
    registry = load_registry()
    malicious = [s for s in registry.list() if s.category in MALICIOUS_CATEGORIES]
    assert len(malicious) >= 15, f"only {len(malicious)} malicious scenarios registered"


def test_benign_controls_exist():
    """Without controls there is no honest false-positive rate."""
    registry = load_registry()
    controls = registry.list(category=AttackCategory.BENIGN_CONTROL)
    assert len(controls) >= 8, f"only {len(controls)} benign controls registered"


def test_every_scenario_id_is_unique():
    registry = load_registry()
    ids = registry.ids()
    assert len(ids) == len(set(ids))


def test_registering_a_duplicate_id_raises():
    """A silently overwritten scenario is one attack that stopped running."""
    registry = ScenarioRegistry()
    scenario = load_registry().get("authorization_replay")
    registry.register(scenario)
    with pytest.raises(DuplicateScenario):
        registry.register(scenario)


def test_unknown_scenario_raises():
    with pytest.raises(UnknownScenario):
        load_registry().get("no_such_scenario")


def test_every_malicious_scenario_declares_an_invariant():
    """A scenario that names no invariant is a scenario nobody can score."""
    for scenario in load_registry().list():
        if scenario.category not in MALICIOUS_CATEGORIES:
            continue
        assert scenario.target_invariants, f"{scenario.id} declares no invariant"
        for invariant in scenario.target_invariants:
            assert invariant.strip()
            assert "->" in invariant, (
                f"{scenario.id} invariant {invariant!r} is not stated as a rule"
            )


def test_every_scenario_declares_a_description_and_severity():
    for scenario in load_registry().list():
        assert len(scenario.description) > 40, f"{scenario.id} has a stub description"
        assert isinstance(scenario.severity, Severity)


def test_malicious_scenarios_expect_blocked_and_controls_expect_allowed():
    """The scoring direction is declared, never inferred at scoring time."""
    for scenario in load_registry().list():
        if scenario.category in MALICIOUS_CATEGORIES:
            assert scenario.expected_status is AttackStatus.BLOCKED, scenario.id
        elif scenario.category is AttackCategory.BENIGN_CONTROL:
            assert scenario.expected_status is AttackStatus.NOT_BLOCKED, scenario.id


def test_known_limitations_are_not_counted_as_attacks():
    """A demonstrated limitation must never inflate or deflate the block rate."""
    registry = load_registry()
    limitations = registry.list(category=AttackCategory.KNOWN_LIMITATION)
    assert limitations, "the tail-truncation limitation should be demonstrated"
    for scenario in limitations:
        assert scenario.category not in MALICIOUS_CATEGORIES
        assert scenario.expected_status is AttackStatus.NOT_BLOCKED


def test_concurrency_scenarios_require_postgres():
    """SQLite cannot host these races, so they must not claim to run there."""
    registry = load_registry()
    concurrency = registry.list(category=AttackCategory.CONCURRENCY)
    assert concurrency
    for scenario in concurrency:
        assert scenario.backend is Backend.POSTGRES, scenario.id


def test_registry_import_is_idempotent():
    """Importing the scenario package twice must not raise DuplicateScenario."""
    import importlib

    import services.attack_lab.scenarios as scenarios_module

    before = len(REGISTRY)
    importlib.reload(scenarios_module)
    assert len(REGISTRY) == before
