"""MCP ``tools/call`` request translation. Status: PARTIAL, and scoped in writing.

WHAT THIS IS
    A translation of ONE Model Context Protocol message shape — the JSON-RPC
    2.0 ``tools/call`` request — into a ``CandidateOperation``. MCP is a
    TOOL/CONTEXT protocol, so it belongs to the ToolAdapter family. It is not a
    payment rail and is not treated as one.

WHAT THIS IS NOT, STATED SO NOBODY HAS TO INFER IT
    * **PACTRA is not an MCP server.** There is no transport (stdio, HTTP,
      SSE), no ``initialize`` handshake, no capability negotiation, no
      ``tools/list``, no resources, no prompts, no sampling, no notifications,
      and no response construction. Nothing here speaks MCP to anybody; it reads
      one request shape.
    * **No SDK.** The envelope is JSON-RPC 2.0, which ``json`` parses. Pulling
      an agent framework into a security kernel to read four keys would be a
      dependency with a threat model attached.
    * The claim in the support matrix is therefore ``PARTIAL`` with that scope
      written next to it, not "PACTRA supports MCP".

PROTOCOL VERSIONS
    MCP versions are date strings negotiated during ``initialize``. The set
    below is exactly the versions this adapter was WRITTEN AGAINST, and it is
    closed: any other string — older or newer — is refused with
    ``ADAPTER_PROTOCOL_VERSION_UNSUPPORTED``. Refusing a version that turns out
    to be compatible is a conservative failure; assuming a version is compatible
    because it looks recent is how two parties end up disagreeing about what a
    field means while both believe they agreed.

THE ``payment.execute`` ANSWER
    A tool call naming ``payment.execute`` is refused with
    ``ADAPTER_OPERATION_UNSUPPORTED`` because ``CandidateOperationType`` has no
    privileged member for it to map to. The refusal is the absence of a value,
    not the presence of a check, so there is nothing to disable. See
    ``services/adapters/tools/base.py``.
"""

from __future__ import annotations

from typing import Any

from packages.schemas.domain import ClaimValue

from services.adapters.errors import (
    MalformedProtocolPayload,
    ProtocolMismatch,
    UnsupportedOperation,
)
from services.adapters.fields import guard_payload_keys
from services.adapters.models import (
    AdapterDescriptor,
    AdapterFamily,
    AdapterWarning,
    AdapterWarningCode,
    CandidateOperation,
    CandidateOperationType,
    SourceIdentity,
    SupportStatus,
)
from services.adapters.tools.base import ToolAdapter
from services.adapters.translation import (
    TranslationResult,
    external_provenance,
    provenance_source,
)

ADAPTER_ID = "mcp.tools-call.v1"
PROTOCOL_NAME = "MCP"
ADAPTER_VERSION = "pactra-mcp-tools-call-v1"

#: The MCP protocol revisions this adapter was written against. Closed set.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
)
PRIMARY_PROTOCOL_VERSION = "2025-06-18"

#: The only JSON-RPC method this adapter reads. ``tools/list``, ``initialize``
#: and the rest are refused rather than stubbed: a stub that answers
#: ``initialize`` would make PACTRA look like an MCP server it is not.
SUPPORTED_METHOD = "tools/call"

JSONRPC_VERSION = "2.0"

#: The members a JSON-RPC 2.0 request envelope may carry. A JSON-RPC envelope
#: has a FIXED shape, unlike a content document, so an undefined member here is
#: a malformed message rather than extension metadata — and is refused.
#:
#: This is the opposite of what the commerce and authorization-intent adapters do
#: with an unknown key, and the difference is the point: those translate
#: EXTENSIBLE documents where a sender may legitimately add a field, so unknown
#: keys are preserved as untrusted metadata. Neither adapter ever IGNORES one.
JSONRPC_ENVELOPE_MEMBERS = frozenset({"jsonrpc", "id", "method", "params"})

