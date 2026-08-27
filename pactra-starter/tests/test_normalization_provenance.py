"""Invariant B (+ #2, #7): every merchant-derived value stays coupled to its
provenance/taint through normalization — value and provenance cannot be
separated in the kernel representation."""

from packages.schemas.kernel import SENSITIVE_FIELDS, ProvenancedOffer
from packages.schemas.provenance import AuthorityLevel, Provenanced, TrustLevel
from services.agent_orchestrator.merchants.mock_merchants import default_merchants
from services.policy_engine.normalization import normalize_offers
from tests.conftest import make_constraints


def _all(c):
    raws = []
    for m in default_merchants():
        raws.extend(m.quote(c, 1))
    return normalize_offers(raws, c)


def test_every_sensitive_field_is_provenance_coupled():
    for offer in _all(make_constraints()):
        assert isinstance(offer, ProvenancedOffer)
        for field in SENSITIVE_FIELDS:
            bound = getattr(offer, field)
            assert isinstance(bound, Provenanced), f"{field} is not coupled"
            assert bound.source.startswith("merchant:")
            assert bound.authority == AuthorityLevel.MERCHANT_DATA
            assert bound.trust == TrustLevel.UNTRUSTED
            assert bound.tainted is True


def test_all_ten_fields_present_none_untracked():
    expected = {
        "merchant_id",
        "merchant_name",
        "merchant_trust",
        "product_id",
        "title",
        "amount_inr",
        "currency",
        "rating",
        "in_stock",
        "offered_at",
    }
    assert set(SENSITIVE_FIELDS) == expected
    offer = _all(make_constraints())[0]
    assert set(offer.meta_map().keys()) == expected


def test_amount_marked_transformed_but_still_tainted():
    offer = _all(make_constraints())[0]
    assert offer.amount_inr.transformed is True
    assert offer.amount_inr.tainted is True  # transform never launders taint


def test_projection_preserves_provenance_and_drops_description():
    offer = _all(make_constraints())[0]
    dto = offer.to_normalized()
    assert set(dto.provenance.keys()) == set(SENSITIVE_FIELDS)
    assert all(m.tainted for m in dto.provenance.values())
    assert "description" not in dto.provenance
    assert "SYSTEM" not in str(dto.model_dump())
