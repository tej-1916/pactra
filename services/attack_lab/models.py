"""Typed scenario / result / finding models for the Adversarial Attack Lab.

The whole point of these types is that a result cannot be *asserted* into
existence. A scenario returns an ``Observation`` describing what it MEASURED —
which reason code the kernel produced, how many payment intents existed before
and after, whether the protected value moved — and the runner turns that into
an ``AttackResult`` with a status. No scenario decides its own status, and
nothing in this module lets one write ``blocked=True`` without the evidence
that says so travelling alongside it.

Three rules are encoded here rather than left to discipline:

* **An exception is not a block.** ``AttackStatus.ERROR`` exists so a crash can
  never be laundered into a security success. A scenario that expected
  ``AUTHORIZATION_REPLAY_DETECTED`` and got a ``TypeError`` proved nothing.
* **INCONCLUSIVE is not secure.** A scenario whose preconditions could not be
  established (no PostgreSQL server, setup raised) reports INCONCLUSIVE and is
  excluded from every rate's denominator — never counted on the safe side.
* **A benign control is a first-class scenario.** Without controls there is no
  honest false-positive rate, so ``AttackCategory.BENIGN_CONTROL`` runs through
  exactly the same runner and the same real code paths.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


class AttackCategory(str, Enum):
    """Benchmark groups. A scenario belongs to exactly one.

    ``KNOWN_LIMITATION`` is deliberately separate from every attack category:
    those scenarios demonstrate something PACTRA genuinely CANNOT detect, and
    folding them into the attack set would either inflate the block rate (if
    counted as blocked, which would be a lie) or deflate it (if counted as a
    bypass, which would misreport a documented boundary as a defect).
    """

    INPUT_TRUST = "INPUT_TRUST"
    AUTHORITY = "AUTHORITY"
    TRANSACTION = "TRANSACTION"
    PAYMENT_RELIABILITY = "PAYMENT_RELIABILITY"
    WEBHOOK = "WEBHOOK"
    AUDIT = "AUDIT"
    CONCURRENCY = "CONCURRENCY"
    BENIGN_CONTROL = "BENIGN_CONTROL"
    KNOWN_LIMITATION = "KNOWN_LIMITATION"


#: Categories whose scenarios are hostile and therefore contribute to the
#: attack block rate. Everything else is measured but scored differently.
MALICIOUS_CATEGORIES = frozenset(
    {
        AttackCategory.INPUT_TRUST,
        AttackCategory.AUTHORITY,
        AttackCategory.TRANSACTION,
        AttackCategory.PAYMENT_RELIABILITY,
        AttackCategory.WEBHOOK,
        AttackCategory.AUDIT,
        AttackCategory.CONCURRENCY,
    }
)


class Severity(str, Enum):
    """A deliberately simple ordinal scale.

    This is NOT CVSS and is never described as CVSS. CVSS is a specific vector
    with defined base metrics; publishing a number that looks like one without
    computing one would be a fabricated measurement of exactly the kind this
    phase exists to avoid.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AttackStatus(str, Enum):
    """What a run actually produced.

    ``BLOCKED``/``NOT_BLOCKED`` are the only two statuses that carry a security
    verdict. For a hostile scenario BLOCKED is the pass; for a benign control
    NOT_BLOCKED is the pass and BLOCKED is a false positive. Both are stated by
    ``AttackScenario.expected_status`` so the direction is never inferred.
    """

    #: The attack was refused by a control, with the effects to prove it.
    BLOCKED = "BLOCKED"
    #: The behaviour went through. For a hostile scenario this is a bypass.
    NOT_BLOCKED = "NOT_BLOCKED"
    #: Something unexpected raised while attacking. Proves nothing either way.
    ERROR = "ERROR"
    #: Preconditions could not be established (setup failed, backend absent).
    INCONCLUSIVE = "INCONCLUSIVE"


class Backend(str, Enum):
    """Which database a scenario needs to mean anything.

    SQLite serializes writers with a database-wide lock, so a race run there is
    refused by the database rather than by the code under test. Concurrency
    scenarios therefore declare ``POSTGRES`` and are reported as INCONCLUSIVE
    — never as blocked — when no server is reachable.
    """

    SQLITE = "SQLITE"
    POSTGRES = "POSTGRES"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    FIXED = "FIXED"
    ACCEPTED_LIMITATION = "ACCEPTED_LIMITATION"


#: Reason attached to an INCONCLUSIVE run when the declared backend is absent.
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# What a scenario returns
# --------------------------------------------------------------------------- #


class Observation(BaseModel):
    """The measurement a scenario made. NOT a verdict.

    ``blocked`` says whether the hostile action was refused; the runner decides
    what that MEANS for this scenario by comparing it against the declared
    expectation. ``observed_effects`` is where the evidence lives, and it is
    machine-readable on purpose: "blocked: true" with an effects map showing
    ``payment_intents_after == payment_intents_before`` is a claim with
    something behind it, and "blocked: true" alone is not.
    """

    model_config = ConfigDict(extra="forbid")

    blocked: bool
    reason_code: str | None = None
    #: Whether the invariant(s) this scenario targets still held afterwards.
    #: ``None`` when the scenario measured no invariant-level state.
    invariant_preserved: bool | None = None
    #: Before/after counts and other machine-readable evidence. Never secrets:
    #: no nonce, no webhook secret, no signature, no full digest.
    observed_effects: dict[str, Any] = Field(default_factory=dict)
    #: Short human-readable note explaining the measurement.
    evidence: str | None = None


