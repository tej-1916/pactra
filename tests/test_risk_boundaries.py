"""Band and threshold boundary semantics, pinned exactly.

WHY THIS FILE EXISTS SEPARATELY
--------------------------------
A band boundary is the one place where an off-by-one in a comparison operator
changes a verdict without changing a number. `0.25` landing in LOW instead of
MEDIUM turns a REVIEW into a PROCEED, and nothing in an aggregate metric would
show it — the mean score would be identical. So the boundaries are asserted at
the exact value, one ULP below, and one ULP above, rather than "somewhere near".

TWO DIFFERENT OUT-OF-RANGE POLICIES, BOTH DELIBERATE
------------------------------------------------------
They are different on purpose and this file pins both:

* ``normalize()`` **clamps**. Its input is a point total that legitimately
  exceeds saturation — three severe factors really do sum past 1.0 — and the
  index is defined as saturating. Rejecting there would turn "very risky" into
  an exception.
* ``RiskAssessment.score`` **rejects**. Its input is supposed to have come from
  ``normalize`` already, so a value outside ``[0, 1]`` means a caller bypassed
  normalization or invented a score. Clamping there would silently accept the
  bypass and hand back a plausible-looking assessment.

Clamp where out-of-range is expected; reject where it means something went
wrong. A single uniform policy would get one of the two cases wrong.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError
from services.risk_engine.config import DEFAULT_RISK_CONFIG, RiskConfig
from services.risk_engine.heuristic import normalize
from services.risk_engine.models import BAND_ORDER, RiskBand, RiskRecommendation

CONFIG = DEFAULT_RISK_CONFIG


#: One representable step below/above a float. Tighter than "0.249999", which
#: only tests a number near the boundary rather than the boundary itself.
def below(value: float) -> float:
    return math.nextafter(value, -math.inf)


def above(value: float) -> float:
    return math.nextafter(value, math.inf)


# --------------------------------------------------------------------------- #
# Band boundaries — the exact values the audit asks for
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "score,expected",
    [
        (0.000000, RiskBand.LOW),
        (0.100000, RiskBand.LOW),
        (0.249999, RiskBand.LOW),
        (0.250000, RiskBand.MEDIUM),
        (0.250001, RiskBand.MEDIUM),
        (0.400000, RiskBand.MEDIUM),
        (0.499999, RiskBand.MEDIUM),
        (0.500000, RiskBand.HIGH),
        (0.500001, RiskBand.HIGH),
        (0.700000, RiskBand.HIGH),
        (0.749999, RiskBand.HIGH),
        (0.750000, RiskBand.CRITICAL),
        (0.750001, RiskBand.CRITICAL),
        (1.000000, RiskBand.CRITICAL),
    ],
)
def test_band_boundaries_are_exact(score, expected):
    assert CONFIG.band_for(score) is expected


@pytest.mark.parametrize(
    "boundary,lower_band,upper_band",
    [
        (0.25, RiskBand.LOW, RiskBand.MEDIUM),
        (0.50, RiskBand.MEDIUM, RiskBand.HIGH),
        (0.75, RiskBand.HIGH, RiskBand.CRITICAL),
    ],
)
def test_each_boundary_is_inclusive_at_the_bottom_to_the_last_ulp(boundary, lower_band, upper_band):
    """The strongest form of the check: one representable step either side.

    ``0.249999`` proves a number near the boundary behaves; ``nextafter`` proves
    the boundary itself does.
    """
    assert CONFIG.band_for(below(boundary)) is lower_band
    assert CONFIG.band_for(boundary) is upper_band
    assert CONFIG.band_for(above(boundary)) is upper_band


def test_the_boundary_value_belongs_to_the_HIGHER_band():
    """Stated as its own assertion because it is the direction that matters.

    An inclusive-at-the-top rule would put 0.25 in LOW and turn a REVIEW into a
    PROCEED — an advisory layer failing quiet, which is the wrong direction for
    it to fail in.
    """
    for boundary in (CONFIG.band_medium_at, CONFIG.band_high_at, CONFIG.band_critical_at):
        assert BAND_ORDER[CONFIG.band_for(boundary)] > BAND_ORDER[CONFIG.band_for(below(boundary))]


# --------------------------------------------------------------------------- #
# Out-of-range: clamp in one place, reject in the other
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("points", [1.0, 1.0000001, 2.0, 10.0, 1e9])
def test_normalize_clamps_above_saturation_rather_than_raising(points):
    """Points legitimately exceed saturation; the index is defined as saturating."""
    assert normalize(points, config=CONFIG) == 1.0


@pytest.mark.parametrize("points", [0.0, -0.0, -1e-9, -5.0])
def test_normalize_floors_at_zero(points):
    assert normalize(points, config=CONFIG) == 0.0


def test_normalize_never_returns_nan_or_infinity():
    for points in (0.0, 1e-300, 1e300, float("inf")):
        value = normalize(points, config=CONFIG)
        assert 0.0 <= value <= 1.0
        assert not math.isnan(value)


@pytest.mark.parametrize("score", [-0.000001, -0.1, -1.0, 1.000001, 1.5, 2.0])
def test_an_assessment_rejects_a_score_outside_the_range(score):
    """A score outside [0,1] reaching the model means normalization was bypassed.

    Clamping here would silently accept the bypass and return a plausible
    assessment built on an invented number.
    """
    from tests.test_risk_models import _assessment

    with pytest.raises(ValidationError):
        _assessment(score=score)


def test_the_two_out_of_range_policies_are_genuinely_different():
    """Documents the asymmetry as a behavioural fact, not a comment.

    Same out-of-range input: ``normalize`` absorbs it, the model refuses it.
    """
    assert normalize(5.0, config=CONFIG) == 1.0
    from tests.test_risk_models import _assessment

    with pytest.raises(ValidationError):
        _assessment(score=5.0)


# --------------------------------------------------------------------------- #
# Review threshold — the operator, stated explicitly
# --------------------------------------------------------------------------- #
def _flagged(score: float, config: RiskConfig = CONFIG) -> bool:
    """The exact predicate the evaluation harness applies. Restated here so a
    change to it breaks this file rather than silently moving every rate."""
    return score >= config.review_threshold


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.000000, False),
        (0.249999, False),
        (0.250000, True),
        (0.250001, True),
        (1.000000, True),
    ],
)
def test_the_review_threshold_predicate_is_greater_than_or_equal(score, expected):
    assert _flagged(score) is expected


def test_the_review_threshold_is_inclusive_to_the_last_ulp():
    threshold = CONFIG.review_threshold
    assert _flagged(below(threshold)) is False
    assert _flagged(threshold) is True
    assert _flagged(above(threshold)) is True


def test_the_harness_uses_the_same_predicate_this_file_pins():
    """Guards against the analysis and the engine drifting apart.

    ``compute_metrics`` must flag exactly the scores ``_flagged`` does; a
    harness using ``>`` while the bands use ``>=`` would report a detection rate
    for an operating point the engine does not have.
    """
    from services.risk_engine.evaluation import compute_metrics
    from services.risk_engine.scenarios import RiskLabel
    from tests.test_risk_evaluation import outcome

    threshold = CONFIG.review_threshold
    for score in (below(threshold), threshold, above(threshold)):
        metrics = compute_metrics([outcome("r", RiskLabel.RISKY, score)], config=CONFIG)
        assert (metrics.risky_flagged == 1) is _flagged(score)


def test_the_threshold_coincides_with_the_medium_band_boundary():
    """A separate operating point would let the reported rates be measured
    somewhere the engine never operates."""
    assert CONFIG.review_threshold == CONFIG.band_medium_at
    threshold = CONFIG.review_threshold
    assert CONFIG.band_for(below(threshold)) is RiskBand.LOW
    assert CONFIG.band_for(threshold) is RiskBand.MEDIUM


def test_flagged_and_not_proceeding_are_the_same_condition():
    """ "At or above the review threshold" and "the engine stopped saying
    PROCEED" must be one condition, not two that happen to agree today."""
    for score in (0.0, 0.1, below(0.25), 0.25, 0.3, 0.5, 0.75, 1.0):
        recommendation = CONFIG.recommendation_for(CONFIG.band_for(score))
        assert _flagged(score) is (recommendation is not RiskRecommendation.PROCEED)
