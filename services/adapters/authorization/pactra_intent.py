"""``pactra.authorization-intent.v1`` — an external authorization INTENTION.

WHY THIS EXISTS AND AN AP2 ADAPTER DOES NOT
-------------------------------------------
The PaymentAuthorizationAdapter family carries the most dangerous invariant in
the phase — ``EXTERNAL AUTHORIZATION TOKEN != PACTRA AUTHORIZATION`` — so it
needs a concrete adapter to prove that invariant against. AP2 cannot be that
adapter: this repository documents no AP2 message schema, and writing one from
memory would be inventing the semantics of somebody else's protocol. So this
adapter speaks a format PACTRA defines, named ``pactra.*`` so it cannot be
misread as an external-standard claim, and AP2 stays PLANNED.

WHAT A CALLER GETS FOR SENDING ONE
-----------------------------------
A ``CandidateAuthorizationRequest``, and nothing else. Not an authorization, not
a partial authorization, not a token that becomes one later. The document may
carry an ``external_authorization_reference`` — an id from the sender's own
system — and PACTRA carries it as an OPAQUE STRING it has not verified and holds
no protocol-specific verifier to verify. USER_ED25519 accepts only PACTRA's own
server-built approval challenge. Every envelope containing a reference gets an
``EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED`` warning, because a reference
carried silently is a reference somebody eventually treats as evidence.

The real path to an authorization is unchanged and runs entirely server-side:

    candidate -> transaction binding -> deterministic policy
              -> issue_authorization  (security-kernel principal only)
              -> AuthorizationArtifact

MONEY IS ``StrictInt``
----------------------
``claimed_amount_inr`` refuses ``"3799"`` and ``3799.0`` alike. A protocol
boundary is exactly where lax coercion decides an amount, and binary floats have
no canonical decimal form — which is why ``packages/schemas/canonical.py``
rejects them from a digest preimage outright. Whole INR is what the domain uses,
so whole INR is what crosses the boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from packages.schemas.domain import ClaimValue
from pydantic import ValidationError

from services.adapters.authorization.base import PaymentAuthorizationAdapter
from services.adapters.errors import MalformedProtocolPayload, ProtocolMismatch
from services.adapters.fields import guard_payload_keys
from services.adapters.models import (
    AdapterDescriptor,
    AdapterFamily,
    AdapterWarning,
    AdapterWarningCode,
    CandidateAuthorizationRequest,
    SourceIdentity,
    SupportStatus,
)
from services.adapters.translation import (
    TranslationResult,
    external_provenance,
    provenance_source,
)

ADAPTER_ID = "pactra.authorization-intent.v1"
PROTOCOL_NAME = "pactra.authorization-intent"
ADAPTER_VERSION = "pactra-authorization-intent-v1"

SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("1.0",)
PRIMARY_PROTOCOL_VERSION = "1.0"

#: Fields the protocol defines. Everything else is unknown metadata; the
#: security-reserved names among them were already refused by
#: ``guard_payload_keys``, which is what stops ``nonce``,
#: ``transaction_digest``, ``authorization_id`` and ``authorization_valid`` from
#: ever reaching this function.
INTENT_FIELDS = frozenset(
    {
        "protocol",
        "mission_id",
        "merchant_id",
        "product_id",
        "quantity",
        "amount_inr",
        "currency",
        "expires_at",
        "external_authorization_reference",
    }
)

DESCRIPTOR = AdapterDescriptor(
    adapter_id=ADAPTER_ID,
    family=AdapterFamily.PAYMENT_AUTHORIZATION,
    protocol_name=PROTOCOL_NAME,
    protocol_version=PRIMARY_PROTOCOL_VERSION,
    supported_protocol_versions=SUPPORTED_PROTOCOL_VERSIONS,
    adapter_version=ADAPTER_VERSION,
    status=SupportStatus.IMPLEMENTED,
    summary=(
        "Translates an external authorization intention into a CandidateAuthorizationRequest. "
        "Issues nothing: an external authorization reference is carried unverified, because "
        "PACTRA has no signature verification."
    ),
)


def _require_object(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise MalformedProtocolPayload(f"{what} must be a JSON object, not {type(value).__name__}")
    return value


def _require_str(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise MalformedProtocolPayload(f"field {key!r} must be a non-empty string")
    return value


def _require_int(mapping: dict, key: str) -> int:
    """A JSON integer. Not a bool, not a float, not a numeric string.

    ``bool`` is excluded explicitly: it subclasses ``int``, so without the check
    ``"quantity": true`` would become a quantity of 1.
    """
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedProtocolPayload(
            f"field {key!r} must be a JSON integer, not {type(value).__name__} — "
            "a protocol boundary does not coerce money or quantity"
        )
    return value


def _optional_timestamp(mapping: dict, key: str) -> datetime | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise MalformedProtocolPayload(
            f"field {key!r} must be an ISO-8601 string, not {type(value).__name__}"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MalformedProtocolPayload(f"field {key!r} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MalformedProtocolPayload(
            f"field {key!r} has no UTC offset; a naive expiry has no single instant"
        )
    return parsed


def _unknown_fields(mapping: dict) -> dict[str, ClaimValue]:
    extras: dict[str, ClaimValue] = {}
    for name, value in sorted(mapping.items()):
        if name in INTENT_FIELDS:
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            extras[name] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            extras[name] = list(value)
        else:
            raise MalformedProtocolPayload(
                f"unknown field {name!r} has unsupported type {type(value).__name__}"
            )
    return extras


class PactraAuthorizationIntentAdapter(PaymentAuthorizationAdapter):
    """``pactra.authorization-intent.v1`` document -> candidate request."""

    descriptor = DESCRIPTOR

    def translate_payload(
        self,
        payload: object,
        *,
        source: SourceIdentity,
        protocol_version: str,
    ) -> TranslationResult[CandidateAuthorizationRequest]:
        document = _require_object(payload, "an authorization intent")

        # FIRST, and this is the load-bearing line of the module. ``nonce``,
        # ``transaction_digest``, ``authorization_id``, ``authorization_valid``,
        # ``signature`` and ``policy_version`` are all reserved, so a document
        # attempting to look like an issued artifact is refused before a single
        # field of it is read.
        guard_payload_keys(document)

        declared = document.get("protocol")
        if declared is not None and declared != PROTOCOL_NAME:
            raise ProtocolMismatch(
                f"document declares protocol {declared!r}; this adapter speaks {PROTOCOL_NAME!r}"
            )

        raw_mission_id = document.get("mission_id")
        mission_id: UUID | None = None
        if raw_mission_id is not None:
            if not isinstance(raw_mission_id, str):
                raise MalformedProtocolPayload("field 'mission_id' must be a UUID string or absent")
            try:
                mission_id = UUID(raw_mission_id)
            except ValueError as exc:
                raise MalformedProtocolPayload(
                    "field 'mission_id' must be a valid UUID string"
                ) from exc

        reference = document.get("external_authorization_reference")
        if reference is not None and not isinstance(reference, str):
            raise MalformedProtocolPayload(
                "field 'external_authorization_reference' must be a string or absent"
            )

        try:
            candidate = CandidateAuthorizationRequest(
                mission_id=mission_id,
                claimed_merchant_id=_require_str(document, "merchant_id"),
                claimed_product_id=_require_str(document, "product_id"),
                claimed_quantity=_require_int(document, "quantity"),
                claimed_amount_inr=_require_int(document, "amount_inr"),
                claimed_currency=_require_str(document, "currency"),
                claimed_expires_at=_optional_timestamp(document, "expires_at"),
                external_authorization_reference=reference,
                untrusted_metadata=_unknown_fields(document),
            )
        except ValidationError as exc:
            raise MalformedProtocolPayload(
                "authorization intent failed candidate validation: "
                f"{exc.error_count()} constraint violation(s)"
            ) from exc

        origin = provenance_source(ADAPTER_ID, source.claimed_id)
        provenance = {
            name: external_provenance(origin)
            for name in (
                "mission_id",
                "claimed_merchant_id",
                "claimed_product_id",
                "claimed_quantity",
                "claimed_amount_inr",
                "claimed_currency",
                "claimed_expires_at",
            )
        }
        # The reference is the single most dangerous value this adapter carries:
        # a sender's assertion that somebody approved the purchase, which PACTRA
        # holds no protocol-specific verifier for (AL-05). Marking it tainted per-field
        # matters more than any other entry here, not less, so it travels with
        # provenance rather than on the envelope-level taint flag alone.
        if candidate.external_authorization_reference is not None:
            provenance["external_authorization_reference"] = external_provenance(origin)
        if candidate.untrusted_metadata:
            provenance["untrusted_metadata"] = external_provenance(origin)

        warnings = [
            AdapterWarning(
                code=AdapterWarningCode.CLAIMED_IDENTITY_NOT_AUTHENTICATED,
                detail=(
                    f"the caller claimed to be {source.claimed_id!r}; PACTRA authenticates "
                    "no protocol channel, so this candidate authorizes nothing on its own"
                ),
            )
        ]
        if reference is not None:
            warnings.append(
                AdapterWarning(
                    code=AdapterWarningCode.EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED,
                    detail=(
                        "an external authorization reference was carried through unverified: "
                        "PACTRA has no verifier for this external reference, so it is a "
                        "correlation handle and never evidence of approval"
                    ),
                )
            )
        if candidate.untrusted_metadata:
            warnings.append(
                AdapterWarning(
                    code=AdapterWarningCode.UNKNOWN_FIELDS_KEPT_AS_UNTRUSTED_METADATA,
                    detail=(
                        "protocol-undefined fields were preserved as untrusted metadata; "
                        "they are never canonical and never security state"
                    ),
                )
            )

        return TranslationResult(
            canonical_payload=candidate,
            provenance=provenance,
            warnings=tuple(warnings),
        )
