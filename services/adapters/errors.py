"""Adapter refusal vocabulary.

Every failure a protocol boundary can produce has its OWN type and its OWN
reason code. That is not tidiness: the attack lab scores a scenario against an
``expected_reason_code``, so "the adapter refused" is only a measurement if the
refusal says which control refused it. A single generic ``AdapterError`` would
let a payload rejected for being malformed and a payload rejected for smuggling
``policy_override`` report identically, and one of those is an attack.

The codes are stated here rather than derived from class names so a rename
cannot silently change what a report says.
"""

from __future__ import annotations


class AdapterError(Exception):
    """Base class for every refusal at a protocol adapter boundary."""

    reason_code = "ADAPTER_ERROR"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.reason_code}: {detail}")
        self.detail = detail


# --------------------------------------------------------------------------- #
# Registry / identity
# --------------------------------------------------------------------------- #
class UnknownAdapter(AdapterError):
    """No adapter is registered under this id.

    Never falls back to a default, for the reason the payment provider registry
    gives: a payload delivered to an unrecognised adapter must not be
    interpreted by whichever adapter happened to be configured.
    """

    reason_code = "ADAPTER_NOT_REGISTERED"

    def __init__(self, adapter_id: str) -> None:
        super().__init__(f"no adapter registered as {adapter_id!r}")
        self.adapter_id = adapter_id


class DuplicateAdapter(AdapterError):
    """Two adapters claimed the same id.

    Raised eagerly at import. A silently overwritten adapter means one protocol
    boundary stopped being the one the support matrix names.
    """

    reason_code = "ADAPTER_ID_CONFLICT"


class AdapterFamilyMismatch(AdapterError):
    """The adapter is registered, but not in the family the caller asked for.

    This is the cross-family confusion defence. A ``ToolAdapter`` resolved as a
    ``CommerceAdapter`` would translate a tool call into commerce semantics and
    call the result canonical.
    """

    reason_code = "ADAPTER_FAMILY_MISMATCH"

    def __init__(self, adapter_id: str, expected: str, actual: str) -> None:
        super().__init__(f"adapter {adapter_id!r} is registered as {actual}, not {expected}")
        self.adapter_id = adapter_id
        self.expected = expected
        self.actual = actual


class AdapterRegistrationRefused(AdapterError):
    """A registration was refused before it could take effect.

    Covers the families that deliberately hold no translating adapter
    (``PAYMENT_RAIL``, ``AGENT_COMMUNICATION``), an implementation that is not
    an instance of its family's base class, and a descriptor whose declared
    authority ceiling exceeds what any adapter may emit.
    """

    reason_code = "ADAPTER_REGISTRATION_REFUSED"


# --------------------------------------------------------------------------- #
# Protocol / version
# --------------------------------------------------------------------------- #
class UnsupportedProtocolVersion(AdapterError):
    """The requested protocol version is not one this adapter was written for.

    Refused rather than reinterpreted. Treating an unknown version as "probably
    like the last one" is how a field silently changes meaning between two
    parties who both believe they agreed.
    """

    reason_code = "ADAPTER_PROTOCOL_VERSION_UNSUPPORTED"

    def __init__(self, adapter_id: str, requested: str, supported: tuple[str, ...]) -> None:
        super().__init__(
            f"adapter {adapter_id!r} does not support protocol version {requested!r} "
            f"(supported: {', '.join(supported) or 'none'})"
        )
        self.adapter_id = adapter_id
        self.requested = requested
        self.supported = supported


class ProtocolMismatch(AdapterError):
    """The payload declares a different protocol than the adapter speaks."""

    reason_code = "ADAPTER_PROTOCOL_MISMATCH"


# --------------------------------------------------------------------------- #
# Payload
# --------------------------------------------------------------------------- #
class MalformedProtocolPayload(AdapterError):
    """The payload is not a well-formed message of this protocol.

    Raised BEFORE any value reaches a domain model, so malformed data never
    arrives at a privileged service. Schema validity is not trust — it is only
    the precondition for having something to distrust precisely.
    """

    reason_code = "ADAPTER_PAYLOAD_MALFORMED"


