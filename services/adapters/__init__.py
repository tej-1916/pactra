"""PACTRA protocol / integration adapters (Phase 8).

AN ADAPTER TRANSLATES. IT NEVER BECOMES AN AUTHORITY.
-----------------------------------------------------
    EXTERNAL PROTOCOL / SYSTEM
        -> PROTOCOL-SPECIFIC ADAPTER
        -> PACTRA CANONICAL DOMAIN MODEL
        -> PROVENANCE / TAINT / AUTHORITY
        -> DETERMINISTIC SECURITY KERNEL
        -> TRANSACTION BINDING -> AUTHORIZATION -> PAYMENT EXECUTOR -> RAIL

Never:

    EXTERNAL REPRESENTATION -> PRIVILEGED EXECUTION

THE CORRECTION THIS PHASE MAKES
-------------------------------
MCP, ACP, AP2, x402 and Razorpay are not interchangeable and do not sit at the
same layer. Treating them as one thing was the v1 design's mistake. There are
five declared families, and a family is stated at registration and again at
resolution — never inferred:

    CommerceAdapter              merchant / catalog / offer semantics
    PaymentAuthorizationAdapter  external authorization INTENT -> candidate
    ToolAdapter                  tool invocation -> constrained operation
    AgentCommunicationAdapter    declared, NOT implemented (see agents/)
    PaymentRailAdapter           the Phase 4 PaymentProvider contract, documented

WHAT IS ACTUALLY IMPLEMENTED
----------------------------
Three adapters, one of which makes an external-protocol claim:

    mcp.tools-call.v1              MCP tools/call requests          PARTIAL
    pactra.commerce.v1             PACTRA's own catalog format      IMPLEMENTED
    pactra.authorization-intent.v1 PACTRA's own intent format       IMPLEMENTED

ACP, AP2 and x402 are PLANNED and no code claims otherwise.
``services/adapters/support.py`` is the machine-readable source of truth, and
two tests hold the registry and the README to it.

FOUR GUARANTEES, EACH STRUCTURAL RATHER THAN CAREFUL
----------------------------------------------------
* **Translation is not execution.** ``translate`` is a synchronous pure function
  that takes NO database session, and nothing in this package imports the
  payment executor, the authorization write path, the binding module, or the
  orchestrator. Zero provider calls, zero authorizations, zero payment intents.
* **Authority cannot rise.** ``SourceIdentity.authenticated`` is
  ``Literal[False]``, so input authority is always AGENT_PROPOSAL; every
  descriptor is capped at AGENT_PROPOSAL; ``translate`` re-checks every
  provenance entry after the adapter returns.
* **Taint survives.** Every emitted value is tainted and untrusted, re-checked
  the same way. A parser does not sanitize authority.
* **Privileged operations are unrepresentable.** ``CandidateOperationType`` has
  no privileged member and the operation->capability table's range is disjoint
  from ``PRIVILEGED_CAPABILITIES``. A tool call naming ``payment.execute`` has
  nothing to translate into.

Importing this package registers the adapters. Registration is an explicit call
below — never filesystem discovery, and never a caller-supplied class path.
"""

from __future__ import annotations

from services.adapters.authorization.pactra_intent import (
    DESCRIPTOR as PACTRA_INTENT_DESCRIPTOR,
)
from services.adapters.authorization.pactra_intent import PactraAuthorizationIntentAdapter
from services.adapters.commerce.pactra_commerce import (
    DESCRIPTOR as PACTRA_COMMERCE_DESCRIPTOR,
)
from services.adapters.commerce.pactra_commerce import PactraCommerceAdapter
from services.adapters.errors import AdapterError
from services.adapters.models import (
    AdapterDescriptor,
    AdapterEnvelope,
    AdapterFamily,
    CandidateAuthorizationRequest,
    CandidateCommerceCatalog,
    CandidateCommerceOffer,
    CandidateOperation,
    CandidateOperationType,
    SourceIdentity,
    SupportStatus,
)
from services.adapters.registry import REGISTRY, AdapterRegistry
from services.adapters.support import PROTOCOL_SUPPORT
from services.adapters.tools.mcp import DESCRIPTOR as MCP_DESCRIPTOR
from services.adapters.tools.mcp import McpToolAdapter
from services.adapters.translate import translate

#: Every adapter PACTRA has, declared once. A missing entry is a missing line
#: here, not a file that silently failed to import — the same rule the attack
#: lab's scenario registration follows, and for the same reason: a boundary that
#: vanishes while the support matrix still names it is worse than one that was
#: never claimed.
_ADAPTERS: tuple[tuple[AdapterDescriptor, object], ...] = (
    (PACTRA_COMMERCE_DESCRIPTOR, PactraCommerceAdapter()),
    (PACTRA_INTENT_DESCRIPTOR, PactraAuthorizationIntentAdapter()),
    (MCP_DESCRIPTOR, McpToolAdapter()),
)


def _register_all() -> tuple[str, ...]:
    """Idempotent under repeated imports.

    A module imported twice — a test reloading it, the CLI importing after a test
    already did — must not raise ``DuplicateAdapter`` for something already
    registered. A DIFFERENT adapter claiming a taken id still raises, which is
    the case that matters.
    """
    for descriptor, implementation in _ADAPTERS:
        if REGISTRY.has(descriptor.adapter_id):
            continue
        REGISTRY.register(descriptor, implementation)
    REGISTRY.seal()
    return tuple(descriptor.adapter_id for descriptor, _ in _ADAPTERS)


REGISTERED_ADAPTER_IDS = _register_all()

__all__ = [
    "MCP_DESCRIPTOR",
    "PACTRA_COMMERCE_DESCRIPTOR",
    "PACTRA_INTENT_DESCRIPTOR",
    "PROTOCOL_SUPPORT",
    "REGISTERED_ADAPTER_IDS",
    "REGISTRY",
    "AdapterDescriptor",
    "AdapterEnvelope",
    "AdapterError",
    "AdapterFamily",
    "AdapterRegistry",
    "CandidateAuthorizationRequest",
    "CandidateCommerceCatalog",
    "CandidateCommerceOffer",
    "CandidateOperation",
    "CandidateOperationType",
    "SourceIdentity",
    "SupportStatus",
    "translate",
]
