from services.agent_orchestrator.merchants.mock_merchants import (
    MockMerchantA,
    MockMerchantB,
    default_merchants,
)
from services.policy_engine.normalization import normalize_offers
from tests.conftest import make_constraints


def test_merchants_are_deterministic():
    a1 = MockMerchantA().quote(make_constraints(), 1)
    a2 = MockMerchantA().quote(make_constraints(), 1)
    assert [o.model_dump() for o in a1] == [o.model_dump() for o in a2]


def test_two_merchants_present():
    ms = default_merchants()
    assert len(ms) == 2
    assert {m.merchant_id for m in ms} == {"merchant_a", "merchant_b"}


def test_normalization_drops_untrusted_description():
    c = make_constraints()
    raws = MockMerchantB().quote(c, 1)
    norms = normalize_offers(raws, c)
    # The coupled ProvenancedOffer has no `description` field at all: injected
    # text cannot reach any decision component.
    for n in norms:
        assert not hasattr(n, "description")
        dumped = n.model_dump()
        assert "description" not in dumped
        assert "SYSTEM" not in str(dumped)


def test_normalization_marks_low_rating_invalid():
    c = make_constraints(min_rating=4.2)
    raws = MockMerchantB().quote(c, 1)  # nim-eb-12 is rated 3.9
    norms = normalize_offers(raws, c)
    low = [n for n in norms if n.product_id.value == "nim-eb-12"][0]
    assert low.valid is False
    from packages.schemas.domain import ReasonCode

    assert ReasonCode.RATING_BELOW_MIN in low.rejection_reasons
