from services.agent_orchestrator.merchants.mock_merchants import default_merchants
from services.policy_engine.normalization import normalize_offers
from services.policy_engine.ranking import best_offer, rank_offers
from tests.conftest import make_constraints


def _all_norms(c):
    raws = []
    for m in default_merchants():
        raws.extend(m.quote(c, 1))
    return normalize_offers(raws, c)


def test_only_valid_offers_ranked():
    c = make_constraints(min_rating=4.2)
    ranked = rank_offers(_all_norms(c))
    assert all(o.valid for o in ranked)
    assert all(o.rating.value >= 4.2 for o in ranked)


def test_ranking_is_deterministic_and_higher_rating_first():
    c = make_constraints(min_rating=4.2)
    r1 = rank_offers(_all_norms(c))
    r2 = rank_offers(_all_norms(c))
    assert [o.product_id.value for o in r1] == [o.product_id.value for o in r2]
    # Aurora 4.6 outranks Nimbus 4.3
    assert r1[0].product_id.value == "aur-eb-01"
    assert r1[0].rank == 1


def test_best_offer_none_when_no_valid():
    c = make_constraints(min_rating=5.0)  # nothing qualifies
    assert best_offer(_all_norms(c)) is None