#: ``tools/call`` params, per MCP. Same reasoning: a fixed shape, so an
#: undefined member is refused. The EXTENSIBLE part is ``arguments``, whose keys
#: are the tool's own and are carried through onto the candidate.
TOOLS_CALL_PARAMS_MEMBERS = frozenset({"name", "arguments", "_meta"})

#: Server-owned tool-name -> canonical-operation table. Every PACTRA tool name
#: is namespaced ``pactra.*`` so a host cannot collide with another server's
#: tool and have the collision resolved in its favour.
#:
#: THERE IS NO ENTRY FOR A PRIVILEGED OPERATION, and there is no enum member one
#: could point at. Adding ``payment.execute`` here would require adding a
#: ``CandidateOperationType`` member first — a change a reviewer sees.
TOOL_NAMES: dict[str, CandidateOperationType] = {
    "pactra.catalog.search": CandidateOperationType.CATALOG_SEARCH,
    "pactra.merchant.discover": CandidateOperationType.MERCHANT_DISCOVER,
    "pactra.offer.request": CandidateOperationType.OFFER_REQUEST,
    "pactra.offer.rank": CandidateOperationType.OFFER_RANK,
    "pactra.purchase.propose": CandidateOperationType.PURCHASE_PROPOSE,
}

#: Argument value types an MCP tool call may carry into PACTRA. Deliberately the
#: same closed JSON-safe union ``RawMerchantOffer.claims`` uses: these values are
#: equally likely to be serialized into a report, and a nested object would be a
#: place to hide a key the top-level reserved-field scan never sees.
_SCALAR_TYPES = (str, int, float, bool)

MAX_ARGUMENTS = 32
MAX_ARGUMENT_STRING = 2000

DESCRIPTOR = AdapterDescriptor(
    adapter_id=ADAPTER_ID,
    family=AdapterFamily.TOOL,
    protocol_name=PROTOCOL_NAME,
    protocol_version=PRIMARY_PROTOCOL_VERSION,
    supported_protocol_versions=SUPPORTED_PROTOCOL_VERSIONS,
    adapter_version=ADAPTER_VERSION,
    status=SupportStatus.PARTIAL,
    summary=(
        "Translates a JSON-RPC 2.0 MCP tools/call request into a candidate PACTRA "
        "operation. PACTRA is not an MCP server: no transport, no initialize "
        "handshake, no tools/list, no response construction."
    ),
)


