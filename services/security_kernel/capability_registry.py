"""Capability source of truth.

Capability sets are decided by trusted application policy here — never supplied
by an agent or derived from an untrusted request. `capabilities_for` is the only
sanctioned way to obtain a principal's capabilities; any allow/deny data that
arrives on a request is irrelevant and cannot expand a principal's rights.
"""

from __future__ import annotations

from packages.schemas.capability import (
    Capability,
    CapabilitySet,
    buyer_agent_capabilities,
    payment_executor_capabilities,
    security_kernel_capabilities,
)

from services.security_kernel.capability import CapabilityDenied, enforce

# Trusted, in-code registry. In later phases this may move to persistent
# application configuration, but it is always server-owned.
_REGISTRY = {
    "buyer-agent": buyer_agent_capabilities,
    "security-kernel": security_kernel_capabilities,
    # Phase 4. Separation of duties: this is the only principal holding
    # `payment.execute`, and it is the only one denied `authorization.issue`
    # while holding it. Issuing and spending are never the same principal.
    "payment-executor": payment_executor_capabilities,
}


def capabilities_for(principal: str) -> CapabilitySet:
    """Return the trusted capability set for a principal. Unknown principals get
    an empty set (default-deny everything)."""
    factory = _REGISTRY.get(principal)
    if factory is None:
        return CapabilitySet(principal=principal)
    return factory(principal)


def enforce_registered(capset: CapabilitySet, capability: Capability) -> None:
    """Enforce against server-owned policy, never caller-supplied grants.

    ``CapabilitySet`` is a schema and can therefore be constructed by untrusted
    code.  Its ``principal`` is the lookup key; its allow/deny contents are not
    authority.  A privileged boundary accepts only the exact set the trusted
    registry defines for that principal, then enforces the requested
    capability against that authoritative set.

    Principal authentication remains the responsibility of the trusted caller
    that selects the principal (the payment worker does so internally).  This
    check prevents a buyer-agent request from adding ``payment.execute`` to its
    own payload and having a service mistake that data for a grant.
    """
    authoritative = capabilities_for(capset.principal)
    if capset != authoritative:
        raise CapabilityDenied(capset.principal, capability)
    enforce(authoritative, capability)
