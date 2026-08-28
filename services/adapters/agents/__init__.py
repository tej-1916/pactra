"""``AgentCommunicationAdapter`` — DECLARED, NOT IMPLEMENTED.

There is no base class in this package and no adapter, and that is a decision
rather than an omission.

WHAT WOULD JUSTIFY ONE
    A concrete agent-to-agent protocol whose message semantics are documented
    somewhere PACTRA can read them, translated into canonical PACTRA agent
    messages that preserve source, claimed identity, trust and taint.

WHY THERE ISN'T ONE
    No such protocol requirement exists in this repository. "ACP" is named once
    in ``PACTRA_BUILD_SPEC.md`` and once in ``docs/architecture.md``, both times
    only to say it is NOT interchangeable with MCP, AP2 or x402 — and the name
    is ambiguous besides. Nothing here defines its messages, so an adapter would
    have to invent them, and inventing them is the fake integration §15 of the
    spec forbids.

    An abstract base class with no implementation would not fix that. It would
    add a file, a family listing, and the impression of coverage, while
    translating nothing. Phase 8's rule is quality over count.

WHY THE FAMILY STILL EXISTS IN THE ENUM
    ``AdapterFamily.AGENT_COMMUNICATION`` is declared so the protocol support
    matrix can type ACP's row with a family value instead of a string, and so
    the registry can REFUSE a registration into it with a reason rather than
    with a KeyError. ``tests/test_adapter_registry.py`` asserts the family holds
    no adapter, so this file cannot quietly stop being true.

    Adding one later means: define the base class here, add the family to
    ``TRANSLATING_FAMILIES`` and to ``FAMILY_BASE_CLASSES``, add the payload
    type to ``FAMILY_PAYLOAD_TYPES``, and update the support matrix. Four
    explicit edits, all visible in a diff.
"""

from __future__ import annotations

from services.adapters.models import AdapterFamily

FAMILY = AdapterFamily.AGENT_COMMUNICATION

#: Read by the CLI and by ``tests/test_adapter_registry.py``. Kept as data so
#: "not implemented" is something a report can print rather than something a
#: reader has to find in a docstring.
NOT_IMPLEMENTED_REASON = (
    "No agent-to-agent protocol is specified in this repository. ACP is named only "
    "as an example of a protocol that is NOT interchangeable with MCP, AP2 or x402, "
    "and its message semantics are documented nowhere PACTRA can read. An adapter "
    "would have to invent them."
)

__all__ = ["FAMILY", "NOT_IMPLEMENTED_REASON"]
