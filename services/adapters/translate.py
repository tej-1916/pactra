"""The single entry point through which an external payload becomes canonical.

TRANSLATION IS NOT EXECUTION, AND THE SIGNATURE IS THE PROOF
------------------------------------------------------------
``translate`` is a SYNCHRONOUS PURE FUNCTION THAT TAKES NO DATABASE SESSION.
There is no parameter through which it could write a row, no ``await`` through
which it could call a provider, and — checked by
``tests/test_adapter_isolation.py`` — no import of
``services.payment_executor``, ``services.security_kernel.authorization``,
``services.security_kernel.binding``, or ``services.agent_orchestrator``
anywhere in the package. So "translation causes zero provider calls, zero
authorizations, zero payment intents and zero outbox rows" is a property of the
type signature rather than an observation somebody made once.

WHAT THIS FUNCTION OWNS THAT ADAPTERS DO NOT
--------------------------------------------
Everything an adapter could get wrong in its own favour:

* **Identity.** Adapter id, protocol name, protocol version and adapter version
  are copied from the registry's ``AdapterDescriptor``. Neither the payload nor
  the adapter states them.
* **Version.** Checked against the descriptor's closed supported set BEFORE the
  payload is parsed, so an unsupported version costs nothing and cannot be
  half-interpreted. An unknown version — including a newer one — is refused, not
  assumed compatible.
* **The authority ceiling.** Every provenance entry the adapter returned is
  checked against ``descriptor.emits_authority``. An adapter cannot exempt
  itself by forgetting a call, because the check runs after it returns.
* **Taint.** Every provenance entry must be tainted and untrusted. A parser does
  not sanitize authority; schema-valid is not trusted.
* **Provenance coverage.** Every canonical value the payload produced must HAVE
  a provenance entry, against a required key set derived from the payload by
  ``required_provenance_keys``. Per-entry validity and coverage are different
  properties, and an adapter that marks the obvious fields while leaving the
  merchant identity claim or an unverified authorization reference unmarked
  satisfies the first while failing the second.
* **The family/payload-type pairing.** A TOOL adapter returning a
  ``CandidateAuthorizationRequest`` is refused rather than shipped under a TOOL
  envelope.

WHY THE CEILING HOLDS RATHER THAN MERELY BEING CHECKED
------------------------------------------------------
``authority(output) <= authority(input)`` needs a value for the input side.
``SourceIdentity.authenticated`` is ``Literal[False]``, so an input's authority
is always ``AGENT_PROPOSAL`` and never higher — there is no authenticated
protocol channel in PACTRA and no type here that could describe one. A
descriptor is capped at ``AGENT_PROPOSAL`` at construction and again at
registration. The inequality is therefore closed on both ends, not sampled.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from packages.schemas.domain import utcnow

from services.adapters.errors import (
    AdapterError,
    AuthorityCeilingViolation,
    MalformedProtocolPayload,
    ProvenanceIncomplete,
    TaintStrippedViolation,
    UnsupportedProtocolVersion,
)
from services.adapters.models import (
    FAMILY_PAYLOAD_TYPES,
    AdapterEnvelope,
    AdapterFamily,
    SourceIdentity,
    required_provenance_keys,
)
from services.adapters.registry import REGISTRY
from services.adapters.translation import TranslationResult

#: Refuse anything larger before parsing it. A protocol boundary that will parse
#: an arbitrarily large document is a protocol boundary an external party can
#: use to consume memory, and nothing PACTRA translates is remotely this big.
MAX_PAYLOAD_BYTES = 256 * 1024


def raw_reference(raw: bytes) -> str:
    """A correlation handle for a delivery, and deliberately not its content.

    An external payload may carry anything the sender chose to put in it —
    injected instructions, personal data, a forged security label. Keeping a
    hash means an envelope can be tied back to the exact bytes that produced it
    without PACTRA storing those bytes anywhere a later reader might trust.
    """
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def as_bytes_and_object(payload: bytes | str | dict) -> tuple[bytes, Any]:
    """Normalize an input to (exact bytes, parsed object).

    Accepts bytes because that is what a wire delivers and what a hash must
    cover, and accepts an already-parsed dict because a CLI and a test have one.
    A dict is re-serialized with sorted keys so the same logical payload always
    produces the same ``raw_reference`` regardless of how it was handed in.
    """
    if isinstance(payload, bytes):
        raw = payload
    elif isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, dict):
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    else:
        raise MalformedProtocolPayload(
            f"payload must be bytes, str or dict, not {type(payload).__name__}"
        )

    if len(raw) > MAX_PAYLOAD_BYTES:
        raise MalformedProtocolPayload(
            f"payload is {len(raw)} bytes, above the {MAX_PAYLOAD_BYTES}-byte adapter limit"
        )

    if isinstance(payload, dict):
        return raw, payload

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise MalformedProtocolPayload("payload is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise MalformedProtocolPayload(f"payload is not valid JSON: {exc.msg}") from exc
    return raw, parsed


def _check_result(
    *,
    adapter_id: str,
    family: AdapterFamily,
    max_authority: Any,
    result: TranslationResult,
) -> None:
    """Everything an adapter could get wrong in its own favour, checked here."""
    permitted_types = FAMILY_PAYLOAD_TYPES[family]
    if not isinstance(result.canonical_payload, permitted_types):
        raise AdapterError(
            f"adapter {adapter_id!r} in family {family.value} returned a "
            f"{type(result.canonical_payload).__name__}, which that family may not emit"
        )

    if not result.provenance:
        # A canonical payload with no provenance is a value whose origin has
        # been forgotten, which is the one thing this package exists to prevent.
        raise AdapterError(
            f"adapter {adapter_id!r} returned a canonical payload with no provenance"
        )

    # COMPLETENESS, not merely presence. "Some provenance" would let an adapter
    # mark the six fields nobody argues about while leaving the merchant
    # identity claim or an external authorization reference unmarked — the half
    # a later reader most needs to know is tainted. The required set is computed
    # from the payload by a server-owned rule, so an adapter cannot decide which
    # of its own output deserves provenance.
    missing = sorted(required_provenance_keys(result.canonical_payload) - set(result.provenance))
    if missing:
        raise ProvenanceIncomplete(
            f"adapter {adapter_id!r} returned canonical values carrying no provenance: "
            f"{', '.join(missing)}"
        )

    for name, meta in result.provenance.items():
        if meta.authority > max_authority:
            raise AuthorityCeilingViolation(
                f"adapter {adapter_id!r} emitted '{name}' at {meta.authority.name}, "
                f"above its declared ceiling {max_authority.name}"
            )
        if not meta.tainted:
            raise TaintStrippedViolation(
                f"adapter {adapter_id!r} emitted '{name}' untainted; "
                "translation does not sanitize authority"
            )
        if meta.trust is not meta.trust.UNTRUSTED:
            raise TaintStrippedViolation(
                f"adapter {adapter_id!r} emitted '{name}' as {meta.trust.value}; "
                "a translating adapter emits untrusted values only"
            )


def translate(
    adapter_id: str,
    *,
    family: AdapterFamily,
    protocol_version: str,
    payload: bytes | str | dict,
    source: SourceIdentity,
    received_at: datetime | None = None,
) -> AdapterEnvelope:
    """Translate one external payload into a canonical, still-untrusted envelope.

    ``family`` is required and keyword-only: the caller states what it believes
    it is talking to, and a mismatch is refused rather than resolved in the
    caller's favour.

    ``received_at`` is a parameter rather than an unconditional clock read so a
    caller can record the moment a delivery actually arrived, and so a test can
    pin it. It is NOT part of ``canonical_fingerprint``, which is what the
    determinism contract compares.
    """
    # Always the sealed, server-owned process registry. Accepting a registry as
    # a parameter would let a caller supply both the adapter identity and the
    # implementation that interprets its payload, defeating the registry
    # boundary before family, version, taint, or authority checks even ran.
    resolved = REGISTRY.get(adapter_id, family=family)
    descriptor = resolved.descriptor

    # BEFORE parsing. An unsupported version must cost nothing and must never be
    # half-interpreted, and refusing early means a malformed payload at an
    # unsupported version reports the version rather than the malformation.
    if not descriptor.supports(protocol_version):
        raise UnsupportedProtocolVersion(
            adapter_id, protocol_version, descriptor.supported_protocol_versions
        )

    raw, parsed = as_bytes_and_object(payload)

    result = resolved.implementation.translate_payload(
        parsed, source=source, protocol_version=protocol_version
    )

    _check_result(
        adapter_id=descriptor.adapter_id,
        family=descriptor.family,
        max_authority=descriptor.emits_authority,
        result=result,
    )

    return AdapterEnvelope(
        # SERVER-OWNED. Copied from the descriptor, never from the payload and
        # never from the adapter's own claim about itself.
        adapter_id=descriptor.adapter_id,
        adapter_family=descriptor.family,
        protocol_name=descriptor.protocol_name,
        protocol_version=protocol_version,
        adapter_version=descriptor.adapter_version,
        source_identity=source,
        source_trust=source.trust,
        source_authority=source.authority,
        received_at=received_at or utcnow(),
        raw_reference=raw_reference(raw),
        raw_byte_length=len(raw),
        canonical_payload=result.canonical_payload,
        provenance=dict(result.provenance),
        warnings=tuple(result.warnings),
    )
