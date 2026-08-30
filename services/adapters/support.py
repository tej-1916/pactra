"""The protocol support matrix. THE source of truth, not a copy of the README.

WHY THIS IS CODE AND NOT PROSE
-------------------------------
A README saying "MCP: IMPLEMENTED" beside a repository containing no MCP adapter
is the exact failure this phase exists to correct. So the matrix lives here as
data, and two tests hold everything else to it:

* ``test_support_matrix_matches_the_registry`` — every IMPLEMENTED or PARTIAL
  entry naming an adapter must resolve to an adapter actually registered under
  that id AND that family; every PLANNED entry must name no adapter and have
  none registered for its protocol. Code cannot claim more than it holds.
* ``test_readme_table_matches_the_support_matrix`` — the README's table is
  parsed and compared row by row. Documentation cannot claim more than the code.

There is no ``SUPPORTED`` status. It is the word that lets a claim mean whatever
the reader hopes; each of the four permitted statuses says something checkable.

HOW TO READ ``family=None``
---------------------------
For ACP and x402, the family itself is UNASSIGNED. That is not laziness — it is
the honest state. Assigning ``x402 -> PaymentAuthorizationAdapter`` would be a
claim about what x402 is, made from no source in this repository, and it would
be the first invented statement in a matrix whose entire purpose is to contain
none. AP2 gets a family because the build spec assigns it one; its ADAPTER is
still absent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from services.adapters.authorization.pactra_intent import (
    ADAPTER_ID as PACTRA_INTENT_ID,
)
from services.adapters.commerce.pactra_commerce import ADAPTER_ID as PACTRA_COMMERCE_ID
from services.adapters.models import AdapterFamily, SupportStatus
from services.adapters.tools.mcp import ADAPTER_ID as MCP_ID


class ProtocolSupport(BaseModel):
    """One row: what PACTRA does and does not do about one protocol or system."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: str = Field(min_length=1, max_length=80)
    #: What layer the named protocol/system actually occupies. Kept separate
    #: from ``family`` because an unassigned family must not erase what is (or
    #: is not) known about the protocol's role.
    actual_role: str = Field(min_length=1, max_length=240)
    #: ``None`` when the protocol's layer cannot be established from any source
    #: in this repository. An unassigned family is a statement; a guessed one
    #: would be a fabrication.
    family: AdapterFamily | None
    status: SupportStatus
    #: The registered adapter that implements it, when one exists.
    adapter_id: str | None = None
    #: Exactly what PACTRA supports. Never a summary that rounds upward.
    supported: str = Field(min_length=1)
    #: Exactly what it does not. Present on every row, including implemented
    #: ones, because the gaps are the part a reader is most likely to assume
    #: away.
    not_supported: str = Field(min_length=1)
    #: Why the status is what it is.
    reason: str = Field(min_length=1)
    #: Primary specification pages used for an external-protocol claim. Empty
    #: for PACTRA-native formats and for protocols left unimplemented because
    #: the repository does not ground their semantics.
    specification_sources: tuple[str, ...] = ()


