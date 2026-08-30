"""Boundaries of what the protocol adapter layer can claim.

KEPT SEPARATE FROM KL-* AND RL-*, FOR THE SAME REASON THEY ARE SEPARATE FROM
EACH OTHER
---------------------------------------------------------------------------
``services/attack_lab/limitations.py`` holds KL-01..KL-07: boundaries of
PACTRA's SECURITY contract. ``services/risk_engine/limitations.py`` holds
RL-01..RL-09: boundaries of a MEASUREMENT. These are boundaries of an
INTEGRATION SURFACE — what PACTRA can and cannot say it speaks.

Three different kinds of claim, three lists. Folding them together would make a
protocol scoping note read like a security defect, and would change what every
Phase 6 attack-lab report prints.

Phase 8 itself added no cryptographic verification, external audit anchor, or
merchant authentication, and changed nothing about reconciliation, Razorpay's
provider-side uniqueness, or the risk engine's real-world generalization. The
later LOCAL CRYPTOGRAPHIC APPROVAL PROOF does not cause adapter-supplied
authorization references to become trusted.

These are NOT findings. Every one is a consequence of a decision made on
purpose, written down so nobody has to discover it from an integration attempt.
"""

from __future__ import annotations

from services.attack_lab.models import KnownLimitation

ADAPTER_LIMITATIONS: tuple[KnownLimitation, ...] = (
    KnownLimitation(
        id="AL-01-no-authenticated-protocol-channel",
        title="No protocol channel is authenticated, and the types say so",
        detail=(
            "SourceIdentity.authenticated is Literal[False]: PACTRA has no mutual TLS, "
            "no signed assertion, and no verifier for any protocol channel. Every "
            "claimed_id is a claim. This is load-bearing rather than merely honest — "
            "because input authority is therefore capped at AGENT_PROPOSAL, an adapter "
            "capped at the same level cannot raise authority even in principle. It also "
            "means the adapter layer proves nothing about a network attacker "
            "impersonating a caller, for the same reason KL-05 gives about merchants."
        ),
        demonstrated_by="adapter_identity_spoof",
    ),
    KnownLimitation(
        id="AL-02-mcp-is-one-message-not-a-server",
        title="MCP support is one request shape, not an MCP server",
        detail=(
            "The MCP adapter translates a JSON-RPC 2.0 tools/call request and nothing "
            "else. There is no transport, no initialize handshake, no capability "
            "negotiation, no tools/list, no resources, prompts, sampling or "
            "notifications, and no response construction. No MCP host can connect to "
            "PACTRA. The status is PARTIAL and the scope is stated wherever the claim "
            "appears; 'PACTRA supports MCP' without that scope would be false."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="AL-03-mcp-versions-are-a-closed-written-against-set",
        title="Supported MCP versions are what the adapter was written against",
        detail=(
            "2024-11-05, 2025-03-26 and 2025-06-18 are refused-by-default outside that "
            "set — including NEWER revisions. This is deliberate: silently reinterpreting "
            "an unknown version is how two parties disagree about a field's meaning while "
            "both believe they agreed. The cost is real and is stated rather than hidden: "
            "a genuinely compatible future revision is refused until somebody reads it "
            "and adds it. The set is a record of what was read, not a claim about the "
            "current MCP release."
        ),
        demonstrated_by="adapter_protocol_version_spoof",
    ),
    KnownLimitation(
        id="AL-04-two-of-three-adapters-speak-pactra-formats",
        title="Two concrete adapters speak PACTRA's own formats, not external standards",
        detail=(
            "pactra.commerce.v1 and pactra.authorization-intent.v1 are formats PACTRA "
            "defines. They are named pactra.* so they cannot be misread as external "
            "standards, and they exist because a family contract has to be provable "
            "against real code — proving it against an invented 'AP2' would be the fake "
            "integration the build spec forbids. What they demonstrate is the FAMILY "
            "boundary, not interoperability with any third party. Only MCP makes an "
            "external-protocol claim."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="AL-05-no-external-authorization-verifier",
        title="An external authorization reference is carried, never verified",
        detail=(
            "CandidateAuthorizationRequest.external_authorization_reference is an opaque "
            "string. PACTRA does not verify it and holds no protocol-specific verifier "
            "for it. The later USER_ED25519 verifier accepts only PACTRA's own "
            "server-built challenge and pre-enrolled demo key; it cannot validate an "
            "external reference. Every envelope carrying one gets an "
            "EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED warning. Until a designed "
            "verifier exists, an external authorization representation can only ever "
            "become a candidate that the kernel adjudicates from scratch."
        ),
        demonstrated_by="adapter_authorization_forgery",
    ),
    KnownLimitation(
        id="AL-06-no-http-ingress",
        title="There is no HTTP endpoint that accepts a protocol payload",
        detail=(
            "Translation is reachable from the CLI and from Python, and from nowhere "
            "else. An ingress route would be an unauthenticated front door accepting "
            "arbitrary external documents, and PACTRA has no authentication layer to gate "
            "one — the same reasoning that kept the Phase 6 attack lab CLI-only. The cost "
            "is that no external system can actually deliver a payload today, which is "
            "why every protocol claim in the support matrix is about TRANSLATION rather "
            "than about connectivity."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="AL-07-reserved-field-scan-is-top-level",
        title="The reserved-field scan covers top-level keys, not arbitrary nesting",
        detail=(
            "guard_payload_keys scans the top level of a message and of a tool call's "
            "arguments — the places a field would have to be to be read as security "
            "state. It deliberately does not recurse into RawMerchantOffer.claims, which "
            "exists to carry merchant claims about protected policy so the AUTHORITY "
            "LATTICE can refuse them and record a SECURITY_VIOLATION; refusing them "
            "earlier would delete a working control. Deeper nesting is refused a "
            "different way: adapters accept JSON scalars and string lists only, so a "
            "nested object cannot reach a canonical value at all."
        ),
        demonstrated_by="adapter_unknown_privileged_field",
    ),
)