class AmbiguousProtocolField(MalformedProtocolPayload):
    """Two payload keys canonicalize to the same field.

    ``merchantId`` beside ``merchant_id``, or ``Policy_Override`` beside
    ``policy-override``: whichever the parser happens to read last decides the
    meaning, and an attacker picks the ordering. Refused rather than resolved,
    because there is no correct resolution — the sender has stated two things.
    """

    reason_code = "ADAPTER_AMBIGUOUS_FIELD"


class ReservedFieldRejected(AdapterError):
    """The payload carried a field that names security state.

    ``authority``, ``capability``, ``trusted``, ``policy_override``,
    ``authorization_valid``, ``nonce``, ``merchant_trust``, ``risk_score`` and
    friends are refused at the boundary rather than ignored. Ignoring them is
    defensible for one build and fragile forever after: the day somebody adds a
    field with a matching name, silently-dropped becomes silently-honoured.
    """

    reason_code = "ADAPTER_RESERVED_FIELD_REJECTED"

    def __init__(self, fields: tuple[str, ...]) -> None:
        super().__init__(
            "payload declares security-reserved field(s) that an external source "
            f"may never set: {', '.join(fields)}"
        )
        self.fields = fields


class UnsupportedOperation(AdapterError):
    """The external caller named an operation PACTRA does not expose.

    This is the ``payment.execute`` answer. The operation is not "denied" by a
    check that could be removed — there is no canonical operation it maps to, so
    the request cannot be represented at all.
    """

    reason_code = "ADAPTER_OPERATION_UNSUPPORTED"

    def __init__(self, adapter_id: str, requested: str) -> None:
        super().__init__(
            f"adapter {adapter_id!r} exposes no canonical operation named {requested!r}"
        )
        self.adapter_id = adapter_id
        self.requested = requested


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #
class AuthorityCeilingViolation(AdapterError):
    """An adapter tried to emit a value above the authority it may produce.

    Checked by ``translate`` AFTER the adapter returns, so an adapter cannot
    exempt itself. A translation that could raise authority would make every
    other control in the kernel conditional on the goodwill of a parser.
    """

    reason_code = "ADAPTER_AUTHORITY_CEILING"


class ProvenanceIncomplete(AdapterError):
    """An adapter emitted a canonical value it attached no provenance to.

    Distinct from ``TaintStrippedViolation``, and the distinction is the point:
    that one is a value MARKED wrongly, this one is a value not marked at all,
    and the second is much the easier of the two to ship by accident. An adapter
    that marks the six fields nobody argues about while leaving the merchant
    identity claim or an external authorization reference unmarked passes a
    per-entry check and fails this one.

    The required key set is computed from the payload by
    ``required_provenance_keys``, which is server-owned and runs after the
    adapter returns, so an adapter cannot narrow its own obligation.
    """

    reason_code = "ADAPTER_PROVENANCE_INCOMPLETE"


class TaintStrippedViolation(AdapterError):
    """An adapter emitted an untainted or trusted value.

    A parser does not sanitize authority. Untrusted input that survives
    translation is still untrusted input.
    """

    reason_code = "ADAPTER_TAINT_STRIPPED"


#: Every reason code this package can produce. Pinned as data so a report or a
#: test can enumerate them without importing every class, and so adding an error
#: type without a distinct code fails ``tests/test_adapter_models.py``.
ADAPTER_REASON_CODES: tuple[str, ...] = (
    AdapterError.reason_code,
    UnknownAdapter.reason_code,
    DuplicateAdapter.reason_code,
    AdapterFamilyMismatch.reason_code,
    AdapterRegistrationRefused.reason_code,
    UnsupportedProtocolVersion.reason_code,
    ProtocolMismatch.reason_code,
    MalformedProtocolPayload.reason_code,
    AmbiguousProtocolField.reason_code,
    ReservedFieldRejected.reason_code,
    UnsupportedOperation.reason_code,
    AuthorityCeilingViolation.reason_code,
    ProvenanceIncomplete.reason_code,
    TaintStrippedViolation.reason_code,
)
