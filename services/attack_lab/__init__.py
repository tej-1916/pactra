"""PACTRA Adversarial Attack Lab (Phase 6).

Runs real adversarial scenarios through real PACTRA code paths, records typed
results, and computes measured metrics. Nothing here reports a number it did not
observe, and nothing here can relax a control: scenarios construct hostile
INPUTS and call the same entry points production calls.

    python -m services.attack_lab.run --list
    python -m services.attack_lab.run --all
    python -m services.attack_lab.run --all --iterations 10 --json

This is DEVELOPER TOOLING. It is deliberately not wired into the FastAPI app:
an HTTP endpoint that executes attacks is an HTTP endpoint that creates
authorizations and payments, and Phase 6 does not add one.
"""

from __future__ import annotations

from services.attack_lab.models import (
    AttackCategory,
    AttackResult,
    AttackScenario,
    AttackStatus,
    Backend,
    KnownLimitation,
    Observation,
    SecurityFinding,
    Severity,
)
from services.attack_lab.registry import REGISTRY, load_registry

__all__ = [
    "REGISTRY",
    "AttackCategory",
    "AttackResult",
    "AttackScenario",
    "AttackStatus",
    "Backend",
    "KnownLimitation",
    "Observation",
    "SecurityFinding",
    "Severity",
    "load_registry",
]
