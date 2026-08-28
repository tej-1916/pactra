"""``ToolAdapter`` — external tool invocation, translated into candidates.

THE WRONG SHAPE, WRITTEN OUT SO IT STAYS OBVIOUS

    external tool call  ->  ToolAdapter  ->  PaymentExecutor          WRONG

THE SHAPE THIS PACKAGE IMPLEMENTS

    external tool call
        -> ToolAdapter
        -> CandidateOperation
        -> capability firewall   (server-owned CapabilitySet, never the payload)
        -> deterministic policy
        -> transaction binding + authorization
        -> PaymentExecutor, only if all of the above permitted it

HOW ``payment.execute`` IS ANSWERED
    Not with a denial. ``CandidateOperationType`` has no privileged member, so
    a tool call naming ``payment.execute`` has nothing to translate INTO and is
    refused with ``ADAPTER_OPERATION_UNSUPPORTED``. A denial is a check somebody
    can delete in a refactor; an absent enum member is a change a reviewer sees.

    The second half is the capability table. Every operation maps to a
    non-privileged capability the buyer agent already holds, and
    ``tests/test_adapter_tools_mcp.py`` asserts the table's range is disjoint
    from ``PRIVILEGED_CAPABILITIES``. So even a mapping mistake cannot produce
    an adapter-originated operation that requires ``payment.execute``.

CONFUSED DEPUTY
    ``authorize_operation`` takes the principal from the CALLER and resolves it
    against the server-owned registry. A ``CandidateOperation`` carries no
    principal of its own and no capability set, so the fact that a trusted,
    registered adapter produced it grants the CALLER nothing. Adapter
    implementation trust and caller authority are different things, and the
    signature is where they are kept apart.
"""

from __future__ import annotations

import abc

from packages.schemas.capability import Capability

from services.adapters.models import (
    AdapterDescriptor,
    AdapterFamily,
    CandidateOperation,
    SourceIdentity,
)
from services.adapters.translation import TranslationResult
from services.security_kernel.capability import enforce
from services.security_kernel.capability_registry import capabilities_for

FAMILY = AdapterFamily.TOOL


class ToolAdapter(abc.ABC):
    """Base class for every tool-protocol adapter."""

    descriptor: AdapterDescriptor

    @property
    def family(self) -> AdapterFamily:
        return FAMILY

    @abc.abstractmethod
    def translate_payload(
        self,
        payload: object,
        *,
        source: SourceIdentity,
        protocol_version: str,
    ) -> TranslationResult[CandidateOperation]:
        """Parse one external tool invocation into a candidate operation."""
        raise NotImplementedError


def required_capability(operation: CandidateOperation) -> Capability:
    """The capability this candidate needs, from the server-owned table."""
    return operation.required_capability


def authorize_operation(operation: CandidateOperation, *, principal: str) -> Capability:
    """Enforce the candidate's capability against a principal's SERVER-OWNED set.

    The principal is named by the trusted caller and resolved through
    ``capabilities_for``; nothing in the candidate contributes to it. An unknown
    principal resolves to an empty set and is denied everything, which is the
    default-deny the capability registry already guarantees.

    Returns the capability that was enforced, so a caller can log what it
    checked. Raises ``CapabilityDenied`` otherwise — the same exception the
    orchestrator's own ``payment.propose`` check raises, from the same module.
    """
    capability = operation.required_capability
    enforce(capabilities_for(principal), capability)
    return capability


__all__ = [
    "FAMILY",
    "CandidateOperation",
    "ToolAdapter",
    "authorize_operation",
    "required_capability",
]
