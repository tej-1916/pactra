from packages.schemas.domain import PolicyOutcome, ReasonCode
from services.policy_engine import engine
from services.policy_engine.normalization import normalize_offers
from services.policy_engine.ranking import best_offer
from tests.conftest import collect_quotes, make_constraints


def _best(c):
    return best_offer(normalize_offers(collect_quotes(c), c))


def test_require_approval_when_over_soft_budget():
    # Best valid offer is aur-eb-01 @ 4299 > soft 4000, <= hard 4500
    c = make_constraints(soft_budget_inr=4000, hard_limit_inr=4500, min_rating=4.2)
    d = engine.evaluate(c, _best(c), 1)
    assert d.decision == PolicyOutcome.REQUIRE_APPROVAL
    assert ReasonCode.SOFT_BUDGET_EXCEEDED in d.reason_codes
    assert d.requested_amount == 4299


def test_allow_within_budget():
    c = make_constraints(soft_budget_inr=5000, hard_limit_inr=6000, min_rating=4.2)
    d = engine.evaluate(c, _best(c), 1)
    assert d.decision == PolicyOutcome.ALLOW
    assert ReasonCode.WITHIN_LIMITS in d.reason_codes


def test_deny_when_over_hard_limit():
    # quantity pushes amount past the hard ceiling
    c = make_constraints(soft_budget_inr=4000, hard_limit_inr=4500, min_rating=4.2)
    d = engine.evaluate(c, _best(c), 2)  # 4299*2 = 8598 > 4500
    assert d.decision == PolicyOutcome.DENY
    assert ReasonCode.HARD_LIMIT_EXCEEDED in d.reason_codes


def test_deny_when_no_valid_offers():
    c = make_constraints(min_rating=5.0)
    d = engine.evaluate(c, _best(c), 1)
    assert d.decision == PolicyOutcome.DENY
    assert ReasonCode.NO_VALID_OFFERS in d.reason_codes


def test_hard_limit_invariant_never_approves_above_ceiling():
    # The hard ceiling is absolute: any amount above it is DENY, even when the
    # soft budget equals the hard limit (i.e. no approval band exists).
    c = make_constraints(soft_budget_inr=1000, hard_limit_inr=1000, min_rating=4.2)
    d = engine.evaluate(c, _best(c), 1)  # best valid offer 4299 > 1000
    assert d.decision == PolicyOutcome.DENY
    assert ReasonCode.HARD_LIMIT_EXCEEDED in d.reason_codes