PROTOCOL_SUPPORT: tuple[ProtocolSupport, ...] = (
    ProtocolSupport(
        protocol="Razorpay",
        actual_role="Payment provider and payment-rail integration",
        family=AdapterFamily.PAYMENT_RAIL,
        status=SupportStatus.PARTIAL,
        adapter_id=None,
        supported=(
            "Test-mode Orders API (create, lookup by id, lookup by receipt for "
            "reconciliation) and faithful X-Razorpay-Signature webhook verification "
            "(hex HMAC-SHA256 over the raw body, constant-time). A non-rzp_test_ key is "
            "refused in __init__ before it can be stored."
        ),
        not_supported=(
            "An Order is not a Payment: a completed payment needs a Checkout front end, "
            "which does not exist. Razorpay does not document receipt uniqueness, so no "
            "provider-side idempotency is claimed — duplicate prevention rests on "
            "PACTRA's own UNIQUE(idempotency_key) and the PROVIDER_PENDING path. The "
            "HTTP paths have never been exercised against the live Razorpay API."
        ),
        reason=(
            "Implemented and tested offline in Phase 4; three stated gaps keep it PARTIAL. "
            "Phase 8 changes none of it."
        ),
    ),
    ProtocolSupport(
        protocol="MCP",
        actual_role="Tool/context protocol; this adapter covers tool invocation only",
        family=AdapterFamily.TOOL,
        status=SupportStatus.PARTIAL,
        adapter_id=MCP_ID,
        supported=(
            "Translation of a JSON-RPC 2.0 tools/call request into a candidate PACTRA "
            "operation, for protocol revisions 2024-11-05, 2025-03-26 and 2025-06-18. "
            "Five namespaced pactra.* tools map to non-privileged capabilities."
        ),
        not_supported=(
            "PACTRA is NOT an MCP server: no transport (stdio/HTTP/SSE), no initialize "
            "handshake, no capability negotiation, no tools/list, no resources, prompts, "
            "sampling or notifications, and no response construction. Any protocol "
            "version outside the three above is refused rather than assumed compatible. "
            "Request ids must be strings or integers; params._meta and nested argument "
            "objects are outside this deliberately narrow boundary and are refused "
            "rather than silently discarded."
        ),
        reason=(
            "The tools/call request envelope is publicly documented and stable enough to "
            "translate without invention or an SDK. The rest of MCP is not implemented, "
            "so the claim is scoped to the one message shape that is."
        ),
        specification_sources=(
            "https://modelcontextprotocol.io/specification/2024-11-05/server/tools",
            "https://modelcontextprotocol.io/specification/2025-03-26/server/tools",
            "https://modelcontextprotocol.io/specification/2025-06-18/server/tools",
        ),
    ),
    ProtocolSupport(
        protocol="AP2",
        actual_role="External payment-authorization protocol; no adapter is implemented",
        family=AdapterFamily.PAYMENT_AUTHORIZATION,
        status=SupportStatus.PLANNED,
        adapter_id=None,
        supported=(
            "The PaymentAuthorizationAdapter family exists, with a base class, a "
            "CandidateAuthorizationRequest type that cannot become an authorization "
            "artifact, and a working reference adapter for PACTRA's own intent format."
        ),
        not_supported=(
            "There is no AP2 adapter. No AP2 message schema is documented anywhere in "
            "this repository, and honouring an external authorization artifact would "
            "additionally require an AP2-specific trust and cryptographic verification "
            "design, which PACTRA does not have."
        ),
        reason=(
            "Writing AP2 message schemas from memory would invent the semantics of "
            "somebody else's protocol. The family boundary is delivered; the adapter is not."
        ),
    ),
    ProtocolSupport(
        protocol="x402",
        actual_role="Not classified from repository-grounded protocol semantics",
        family=None,
        status=SupportStatus.PLANNED,
        adapter_id=None,
        supported="Nothing. No x402 code exists in this repository.",
        not_supported=(
            "Everything. There is no x402 adapter, no x402 message handling, and no "
            "x402 payment path. PACTRA having an amount and a payment rail is not x402 "
            "support."
        ),
        reason=(
            "No x402 semantics are documented in any source this repository contains — "
            "not even enough to assign it an adapter family, which is why the family is "
            "left unassigned rather than guessed."
        ),
    ),
    ProtocolSupport(
        protocol="ACP",
        actual_role="Not classified from repository-grounded protocol semantics",
        family=None,
        status=SupportStatus.PLANNED,
        adapter_id=None,
        supported="Nothing. No ACP code exists in this repository.",
        not_supported=(
            "Everything. The AgentCommunicationAdapter family is declared in the enum so "
            "this row can be typed and so the registry can refuse a registration into it, "
            "but the family has no base class and no implementation."
        ),
        reason=(
            "The name is ambiguous and this repository defines it nowhere: ACP appears "
            "twice, both times only to say it is NOT interchangeable with MCP, AP2 or "
            "x402. Agents exchanging JSON is not ACP compatibility."
        ),
    ),
    ProtocolSupport(
        protocol="pactra.commerce.v1",
        actual_role="PACTRA-native commerce catalog and offer translation",
        family=AdapterFamily.COMMERCE,
        status=SupportStatus.IMPLEMENTED,
        adapter_id=PACTRA_COMMERCE_ID,
        supported=(
            "A PACTRA-defined catalog document translated into candidate merchant offers, "
            "with strict JSON type checking ahead of the lax merchant DTO, unknown fields "
            "kept as untrusted metadata, and merchant claims passed to the authority "
            "lattice unchanged."
        ),
        not_supported=(
            "It assigns no merchant trust, no display name, and no authenticated "
            "identity: the claimed merchant id is verified against a transport identity "
            "downstream. It is PACTRA's own format and is not any external standard."
        ),
        reason=(
            "PACTRA-native, so implementing it invents nobody's semantics. It is what "
            "makes the CommerceAdapter contract provable against real code."
        ),
    ),
    ProtocolSupport(
        protocol="pactra.authorization-intent.v1",
        actual_role="PACTRA-native external authorization-intent translation",
        family=AdapterFamily.PAYMENT_AUTHORIZATION,
        status=SupportStatus.IMPLEMENTED,
        adapter_id=PACTRA_INTENT_ID,
        supported=(
            "A PACTRA-defined authorization intention translated into a "
            "CandidateAuthorizationRequest, with StrictInt money and timezone-aware "
            "expiries. Reserved names (nonce, transaction_digest, authorization_id, "
            "authorization_valid, signature) are refused at the boundary."
        ),
        not_supported=(
            "It issues nothing and verifies nothing. Any external authorization "
            "reference is carried as an opaque, explicitly unverified string. The "
            "USER_ED25519 verifier accepts only PACTRA's own challenge and does not "
            "authenticate external protocol references."
        ),
        reason=(
            "PACTRA-native, so implementing it invents nobody's semantics. It is what "
            "makes EXTERNAL AUTHORIZATION TOKEN != PACTRA AUTHORIZATION testable rather "
            "than merely asserted."
        ),
    ),
)


def support_for(protocol: str) -> ProtocolSupport:
    for entry in PROTOCOL_SUPPORT:
        if entry.protocol == protocol:
            return entry
    raise KeyError(f"no support-matrix entry for protocol {protocol!r}")


def implemented_protocols() -> tuple[str, ...]:
    return tuple(
        e.protocol
        for e in PROTOCOL_SUPPORT
        if e.status in (SupportStatus.IMPLEMENTED, SupportStatus.PARTIAL)
    )


def planned_protocols() -> tuple[str, ...]:
    return tuple(e.protocol for e in PROTOCOL_SUPPORT if e.status is SupportStatus.PLANNED)
