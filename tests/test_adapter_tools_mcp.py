"""The MCP tool adapter, and the tool-call escalation it makes unrepresentable.

The claim under test is narrow on purpose: PACTRA translates ONE MCP message
shape and is not an MCP server. These tests pin both halves — that the shape it
does translate is translated faithfully, and that everything else is refused
rather than stubbed into looking supported.
"""

from __future__ import annotations

import pytest
from packages.schemas.capability import Capability
from services.adapters.errors import (
    MalformedProtocolPayload,
    ProtocolMismatch,
    ReservedFieldRejected,
    UnsupportedOperation,
    UnsupportedProtocolVersion,
)
from services.adapters.models import (
    OPERATION_CAPABILITY,
    PRIVILEGED_CAPABILITIES,
    AdapterFamily,
    CandidateOperationType,
    SourceIdentity,
    SupportStatus,
)
from services.adapters.tools.base import authorize_operation, required_capability
from services.adapters.tools.mcp import (
    DESCRIPTOR,
    SUPPORTED_METHOD,
    SUPPORTED_PROTOCOL_VERSIONS,
    TOOL_NAMES,
)
from services.adapters.translate import translate
from services.security_kernel.capability import CapabilityDenied

ADAPTER = "mcp.tools-call.v1"
VERSION = "2025-06-18"
SOURCE = SourceIdentity(claimed_id="mcp-host", channel="pytest")


def call(name: str = "pactra.offer.request", **arguments):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": dict(arguments)},
    }


def do(payload, version: str = VERSION):
    return translate(
        ADAPTER,
        family=AdapterFamily.TOOL,
        protocol_version=version,
        payload=payload,
        source=SOURCE,
    )


# --------------------------------------------------------------------------- #
# The scoped claim
# --------------------------------------------------------------------------- #
def test_the_adapter_is_declared_partial_not_implemented():
    """PACTRA is not an MCP server, and the status says so."""
    assert DESCRIPTOR.status is SupportStatus.PARTIAL
    assert DESCRIPTOR.protocol_name == "MCP"
    assert "not an MCP server" in DESCRIPTOR.summary


@pytest.mark.parametrize("version", SUPPORTED_PROTOCOL_VERSIONS)
def test_every_declared_mcp_revision_translates(version):
    envelope = do(call(), version=version)
    assert envelope.protocol_version == version


@pytest.mark.parametrize("version", ["2023-01-01", "2099-12-31", "1.0", "latest", ""])
def test_an_undeclared_revision_is_refused_including_a_newer_one(version):
    """A conservative failure beats a silent reinterpretation."""
    with pytest.raises(UnsupportedProtocolVersion):
        do(call(), version=version)


@pytest.mark.parametrize(
    "method", ["initialize", "tools/list", "resources/list", "prompts/get", "notifications/x", ""]
)
def test_only_tools_call_is_translated(method):
    """The other methods are refused, not stubbed. A stub answering
    ``initialize`` would make PACTRA look like a server it is not."""
    assert SUPPORTED_METHOD == "tools/call"
    payload = call()
    payload["method"] = method
    with pytest.raises((UnsupportedOperation, MalformedProtocolPayload)):
        do(payload)


def test_a_non_jsonrpc_envelope_is_refused():
    for version in ("1.0", "2.1", None, 2.0):
        payload = call()
        payload["jsonrpc"] = version
        with pytest.raises(ProtocolMismatch):
            do(payload)


@pytest.mark.parametrize("request_id", [None, True, False, 1.5, [], {}])
def test_a_tools_call_requires_a_jsonrpc_request_id(request_id):
    payload = call()
    payload["id"] = request_id
    with pytest.raises(MalformedProtocolPayload):
        do(payload)


def test_a_missing_jsonrpc_request_id_is_refused():
    payload = call()
    del payload["id"]
    with pytest.raises(MalformedProtocolPayload):
        do(payload)


