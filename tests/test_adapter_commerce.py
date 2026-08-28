"""The commerce adapter, and the merchant trust it structurally cannot assign.

The interesting tests here are the ones that continue PAST translation. A
commerce adapter whose output could not be ingested by the kernel would
translate into nothing usable; one whose output could be ingested with trust
attached would have broken the Phase 2 guarantee. Both halves are exercised
against the REAL ingress with a transport-authenticated context.
"""

from __future__ import annotations

import pytest
from packages.schemas.merchant import MerchantAuthMethod, MerchantIdentity
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from services.adapters.commerce.pactra_commerce import DESCRIPTOR, MAX_OFFERS
from services.adapters.errors import (
    MalformedProtocolPayload,
    ProtocolMismatch,
    ReservedFieldRejected,
)
from services.adapters.models import (
    AdapterFamily,
    AdapterWarningCode,
    CandidateCommerceCatalog,
    CandidateCommerceOffer,
    SourceIdentity,
    SupportStatus,
)
from services.adapters.translate import translate
from services.policy_engine.normalization import normalize_offer
from services.security_kernel.ingress import ingest_merchant_offer
from services.security_kernel.merchant_registry import default_merchant_registry

ADAPTER = "pactra.commerce.v1"
VERSION = "1.0"
SOURCE = SourceIdentity(claimed_id="merchant_a", channel="pytest")


def offer(**overrides) -> dict:
    base = {
        "merchant_id": "merchant_a",
        "product_id": "aur-eb-01",
        "title": "Aurora SoundCore Wireless Earbuds",
        "description": "Premium ANC earbuds with 30h battery.",
        "price": 4299,
        "currency": "INR",
        "rating": 4.6,
        "in_stock": True,
        "offered_at": "2026-01-01T12:00:00+00:00",
    }
    base.update(overrides)
    return base


def catalog(merchant_id: str = "merchant_a", **offer_overrides) -> dict:
    return {
        "protocol": "pactra.commerce",
        "merchant_id": merchant_id,
        "offers": [offer(merchant_id=merchant_id, **offer_overrides)],
    }


def do(payload):
    return translate(
        ADAPTER,
        family=AdapterFamily.COMMERCE,
        protocol_version=VERSION,
        payload=payload,
        source=SOURCE,
    )


def context_for(merchant_id: str):
    identity = MerchantIdentity(
        merchant_id=merchant_id,
        auth_method=MerchantAuthMethod.IN_PROCESS_ADAPTER,
        channel="in-process",
    )
    return default_merchant_registry().context_for(identity)


# --------------------------------------------------------------------------- #
# It is PACTRA's own format, and says so
# --------------------------------------------------------------------------- #
def test_the_adapter_speaks_a_pactra_format_not_an_external_standard():
    assert DESCRIPTOR.protocol_name.startswith("pactra.")
    assert DESCRIPTOR.adapter_id.startswith("pactra.")
    assert DESCRIPTOR.status is SupportStatus.IMPLEMENTED


def test_a_document_declaring_another_protocol_is_refused():
    with pytest.raises(ProtocolMismatch):
        do({**catalog(), "protocol": "acp.commerce"})


# --------------------------------------------------------------------------- #
# Merchant trust: not assignable, because there is nothing to assign it from
# --------------------------------------------------------------------------- #
def test_the_candidate_type_has_no_trust_or_context_field():
    """The structural half. Two independent defences, and this is the one that
    does not depend on the reserved-field list being complete."""
    fields = set(CandidateCommerceOffer.model_fields) | set(CandidateCommerceCatalog.model_fields)
    assert not (fields & {"merchant_trust", "merchant_name", "context", "identity", "trust_score"})


@pytest.mark.parametrize("key", ["merchant_trust", "trust_score", "merchant_name", "trusted"])
def test_a_catalog_cannot_award_itself_trust(key):
    document = catalog()
    document["offers"][0][key] = 1.0
    with pytest.raises(ReservedFieldRejected):
        do(document)