class ScenarioContext(Protocol):
    """What a scenario is handed. Structural, so the runner owns construction."""

    backend: Backend

    @property
    def sessionmaker(self) -> Any: ...


SetupFn = Callable[[Any], Awaitable[Any]]
ExecuteFn = Callable[[Any, Any], Awaitable[Observation]]


# --------------------------------------------------------------------------- #
# Scenario declaration
# --------------------------------------------------------------------------- #


class AttackScenario(BaseModel):
    """One named adversarial (or benign-control) scenario.

    ``setup`` establishes the preconditions through the REAL kernel — issuing an
    authorization, running a mission, settling a payment — and ``execute``
    performs the hostile action and measures the result. The split matters for
    honesty: a failure in ``setup`` means the attack never ran (INCONCLUSIVE),
    while a failure in ``execute`` means the attack ran and something unexpected
    happened (ERROR). Collapsing them would let a broken fixture masquerade as a
    crashed attack, or worse, as a blocked one.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=160)
    category: AttackCategory
    severity: Severity
    description: str = Field(min_length=1)
    #: The invariant(s) from the test contract this scenario exercises, written
    #: in the contract's own words so a result maps back to §17 of the spec.
    target_invariants: tuple[str, ...] = Field(min_length=1)
    backend: Backend = Backend.SQLITE
    #: What a correct system produces. BLOCKED for hostile scenarios,
    #: NOT_BLOCKED for benign controls and for demonstrated known limitations.
    expected_status: AttackStatus = AttackStatus.BLOCKED
    #: The reason code the correct control should produce, where one is
    #: deterministic. ``None`` where the defence is structural (a field that
    #: does not exist cannot be rejected by name) — inventing a code for those
    #: would be inventing a measurement.
    expected_reason_code: str | None = None
    #: A CRITICAL scenario that ERRORs fails the run: an unproven critical
    #: control is not a passing one.
    critical: bool = False
    setup: SetupFn
    execute: ExecuteFn

    @property
    def is_malicious(self) -> bool:
        return self.category in MALICIOUS_CATEGORIES


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #


class AttackResult(BaseModel):
    """One execution of one scenario.

    ``duration_ms`` covers setup and attack; ``execute_ms`` covers only the
    hostile action and the enforcement that refused it. Percentiles are computed
    over ``execute_ms`` because setup cost (creating a schema, running a whole
    mission) is scenario-construction overhead, not enforcement.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    scenario_name: str
    category: AttackCategory
    severity: Severity
    target_invariants: list[str]
    backend: Backend
    run_id: str
    iteration: int = Field(ge=1)
    started_at: datetime
    duration_ms: float = Field(ge=0.0)
    execute_ms: float = Field(ge=0.0)

    status: AttackStatus
    expected_status: AttackStatus
    #: True when the hostile action was refused. ``None`` when nothing was
    #: measured because the run errored or was inconclusive.
    blocked: bool | None = None
    reason_code: str | None = None
    expected_reason_code: str | None = None
    #: True/False only when BOTH an expected and an observed code exist; None
    #: otherwise, because "no expectation" is not a match and not a mismatch.
    reason_match: bool | None = None
    invariant_preserved: bool | None = None
    observed_effects: dict[str, Any] = Field(default_factory=dict)
    evidence: str | None = None
    #: Exception type and message for an ERROR/INCONCLUSIVE run. Present so a
    #: failure is diagnosable without re-running, and short so a stack trace
    #: never lands in a shareable report.
    error: str | None = None
    critical: bool = False

    @property
    def outcome_as_expected(self) -> bool:
        return self.status == self.expected_status

    @property
    def is_malicious(self) -> bool:
        return self.category in MALICIOUS_CATEGORIES

    @property
    def is_decisive(self) -> bool:
        """Whether this run produced a security verdict at all."""
        return self.status in (AttackStatus.BLOCKED, AttackStatus.NOT_BLOCKED)


class SecurityFinding(BaseModel):
    """A real bypass, derived from an actual NOT_BLOCKED hostile run.

    Findings are never authored by hand and never invented: ``derive_findings``
    builds them from results. A run that was blocked produces no finding, and
    there is no code path that produces one from anything other than a measured
    bypass.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    scenario_id: str
    severity: Severity
    category: AttackCategory
    invariants: list[str]
    description: str
    reproduction: str
    observed_effect: dict[str, Any] = Field(default_factory=dict)
    status: FindingStatus = FindingStatus.OPEN
    occurrences: int = Field(default=1, ge=1)


class KnownLimitation(BaseModel):
    """A boundary of the claimed security contract, stated rather than hidden.

    These are NOT findings. A finding is something that should be fixed; a known
    limitation is something the current design cannot do and does not claim to
    do. Reporting the two in one list would make the honest disclosures look
    like defects and the defects look like disclosures.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    detail: str
    #: Scenario that demonstrates it, when one exists.
    demonstrated_by: str | None = None


def new_run_id() -> str:
    """A batch identifier.

    Carries NO security authority: nothing in the kernel reads it, no decision
    depends on it, and it is not a token. It exists so a report can be
    correlated with the run that produced it.
    """
    return f"attack-run-{uuid.uuid4()}"