@pytest.mark.parametrize("request_id", [0, 7, "request-7", ""])
def test_string_and_integer_jsonrpc_request_ids_are_accepted(request_id):
    payload = call()
    payload["id"] = request_id
    assert do(payload).canonical_payload.claimed_tool_name == "pactra.offer.request"


# --------------------------------------------------------------------------- #
# The escalation that cannot be expressed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    [
        "payment.execute",
        "pactra.payment.execute",
        "refund.execute",
        "policy.modify",
        "authorization.issue",
        "merchant.modify",
        "pactra.purchase.execute",
        "PACTRA.OFFER.REQUEST",
        "pactra.offer.request ",
    ],
)
def test_a_privileged_or_unknown_tool_name_has_nothing_to_map_to(name):
    """Including case and whitespace variants: the table is an exact match, so a
    variant simply is not in it rather than being normalized into it."""
    with pytest.raises(UnsupportedOperation):
        do(call(name))


def test_no_registered_tool_name_reaches_a_privileged_capability():
    """Both halves of the guarantee, asserted rather than described."""
    assert set(TOOL_NAMES.values()) <= set(CandidateOperationType)
    reachable = {OPERATION_CAPABILITY[op] for op in TOOL_NAMES.values()}
    assert not (reachable & PRIVILEGED_CAPABILITIES)


def test_every_tool_name_is_namespaced():
    """So an MCP host cannot collide with another server's tool and have the
    collision resolved in PACTRA's favour."""
    for name in TOOL_NAMES:
        assert name.startswith("pactra."), name


# --------------------------------------------------------------------------- #
# Faithful translation of the shape it does handle
# --------------------------------------------------------------------------- #
def test_a_tool_call_becomes_a_candidate_operation():
    envelope = do(call("pactra.purchase.propose", quantity=2, category="earbuds"))
    candidate = envelope.canonical_payload
    assert candidate.operation is CandidateOperationType.PURCHASE_PROPOSE
    assert candidate.claimed_tool_name == "pactra.purchase.propose"
    assert candidate.arguments == {"category": "earbuds", "quantity": 2}
    assert candidate.candidate is True
    assert required_capability(candidate) is Capability.PAYMENT_PROPOSE


def test_the_tool_name_the_caller_used_is_kept_verbatim():
    """A report should show what was asked for, not only what it mapped to."""
    envelope = do(call("pactra.offer.rank"))
    assert envelope.canonical_payload.claimed_tool_name == "pactra.offer.rank"


def test_missing_arguments_are_an_empty_mapping_not_an_error():
    assert do(call()).canonical_payload.arguments == {}
    payload = call()
    payload["params"]["arguments"] = None
    assert do(payload).canonical_payload.arguments == {}


@pytest.mark.parametrize("value", [{"nested": 1}, [1, 2], [{"a": 1}], object()])
def test_a_nested_argument_value_is_refused_rather_than_flattened(value):
    """Flattening would move keys out of reach of the reserved-field scan, which
    is exactly where an attacker would like ``capabilities`` to live."""
    with pytest.raises((MalformedProtocolPayload, TypeError)):
        do(call("pactra.offer.request", filter=value))


def test_a_string_list_argument_is_accepted():
    envelope = do(call("pactra.offer.request", merchants=["merchant_a", "merchant_b"]))
    assert envelope.canonical_payload.arguments["merchants"] == ["merchant_a", "merchant_b"]


def test_risk_weight_and_threshold_words_remain_untrusted_arguments_only():
    """Generic tool arguments may use these words; they never configure Phase 7."""
    from packages.schemas.provenance import TrustLevel
    from services.risk_engine.config import DEFAULT_RISK_CONFIG

    before = DEFAULT_RISK_CONFIG.model_dump(mode="json")
    envelope = do(
        call(
            "pactra.offer.rank",
            weights=["merchant_trust=999", "risk_score=0"],
            threshold=0.0,
        )
    )
    assert envelope.canonical_payload.arguments == {
        "threshold": 0.0,
        "weights": ["merchant_trust=999", "risk_score=0"],
    }
    assert envelope.provenance["arguments.weights"].trust is TrustLevel.UNTRUSTED
    assert envelope.provenance["arguments.threshold"].tainted is True
    assert DEFAULT_RISK_CONFIG.model_dump(mode="json") == before


