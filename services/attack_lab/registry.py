"""Explicit scenario registry.

Deliberately NOT filesystem discovery. Importing every module in a directory and
scraping it for scenarios means the set of attacks PACTRA claims to run depends
on which files happen to be present, and a scenario silently disappearing — a
renamed file, a failed import swallowed by a broad ``except`` — would quietly
shrink the security claim while the report still said "all attacks blocked".

So registration is a function call. A scenario that is not registered does not
run, a scenario registered twice raises at import time, and the required-set
check in ``tests/test_attack_lab_registry.py`` fails if a named scenario is
missing. Ordering is registration order, which makes a batch reproducible.
"""

from __future__ import annotations

from services.attack_lab.models import AttackCategory, AttackScenario, Backend

#: Module-level aliases so the annotations below still mean the BUILTIN list.
#: ``ScenarioRegistry.list`` shadows ``list`` inside the class body, and
#: ``-> list[...]`` there resolves to the method rather than the type.
#: The public method keeps its name — ``registry.list()`` is the documented
#: API — and the annotations reference these instead.
ScenarioList = list[AttackScenario]
IdList = list[str]


class DuplicateScenario(Exception):
    """Two scenarios claimed the same id.

    Raised eagerly at import rather than tolerated, because a silently
    overwritten scenario means one attack stopped running while the report kept
    counting a scenario with that id.
    """


class UnknownScenario(Exception):
    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"no attack scenario registered as {scenario_id!r}")
        self.scenario_id = scenario_id


class ScenarioRegistry:
    def __init__(self) -> None:
        self._scenarios: dict[str, AttackScenario] = {}

    def register(self, scenario: AttackScenario) -> AttackScenario:
        if scenario.id in self._scenarios:
            raise DuplicateScenario(f"scenario id {scenario.id!r} is already registered")
        self._scenarios[scenario.id] = scenario
        return scenario

    def get(self, scenario_id: str) -> AttackScenario:
        scenario = self._scenarios.get(scenario_id)
        if scenario is None:
            raise UnknownScenario(scenario_id)
        return scenario

    def has(self, scenario_id: str) -> bool:
        return scenario_id in self._scenarios

    def list(
        self,
        *,
        category: AttackCategory | None = None,
        backend: Backend | None = None,
    ) -> ScenarioList:
        """Registered scenarios in registration order, optionally filtered."""
        scenarios: ScenarioList = list(self._scenarios.values())
        if category is not None:
            scenarios = [s for s in scenarios if s.category == category]
        if backend is not None:
            scenarios = [s for s in scenarios if s.backend == backend]
        return scenarios

    def ids(self) -> IdList:
        return list(self._scenarios)

    def __len__(self) -> int:
        return len(self._scenarios)


#: The process-wide registry. Populated by importing
#: ``services.attack_lab.scenarios``, which is the only module that registers.
REGISTRY = ScenarioRegistry()


def register(scenario: AttackScenario) -> AttackScenario:
    return REGISTRY.register(scenario)


def load_registry() -> ScenarioRegistry:
    """Import the scenario package (idempotent) and return the registry."""
    import services.attack_lab.scenarios  # noqa: F401  (registration side effect)

    return REGISTRY
