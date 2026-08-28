"""Property tests over the scorer, with Hypothesis.

Used selectively. The properties below are the ones where a hand-written example
proves little because the interesting failures live at boundaries a person would
not think to pick: a ramp evaluated a float's width either side of its bound, a
count of 10^9, a feature map with every factor firing at once.
"""

from __future__ import annotations

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from services.risk_engine.config import DEFAULT_RISK_CONFIG, ramp
from services.risk_engine.heuristic import FACTOR_RULES, Shape, normalize, score
from services.risk_engine.models import BAND_ORDER
from tests.test_risk_heuristic import feature

CONFIG = DEFAULT_RISK_CONFIG

#: Values a feature could plausibly hold, including the absurd ones.
VALUES = st.one_of(
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.integers(min_value=0, max_value=1_000_000),
)

#: Every feature a rule reads, so a generated map can fire anything.
SCORED_FEATURES = sorted({rule.feature for rule in FACTOR_RULES})


# --------------------------------------------------------------------------- #
# ramp
# --------------------------------------------------------------------------- #
@given(
    value=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
    lo=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    width=st.floats(min_value=0.001, max_value=100.0, allow_nan=False),
)
def test_ramp_always_returns_a_fraction(value, lo, width):
    assert 0.0 <= ramp(value, lo, lo + width) <= 1.0


@given(
    lower=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False),
    delta=st.floats(min_value=0.0, max_value=1e5, allow_nan=False),
    lo=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    width=st.floats(min_value=0.001, max_value=100.0, allow_nan=False),
)
def test_ramp_is_non_decreasing(lower, delta, lo, width):
    assert ramp(lower + delta, lo, lo + width) >= ramp(lower, lo, lo + width)


# --------------------------------------------------------------------------- #
# Score range and determinism
# --------------------------------------------------------------------------- #
@given(
    values=st.dictionaries(
        st.sampled_from(SCORED_FEATURES), VALUES, min_size=0, max_size=len(SCORED_FEATURES)
    )
)
@settings(max_examples=200, deadline=None)
def test_the_normalized_score_is_always_within_range(values):
    payload = {name: feature(name, value) for name, value in values.items()}
    _, points = score(payload, config=CONFIG)
    normalized = normalize(points, config=CONFIG)
    assert 0.0 <= normalized <= 1.0
    assert not math.isnan(normalized)


@given(
    values=st.dictionaries(
        st.sampled_from(SCORED_FEATURES), VALUES, min_size=1, max_size=len(SCORED_FEATURES)
    )
)
@settings(max_examples=100, deadline=None)
def test_the_same_feature_vector_always_produces_the_same_assessment(values):
    payload = {name: feature(name, value) for name, value in values.items()}
    first_factors, first_points = score(payload, config=CONFIG)
    second_factors, second_points = score(payload, config=CONFIG)
    assert first_points == second_points
    assert [f.model_dump() for f in first_factors] == [f.model_dump() for f in second_factors]


@given(
    values=st.dictionaries(
        st.sampled_from(SCORED_FEATURES), VALUES, min_size=1, max_size=len(SCORED_FEATURES)
    )
)
@settings(max_examples=200, deadline=None)
def test_contributions_always_sum_to_the_raw_points(values):
    """The property that makes the explanation an account of the score."""
    payload = {name: feature(name, value) for name, value in values.items()}
    factors, points = score(payload, config=CONFIG)
    # Exact equality, across arbitrary feature vectors: the engine sums the
    # factors in the order it publishes them, so the printed column and the
    # reported total are the same computation rather than two similar ones.
    assert sum(f.contribution for f in factors) == points


@given(
    values=st.dictionaries(
        st.sampled_from(SCORED_FEATURES), VALUES, min_size=1, max_size=len(SCORED_FEATURES)
    )
)
@settings(max_examples=200, deadline=None)
def test_no_contribution_ever_exceeds_its_configured_weight(values):
    payload = {name: feature(name, value) for name, value in values.items()}
    factors, _ = score(payload, config=CONFIG)
    for factor in factors:
        assert 0.0 < factor.contribution <= factor.weight + 1e-12