def test_trust_comes_from_the_registry_after_ingress_not_from_the_document():
    """The behavioural half, run through the REAL ingress."""
    known = do(catalog("merchant_a")).canonical_payload.offers[0]
    provenanced = ingest_merchant_offer(known.offer, context_for("merchant_a"))
    assert provenanced.merchant_trust.value == 0.9
    assert provenanced.merchant_trust.source == "merchant-registry:merchant_a"

    unknown = do(catalog("nobody-has-heard-of-this-one")).canonical_payload.offers[0]
    unknown_provenanced = ingest_merchant_offer(
        unknown.offer, context_for("nobody-has-heard-of-this-one")
    )
    assert unknown_provenanced.merchant_trust.value == 0.0


def test_the_warning_says_trust_was_not_assigned():
    codes = {w.code for w in do(catalog()).warnings}
    assert AdapterWarningCode.MERCHANT_TRUST_NOT_ASSIGNED_BY_ADAPTER in codes
    assert AdapterWarningCode.CLAIMED_IDENTITY_NOT_AUTHENTICATED in codes


# --------------------------------------------------------------------------- #
# Identity stays a claim, and a spoof is caught downstream
# --------------------------------------------------------------------------- #
def test_a_spoofed_merchant_id_survives_as_a_claim_and_is_caught_at_ingress():
    """The adapter does not authenticate; the kernel compares.

    The document says ``merchant_a`` while the transport authenticated ``evil``,
    which is the exact Phase 2 spoof — re-proved for an offer that arrived
    through a protocol boundary.
    """
    from packages.schemas.domain import ReasonCode

    candidate = do(catalog("merchant_a")).canonical_payload.offers[0]
    assert candidate.claimed_merchant_id == "merchant_a"

    provenanced = ingest_merchant_offer(candidate.offer, context_for("evil"))
    assert provenanced.identity_mismatch is True
    assert provenanced.merchant_id.value == "evil"

    from services.attack_lab.scenarios._helpers import constraints

    normalized = normalize_offer(candidate.offer, context_for("evil"), constraints())
    assert normalized.valid is False
    assert ReasonCode.MERCHANT_IDENTITY_MISMATCH in normalized.rejection_reasons


def test_merchant_identity_is_never_case_folded():
    """Folding would turn a case variant into a MATCH against the authenticated
    identity. Leaving it exact means it correctly fails to match."""
    candidate = do(catalog("MERCHANT_A")).canonical_payload.offers[0]
    assert candidate.claimed_merchant_id == "MERCHANT_A"
    assert ingest_merchant_offer(candidate.offer, context_for("merchant_a")).identity_mismatch


# --------------------------------------------------------------------------- #
# Stricter than the DTO behind it
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", "4299"),
        ("price", True),
        ("price", None),
        ("rating", "4.6"),
        ("rating", True),
        ("in_stock", 1),
        ("in_stock", "true"),
        ("in_stock", None),
        ("product_id", 42),
        ("product_id", ""),
        ("title", None),
        ("currency", 356),
    ],
)
def test_wire_types_are_not_coerced(field, value):
    """``RawMerchantOffer`` runs in lax mode, which is fine for a trusted
    in-process caller and not fine where the SENDER chose the type."""
    with pytest.raises(MalformedProtocolPayload):
        do(catalog(**{field: value}))


@pytest.mark.parametrize(
    "timestamp", ["2026-01-01T12:00:00", "not-a-timestamp", "2026-13-01T00:00:00+00:00", ""]
)
def test_a_naive_or_invalid_timestamp_is_refused(timestamp):
    """The offer fingerprint that ends up inside a transaction digest is
    computed over this value, so a timestamp whose meaning depends on the
    reader's locale would make the binding depend on it too."""
    with pytest.raises(MalformedProtocolPayload):
        do(catalog(offered_at=timestamp))


