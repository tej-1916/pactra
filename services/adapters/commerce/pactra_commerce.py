"""``pactra.commerce.v1`` — PACTRA's own catalog/offer document format.

WHY A PACTRA-NATIVE PROTOCOL RATHER THAN A NAMED EXTERNAL ONE
-------------------------------------------------------------
The CommerceAdapter family's contract has to be provable against something. The
external candidates do not qualify: this repository documents no ACP, AP2 or
x402 semantics, and implementing one from memory would be the fake integration
§15 of the spec forbids. So this adapter speaks a format PACTRA defines and
names it ``pactra.*``, which cannot be misread as a claim about somebody else's
standard.

What it is actually for: it is the shape an HTTP or message-queue merchant
integration would post. Today merchants are in-process Python objects reached
through ``MerchantTransport``; this is the boundary that would sit in front of a
merchant that is not.

STRICTER THAN ``RawMerchantOffer``, DELIBERATELY
------------------------------------------------
``RawMerchantOffer`` runs in Pydantic's lax mode, so ``price="3799"`` and
``in_stock=1`` would coerce. That is fine when a trusted caller constructs the
model in-process and is not fine here, where the SENDER chose the type: a
string that becomes a number is a value whose meaning was decided by the
parser rather than by either party. This adapter therefore checks JSON types
itself before constructing the model. The DTO is left alone — tightening it
would change Phase 1 behaviour for every existing caller to fix a problem that
only exists at this boundary.

WHAT THIS ADAPTER STRUCTURALLY CANNOT DO
-----------------------------------------
Assign merchant trust or a display name. ``CandidateCommerceOffer`` has no field
for either and this module does not import ``MerchantRegistry``. A document
declaring ``merchant_trust: 1.0`` is refused outright by the reserved-field scan
— and even if it were not, ``RawMerchantOffer`` has no such field and
``extra="ignore"`` would drop it, which is the Phase 2 structural defence still
doing its job one layer down. Two independent refusals, neither relying on the
other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from packages.schemas.domain import ClaimValue, RawMerchantOffer
from pydantic import ValidationError

from services.adapters.commerce.base import CommerceAdapter
from services.adapters.errors import MalformedProtocolPayload, ProtocolMismatch
from services.adapters.fields import guard_payload_keys
from services.adapters.models import (
    AdapterDescriptor,
    AdapterFamily,
    AdapterWarning,
    AdapterWarningCode,
    CandidateCommerceCatalog,
    CandidateCommerceOffer,
    SourceIdentity,
    SupportStatus,
)
from services.adapters.translation import (
    TranslationResult,
    external_provenance,
    provenance_source,
)

ADAPTER_ID = "pactra.commerce.v1"
PROTOCOL_NAME = "pactra.commerce"
ADAPTER_VERSION = "pactra-commerce-v1"

SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("1.0",)
PRIMARY_PROTOCOL_VERSION = "1.0"

MAX_OFFERS = 50

#: Fields the protocol defines on one offer. Anything else is UNKNOWN: kept as
#: untrusted metadata with a warning rather than dropped in silence, so a
#: reader can see what a merchant sent. Reserved security names never reach
#: here — ``guard_payload_keys`` refuses them first.
CATALOG_FIELDS = frozenset({"protocol", "merchant_id", "offers"})

OFFER_FIELDS = frozenset(
    {
        "merchant_id",
        "product_id",
        "title",
        "description",
        "price",
        "currency",
        "rating",
        "in_stock",
        "offered_at",
        "claims",
    }
)

DESCRIPTOR = AdapterDescriptor(
    adapter_id=ADAPTER_ID,
    family=AdapterFamily.COMMERCE,
    protocol_name=PROTOCOL_NAME,
    protocol_version=PRIMARY_PROTOCOL_VERSION,
    supported_protocol_versions=SUPPORTED_PROTOCOL_VERSIONS,
    adapter_version=ADAPTER_VERSION,
    status=SupportStatus.IMPLEMENTED,
    summary=(
        "Translates a PACTRA-native commerce catalog document into candidate merchant "
        "offers. Assigns no merchant trust and no authenticated identity: the claimed "
        "merchant id is verified against a transport identity downstream."
    ),
)


def _require_object(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise MalformedProtocolPayload(f"{what} must be a JSON object, not {type(value).__name__}")
    return value


def _require_str(mapping: dict, key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise MalformedProtocolPayload(f"offer field {key!r} must be a non-empty string")
    return value


def _require_number(mapping: dict, key: str) -> float:
    """A JSON number, and NOT a bool or a numeric string.

    ``bool`` is excluded explicitly because it is a subclass of ``int`` in
    Python: without the check, ``"price": true`` would become a price of 1.
    """
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MalformedProtocolPayload(
            f"offer field {key!r} must be a JSON number, not "
            f"{type(value).__name__} — a protocol boundary does not coerce money"
        )
    return float(value)


def _require_bool(mapping: dict, key: str) -> bool:
    value = mapping.get(key)
    if not isinstance(value, bool):
        raise MalformedProtocolPayload(
            f"offer field {key!r} must be a JSON boolean, not {type(value).__name__}"
        )
    return value


def _require_timestamp(mapping: dict, key: str) -> datetime:
    """An ISO-8601 timestamp WITH an offset.

    A naive timestamp has no single instant, and the offer fingerprint that
    ends up inside a transaction digest is computed over this value — so a
    timestamp whose meaning depends on the reader's locale would make the
    binding depend on it too.
    """
    value = mapping.get(key)
    if not isinstance(value, str):
        raise MalformedProtocolPayload(
            f"offer field {key!r} must be an ISO-8601 string, not {type(value).__name__}"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MalformedProtocolPayload(
            f"offer field {key!r} is not a valid ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MalformedProtocolPayload(
            f"offer field {key!r} has no UTC offset; a naive timestamp has no single instant"
        )
    return parsed


def _claims(mapping: dict) -> dict[str, ClaimValue]:
    """Merchant claims, passed through UNCHANGED for the authority lattice.

    Deliberately not filtered. ``claims`` is the channel a merchant uses to
    assert things about protected policy, and the AUTHORITY LATTICE already
    refuses every such write and records a ``SECURITY_VIOLATION``. Refusing them
    here would delete a working control and replace "the attempt was caught and
    audited" with "the attempt was never seen".
    """
    claims = mapping.get("claims", {})
    if claims is None:
        return {}
    claims_object = _require_object(claims, "offer field 'claims'")
    for name, value in claims_object.items():
        if value is not None and not isinstance(value, (str, int, float, bool, list)):
            raise MalformedProtocolPayload(
                f"claim {name!r} has unsupported type {type(value).__name__}"
            )
        if isinstance(value, list) and not all(isinstance(item, str) for item in value):
            raise MalformedProtocolPayload(f"claim {name!r} is a list of non-strings")
    return dict(claims_object)


def _unknown_fields(mapping: dict, known: frozenset[str] = OFFER_FIELDS) -> dict[str, ClaimValue]:
    """Protocol-undefined keys, kept as untrusted metadata.

    Never canonical and never security state — the reserved names that WOULD be
    security state were already refused by ``guard_payload_keys``. Keeping the
    rest means a merchant that sends an extra field gets it back in a report
    instead of having it vanish, and a reader can see exactly what arrived.
    """
    extras: dict[str, ClaimValue] = {}
    for name, value in sorted(mapping.items()):
        if name in known:
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            extras[name] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            extras[name] = list(value)
        else:
            raise MalformedProtocolPayload(
                f"unknown field {name!r} has unsupported type {type(value).__name__}; "
                "nested structures are refused rather than kept as opaque metadata"
            )
    return extras


class PactraCommerceAdapter(CommerceAdapter):
    """``pactra.commerce.v1`` catalog document -> candidate commerce offers."""

    descriptor = DESCRIPTOR

    def translate_payload(
        self,
        payload: object,
        *,
        source: SourceIdentity,
        protocol_version: str,
    ) -> TranslationResult[CandidateCommerceCatalog | CandidateCommerceOffer]:
        document = _require_object(payload, "a pactra.commerce catalog")
        guard_payload_keys(document)

        declared = document.get("protocol")
        if declared is not None and declared != PROTOCOL_NAME:
            raise ProtocolMismatch(
                f"document declares protocol {declared!r}; this adapter speaks {PROTOCOL_NAME!r}"
            )

        claimed_merchant_id = _require_str(document, "merchant_id")

        raw_offers = document.get("offers")
        if not isinstance(raw_offers, list):
            raise MalformedProtocolPayload("catalog field 'offers' must be a JSON array")
        if not raw_offers:
            raise MalformedProtocolPayload("catalog carries no offers")
        if len(raw_offers) > MAX_OFFERS:
            raise MalformedProtocolPayload(
                f"catalog carries {len(raw_offers)} offers, above the {MAX_OFFERS} limit"
            )

        catalog_extras = _unknown_fields(document, CATALOG_FIELDS)
        origin = provenance_source(ADAPTER_ID, claimed_merchant_id)
        offers: list[CandidateCommerceOffer] = []
        provenance = {"claimed_merchant_id": external_provenance(origin)}
        if catalog_extras:
            provenance["untrusted_metadata"] = external_provenance(origin)
        any_unknown_fields = bool(catalog_extras)

        for index, entry in enumerate(raw_offers):
            offer_object = _require_object(entry, f"offers[{index}]")
            guard_payload_keys(offer_object)

            # Types are checked HERE, before the lax-mode model sees them.
            values = {
                "merchant_id": _require_str(offer_object, "merchant_id"),
                "product_id": _require_str(offer_object, "product_id"),
                "title": _require_str(offer_object, "title"),
                "description": offer_object.get("description", ""),
                "price": _require_number(offer_object, "price"),
                "currency": _require_str(offer_object, "currency"),
                "rating": _require_number(offer_object, "rating"),
                "in_stock": _require_bool(offer_object, "in_stock"),
                "offered_at": _require_timestamp(offer_object, "offered_at"),
                "claims": _claims(offer_object),
            }
            if not isinstance(values["description"], str):
                raise MalformedProtocolPayload("offer field 'description' must be a string")

            try:
                raw_offer = RawMerchantOffer(**values)
            except ValidationError as exc:
                # Range and length constraints (negative price, rating above
                # scale, oversize title) are the DTO's, and are reported as the
                # adapter refusing rather than as a stack trace.
                raise MalformedProtocolPayload(
                    f"offers[{index}] failed PACTRA's merchant offer schema: "
                    f"{exc.error_count()} constraint violation(s)"
                ) from exc

            extras = _unknown_fields(offer_object)
            any_unknown_fields = any_unknown_fields or bool(extras)
            offers.append(
                CandidateCommerceOffer(
                    claimed_merchant_id=raw_offer.merchant_id,
                    offer=raw_offer,
                    untrusted_metadata=extras,
                )
            )
            # EVERY field of the offer, not the interesting-looking subset.
            # ``merchant_id`` is the identity claim and ``offered_at`` is what
            # the offer fingerprint inside a transaction digest is computed
            # over, so leaving either unmarked would omit provenance from
            # exactly the two values a later reader most needs to distrust.
            # ``translate`` re-derives this set and refuses a short one.
            for field_name in type(raw_offer).model_fields:
                provenance[f"offers[{index}].{field_name}"] = external_provenance(origin)
            if extras:
                provenance[f"offers[{index}].untrusted_metadata"] = external_provenance(origin)

        warnings = [
            AdapterWarning(
                code=AdapterWarningCode.CLAIMED_IDENTITY_NOT_AUTHENTICATED,
                detail=(
                    f"the document claims merchant {claimed_merchant_id!r}; it is verified "
                    "against a transport-authenticated identity by "
                    "ingest_merchant_offer, and a mismatch is MERCHANT_IDENTITY_MISMATCH"
                ),
            ),
            AdapterWarning(
                code=AdapterWarningCode.MERCHANT_TRUST_NOT_ASSIGNED_BY_ADAPTER,
                detail=(
                    "no merchant trust or display name is attached: both come from the "
                    "server-owned MerchantRegistry, which this adapter cannot reach"
                ),
            ),
        ]
        if any_unknown_fields:
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
            canonical_payload=CandidateCommerceCatalog(
                claimed_merchant_id=claimed_merchant_id,
                offers=tuple(offers),
                untrusted_metadata=catalog_extras,
            ),
            provenance=provenance,
            warnings=tuple(warnings),
        )
