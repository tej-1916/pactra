"""Deterministic capability firewall.

Default-deny: a capability is permitted only if it is in `allow` and not in
`deny`. `run_privileged` is the single choke point through which any privileged
operation must pass — a principal lacking the capability can never reach the
wrapped operation, so a compromised LLM/agent cannot invoke it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from packages.schemas.capability import Capability, CapabilitySet

R = TypeVar("R")

REASON_CODE = "CAPABILITY_DENIED"


class CapabilityDenied(Exception):
    reason_code = REASON_CODE

    def __init__(self, principal: str, capability: Capability) -> None:
        super().__init__(f"{REASON_CODE}: principal '{principal}' may not '{capability.value}'")
        self.principal = principal
        self.capability = capability


def permits(capset: CapabilitySet, capability: Capability) -> bool:
    if capability in capset.deny:
        return False
    return capability in capset.allow


def enforce(capset: CapabilitySet, capability: Capability) -> None:
    if not permits(capset, capability):
        raise CapabilityDenied(capset.principal, capability)


def run_privileged(
    capset: CapabilitySet,
    capability: Capability,
    operation: Callable[..., R],
    *args: Any,
    **kwargs: Any,
) -> R:
    """Enforce `capability`, then invoke `operation`. The operation is
    unreachable if the capability is denied — enforcement happens first."""
    enforce(capset, capability)
    return operation(*args, **kwargs)