@pytest.mark.parametrize(
    ("field", "value"), [("price", -1), ("rating", 5.5), ("rating", -0.1), ("title", "x" * 400)]
)
def test_dto_range_constraints_are_reported_as_an_adapter_refusal(field, value):
    with pytest.raises(MalformedProtocolPayload):
        do(catalog(**{field: value}))


def test_an_empty_or_oversize_catalog_is_refused():
    with pytest.raises(MalformedProtocolPayload):
        do({"protocol": "pactra.commerce", "merchant_id": "merchant_a", "offers": []})
    with pytest.raises(MalformedProtocolPayload):
        do(
            {
                "protocol": "pactra.commerce",
                "merchant_id": "merchant_a",
                "offers": [offer() for _ in range(MAX_OFFERS + 1)],
            }
        )


# --------------------------------------------------------------------------- #
# Claims pass through to the authority lattice, deliberately
# --------------------------------------------------------------------------- #
def test_merchant_claims_are_preserved_for_the_authority_lattice():
    """Refusing them here would delete a working control and replace 'the
    attempt was caught and audited' with 'the attempt was never seen'."""
    candidate = do(catalog(claims={"hard_limit_inr": 100000})).canonical_payload.offers[0]
    assert candidate.offer.claims == {"hard_limit_inr": 100000}


def test_a_claim_carrying_an_unsupported_type_is_refused():
    with pytest.raises(MalformedProtocolPayload):
        do(catalog(claims={"hard_limit_inr": {"nested": 1}}))


# --------------------------------------------------------------------------- #
# Provenance and taint through to the kernel representation
# --------------------------------------------------------------------------- #
def test_the_offer_reaches_the_kernel_still_tainted():
    """Translation then ingress: at no point does the value become trusted."""
    envelope = do(catalog())
    for meta in envelope.provenance.values():
        assert meta.tainted and meta.trust is TrustLevel.UNTRUSTED
        assert meta.authority <= AuthorityLevel.AGENT_PROPOSAL

    provenanced = ingest_merchant_offer(
        envelope.canonical_payload.offers[0].offer, context_for("merchant_a")
    )
    for field in ("amount_inr", "currency", "rating", "product_id", "title"):
        value = provenanced.field(field)
        assert value.tainted is True, field
        assert value.trust is TrustLevel.UNTRUSTED, field
        assert value.authority is AuthorityLevel.MERCHANT_DATA, field


def test_a_translated_offer_can_still_become_a_valid_ranked_offer():
    """A commerce adapter whose output could not be ingested would translate
    into nothing usable, so the happy path is asserted too."""
    from services.attack_lab.scenarios._helpers import constraints

    candidate = do(catalog()).canonical_payload.offers[0]
    normalized = normalize_offer(
        candidate.offer, context_for("merchant_a"), constraints(soft_budget_inr=4500)
    )
    assert normalized.valid is True
    assert normalized.amount_inr.value == 4299
    assert normalized.offer_version


def test_unknown_fields_are_kept_as_untrusted_metadata_at_both_levels():
    document = catalog(loyalty_tier="gold")
    document["catalog_note"] = "seasonal"
    envelope = do(document)
    assert envelope.canonical_payload.untrusted_metadata == {"catalog_note": "seasonal"}
    assert envelope.canonical_payload.offers[0].untrusted_metadata == {"loyalty_tier": "gold"}
    assert AdapterWarningCode.UNKNOWN_FIELDS_KEPT_AS_UNTRUSTED_METADATA in {
        w.code for w in envelope.warnings
    }


def test_untrusted_metadata_never_becomes_a_merchant_offer_field():
    """Preserved and marked is not the same as honoured."""
    candidate = do(catalog(loyalty_tier="gold")).canonical_payload.offers[0]
    assert "loyalty_tier" not in candidate.offer.model_dump()