# --------------------------------------------------------------------------- #
# Monotonicity: more of a risky thing never contributes less
# --------------------------------------------------------------------------- #
_RISING_RULES = [rule for rule in FACTOR_RULES if rule.shape in (Shape.RATIO, Shape.COUNT)]


@given(
    rule_index=st.integers(min_value=0, max_value=len(_RISING_RULES) - 1),
    base=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
    delta=st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
)
@settings(max_examples=300, deadline=None)
def test_increasing_a_risky_feature_never_lowers_its_own_contribution(rule_index, base, delta):
    rule = _RISING_RULES[rule_index]

    def contribution(value: float) -> float:
        payload = {rule.feature: feature(rule.feature, value)}
        # ``merchant_known`` gates the trust rule; the rules here are ungated,
        # but supplying it keeps the map shape uniform.
        factors, _ = score(payload, config=CONFIG)
        return sum(f.contribution for f in factors if f.code == rule.code)

    assert contribution(base + delta) >= contribution(base)


@given(
    high=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    drop=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=200, deadline=None)
def test_lower_merchant_trust_never_lowers_the_trust_contribution(high, drop):
    """Trust runs the other way, so it gets its own property."""
    low = max(0.0, high - drop)

    def contribution(trust: float) -> float:
        payload = {
            "merchant_known": feature("merchant_known", True),
            "merchant_trust": feature("merchant_trust", trust),
        }
        factors, _ = score(payload, config=CONFIG)
        return sum(f.contribution for f in factors if f.code == "MERCHANT_TRUST_BELOW_PREFERRED")

    assert contribution(low) >= contribution(high)


@given(
    values=st.dictionaries(st.sampled_from(SCORED_FEATURES), VALUES, min_size=1, max_size=6),
    extra=st.sampled_from(SCORED_FEATURES),
    extra_value=st.floats(min_value=0.0, max_value=1e4, allow_nan=False),
)
@settings(max_examples=200, deadline=None)
def test_adding_a_risky_observation_never_lowers_the_total(values, extra, extra_value):
    """No factor can cancel another. A clean record cannot net out a spoof."""
    assume(extra not in values)
    base = {name: feature(name, value) for name, value in values.items()}
    augmented = {**base, extra: feature(extra, extra_value)}
    assert score(augmented, config=CONFIG)[1] >= score(base, config=CONFIG)[1]


# --------------------------------------------------------------------------- #
# Bands
# --------------------------------------------------------------------------- #
@given(value=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
def test_a_band_is_always_assigned(value):
    assert CONFIG.band_for(value) in BAND_ORDER


@given(
    lower=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    upper=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
def test_a_higher_score_never_yields_a_lower_band(lower, upper):
    low, high = sorted((lower, upper))
    assert BAND_ORDER[CONFIG.band_for(high)] >= BAND_ORDER[CONFIG.band_for(low)]


@given(points=st.floats(min_value=0.0, max_value=1e9, allow_nan=False))
def test_normalize_is_non_decreasing_and_saturates(points):
    value = normalize(points, config=CONFIG)
    assert 0.0 <= value <= 1.0
    assert normalize(points + 1.0, config=CONFIG) >= value


# --------------------------------------------------------------------------- #
# Untrusted claims cannot participate
# --------------------------------------------------------------------------- #
@given(claimed_trust=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
@settings(max_examples=50, deadline=None)
def test_a_claimed_trust_value_has_no_field_to_arrive_through(claimed_trust):
    """Whatever a merchant claims, the schema has nowhere to put it."""
    from packages.schemas.domain import RawMerchantOffer

    offer = RawMerchantOffer.model_validate(
        {
            "merchant_id": "m",
            "product_id": "p",
            "title": "t",
            "price": 100,
            "currency": "INR",
            "rating": 4.0,
            "in_stock": True,
            "merchant_trust": claimed_trust,
            "trust": claimed_trust,
            "trust_score": claimed_trust,
        }
    )
    dumped = offer.model_dump()
    assert "merchant_trust" not in dumped
    assert "trust" not in dumped
    assert "trust_score" not in dumped