def _require_object(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise MalformedProtocolPayload(f"{what} must be a JSON object, not {type(value).__name__}")
    return value


def _normalize_argument(name: str, value: Any) -> ClaimValue:
    """Accept JSON scalars and string lists; refuse everything else.

    A nested object is refused rather than flattened. Flattening would move keys
    out of reach of the top-level reserved-field scan, which is exactly where an
    attacker would like ``capabilities`` to live.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, _SCALAR_TYPES):
        if isinstance(value, str) and len(value) > MAX_ARGUMENT_STRING:
            raise MalformedProtocolPayload(
                f"argument {name!r} is {len(value)} characters, above the "
                f"{MAX_ARGUMENT_STRING}-character limit"
            )
        return value
    if isinstance(value, list):
        if not all(isinstance(item, str) for item in value):
            raise MalformedProtocolPayload(
                f"argument {name!r} is a list containing non-string items; "
                "only lists of strings are accepted"
            )
        return list(value)
    raise MalformedProtocolPayload(
        f"argument {name!r} has unsupported type {type(value).__name__}; "
        "nested objects are refused rather than flattened, because flattening "
        "would move keys out of reach of the reserved-field check"
    )


class McpToolAdapter(ToolAdapter):
    """MCP ``tools/call`` -> ``CandidateOperation``."""

    descriptor = DESCRIPTOR

    def translate_payload(
        self,
        payload: object,
        *,
        source: SourceIdentity,
        protocol_version: str,
    ) -> TranslationResult[CandidateOperation]:
        message = _require_object(payload, "an MCP request")

        # Key-level defences run on the envelope too, not only on arguments. A
        # request carrying a top-level ``adapter_id`` or ``capabilities`` is
        # refused before its method is even read.
        guard_payload_keys(message)

        unexpected = sorted(set(message) - JSONRPC_ENVELOPE_MEMBERS)
        if unexpected:
            raise MalformedProtocolPayload(
                f"JSON-RPC request carries undefined envelope member(s): "
                f"{', '.join(unexpected)}. A JSON-RPC envelope has a fixed shape, so "
                "an unknown member is a malformed message rather than extension "
                "metadata, and is refused rather than ignored."
            )

        jsonrpc = message.get("jsonrpc")
        if jsonrpc != JSONRPC_VERSION:
            raise ProtocolMismatch(
                f"MCP is JSON-RPC {JSONRPC_VERSION}; payload declares {jsonrpc!r}"
            )

        request_id = message.get("id")
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            raise MalformedProtocolPayload(
                "MCP tools/call is a JSON-RPC request and requires a string or "
                "integer 'id'; null, booleans, floats and missing ids are refused"
            )

        method = message.get("method")
        if not isinstance(method, str):
            raise MalformedProtocolPayload("MCP request has no string 'method'")
        if method != SUPPORTED_METHOD:
            # Not a stub and not a guess. PACTRA translates one method; saying
            # so is the difference between a scoped adapter and a pretend server.
            raise UnsupportedOperation(ADAPTER_ID, method)

        params = _require_object(message.get("params"), "MCP tools/call 'params'")
        guard_payload_keys(params)

        unexpected_params = sorted(set(params) - TOOLS_CALL_PARAMS_MEMBERS)
        if unexpected_params:
            raise MalformedProtocolPayload(
                f"tools/call params carries undefined member(s): {', '.join(unexpected_params)}"
            )

        if "_meta" in params:
            # _meta is a real MCP extension point, not an unknown field. This
            # deliberately narrow translator does not interpret or preserve its
            # arbitrary nested values, so accepting it would silently discard
            # protocol data. Refusal states the partial boundary honestly.
            raise MalformedProtocolPayload(
                "MCP tools/call params._meta is defined by MCP but is not supported "
                "by this partial translation boundary; it is refused rather than ignored"
            )

        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise MalformedProtocolPayload("MCP tools/call params has no string 'name'")

        operation = TOOL_NAMES.get(tool_name)
        if operation is None:
            # THIS is where payment.execute lands. There is no canonical
            # operation for it, so there is nothing to translate it into.
            raise UnsupportedOperation(ADAPTER_ID, tool_name)

        raw_arguments = params.get("arguments", {})
        if raw_arguments is None:
            raw_arguments = {}
        arguments_object = _require_object(raw_arguments, "MCP tools/call 'arguments'")
        if len(arguments_object) > MAX_ARGUMENTS:
            raise MalformedProtocolPayload(
                f"tool call carries {len(arguments_object)} arguments, above the "
                f"{MAX_ARGUMENTS} limit"
            )
        guard_payload_keys(arguments_object)

        arguments: dict[str, ClaimValue] = {
            name: _normalize_argument(name, value)
            for name, value in sorted(arguments_object.items())
        }

        candidate = CandidateOperation(
            operation=operation,
            claimed_tool_name=tool_name,
            arguments=arguments,
        )

        origin = provenance_source(ADAPTER_ID, source.claimed_id)
        provenance = {
            "operation": external_provenance(origin),
            "claimed_tool_name": external_provenance(origin),
            **{f"arguments.{name}": external_provenance(origin) for name in arguments},
        }

        return TranslationResult(
            canonical_payload=candidate,
            provenance=provenance,
            warnings=(
                AdapterWarning(
                    code=AdapterWarningCode.CLAIMED_IDENTITY_NOT_AUTHENTICATED,
                    detail=(
                        f"the MCP caller claimed to be {source.claimed_id!r}; PACTRA "
                        "authenticates no protocol channel, so this is a claim and the "
                        "operation still requires a server-resolved principal"
                    ),
                ),
            ),
        )
