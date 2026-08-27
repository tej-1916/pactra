"""Capability source of truth.

Capability sets are decided by trusted application policy here — never supplied
by an agent or derived from an untrusted request. `capabilities_for` is the only
sanctioned way to obtain a principal's capabilities; any allow/deny data that
arrives on a request is irrelevant and cannot expand a principal's rights.
"""

from __future__ import annotations

from packages.schemas.capability import CapabilitySet, buyer_agent_capabilities

# Trusted, in-code registry. In later phases this may move to persistent
# application configuration, but it is always server-owned.
_REGISTRY = {
    "buyer-agent": buyer_agent_capabilities,
}


def capabilities_for(principal: str) -> CapabilitySet:
    """Return the trusted capability set for a principal. Unknown principals get
    an empty set (default-deny everything)."""
    factory = _REGISTRY.get(principal)
    if factory is None:
        return CapabilitySet(principal=principal)
    return factory(principal)