def test_too_many_arguments_are_refused():
    from services.adapters.tools.mcp import MAX_ARGUMENTS

    with pytest.raises(MalformedProtocolPayload):
        do(call("pactra.offer.request", **{f"a{i}": i for i in range(MAX_ARGUMENTS + 1)}))


def test_an_oversize_argument_string_is_refused():
    from services.adapters.tools.mcp import MAX_ARGUMENT_STRING

    with pytest.raises(MalformedProtocolPayload):
        do(call("pactra.offer.request", note="x" * (MAX_ARGUMENT_STRING + 1)))


# --------------------------------------------------------------------------- #
# The confused-deputy boundary
# --------------------------------------------------------------------------- #
def test_a_candidate_carries_no_principal_of_its_own():
    """Adapter implementation trust and caller authority are different things,
    and the candidate is where they must not be conflated."""
    from services.adapters.models import CandidateOperation

    fields = set(CandidateOperation.model_fields)
    assert not (fields & {"principal", "capabilities", "capability", "authorized"})


def test_the_principal_comes_from_the_caller_and_resolves_server_side():
    candidate = do(call("pactra.offer.request")).canonical_payload
    assert authorize_operation(candidate, principal="buyer-agent") is Capability.OFFER_REQUEST


@pytest.mark.parametrize(
    "principal", ["payment-executor", "security-kernel", "unknown-principal", ""]
)
def test_a_principal_lacking_the_capability_is_denied(principal):
    """A trusted, registered adapter produced this candidate. That grants the
    CALLER nothing — which is the confused-deputy defence."""
    candidate = do(call("pactra.offer.request")).canonical_payload
    with pytest.raises(CapabilityDenied):
        authorize_operation(candidate, principal=principal)


def test_a_candidate_cannot_be_used_to_reach_payment_execute():
    """Swept over every operation and every principal: none yields a privileged
    capability, because none maps to one."""
    for tool_name in TOOL_NAMES:
        candidate = do(call(tool_name)).canonical_payload
        assert candidate.required_capability not in PRIVILEGED_CAPABILITIES


# --------------------------------------------------------------------------- #
# Reserved fields at every level of the envelope
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "key",
    ["capabilities", "authority", "trusted", "adapter_id", "nonce", "payment.execute"],
)
def test_reserved_fields_are_refused_in_the_envelope_and_in_arguments(key):
    envelope_level = call()
    envelope_level[key] = "x"
    with pytest.raises(ReservedFieldRejected):
        do(envelope_level)

    with pytest.raises(ReservedFieldRejected):
        do(call("pactra.offer.request", **{key: "x"}))


def test_an_undefined_jsonrpc_envelope_member_is_refused():
    """A JSON-RPC envelope has a fixed shape, so an unknown member is malformed
    rather than extension metadata — and refusing beats dropping, because a
    dropped member is invisible to every reader."""
    payload = call()
    payload["extra_member"] = "x"
    with pytest.raises(MalformedProtocolPayload):
        do(payload)


def test_mcp_meta_is_refused_instead_of_silently_discarded():
    """``_meta`` is defined by MCP but outside this thin boundary's scope."""
    payload = call()
    payload["params"]["_meta"] = {"progressToken": "progress-7"}
    with pytest.raises(MalformedProtocolPayload, match="not supported"):
        do(payload)


def test_aliased_argument_keys_are_refused():
    """The sender has stated one field twice; there is no correct resolution."""
    payload = call()
    payload["params"]["arguments"] = {"merchant_id": "a", "merchantId": "b"}
    with pytest.raises(MalformedProtocolPayload):
        do(payload)
