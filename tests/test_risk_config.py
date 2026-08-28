"""Weights are server-owned, ordered, and complete. Proved, not asserted in prose.

The config is the only place a scoring number exists, so these tests are what
stop it from drifting into being a place a scoring number *usually* exists.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError
from services.risk_engine.config import (
    DEFAULT_RISK_CONFIG,
    MODERATE,
    SEVERE,
    STRONG,
    WEAK,
    RiskConfig,
    ramp,
)
from services.risk_engine.heuristic import FACTOR_RULES, Shape
from services.risk_engine.models import RiskBand, RiskRecommendation


# --------------------------------------------------------------------------- #
# Server ownership
# --------------------------------------------------------------------------- #
def test_config_is_frozen():
    """A caller holding a config cannot widen a threshold in place."""
    with pytest.raises(ValidationError):
        DEFAULT_RISK_CONFIG.band_medium_at = 0.99


def test_config_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        RiskConfig(merchant_supplied_weight=1.0)


def test_config_module_exposes_no_mutator():
    """There is no sanctioned way to replace the running configuration.

    A setter would be the exact hole a forged capability would aim at, so the
    absence is checked rather than assumed.
    """
    import services.risk_engine.config as module

    suspicious = [
        name
        for name in dir(module)
        if any(
            name.startswith(prefix)
            for prefix in ("set_", "update_", "configure_", "override_", "reload_")
        )
    ]
    assert suspicious == [], suspicious


def test_weight_tiers_are_ordered():
    """The four tiers must stay a scale, not four similar numbers."""
    assert 0 < WEAK < MODERATE < STRONG < SEVERE


def test_saturation_is_reachable_by_two_severe_signals_and_not_by_one():
    """The stated calibration of the BANDS, checked rather than described."""
    config = DEFAULT_RISK_CONFIG
    assert SEVERE < config.saturation_points, "one severe signal must not saturate"
    assert 2 * SEVERE >= config.saturation_points, "two severe signals must saturate"


# --------------------------------------------------------------------------- #
# ramp
# --------------------------------------------------------------------------- #
def test_ramp_is_clamped_at_both_ends():
    assert ramp(-5.0, 0.0, 1.0) == 0.0
    assert ramp(0.0, 0.0, 1.0) == 0.0
    assert ramp(1.0, 0.0, 1.0) == 1.0
    assert ramp(99.0, 0.0, 1.0) == 1.0


def test_ramp_is_linear_between_the_bounds():
    assert ramp(0.5, 0.0, 1.0) == pytest.approx(0.5)
    assert ramp(0.875, 0.75, 1.0) == pytest.approx(0.5)


def test_ramp_is_monotonic():
    previous = -1.0
    for step in range(0, 101):
        value = ramp(step / 50.0, 0.5, 1.5)
        assert value >= previous
        previous = value


def test_a_degenerate_ramp_is_a_configuration_error_not_a_cliff():
    """Silently becoming a step function would hide the mistake."""
    with pytest.raises(ValueError):
        ramp(1.0, 1.0, 1.0)
    with pytest.raises(ValueError):
        ramp(1.0, 2.0, 1.0)


# --------------------------------------------------------------------------- #
# Bands and recommendations
# --------------------------------------------------------------------------- #
def test_band_boundaries_are_ordered():
    config = DEFAULT_RISK_CONFIG
    assert 0 < config.band_medium_at < config.band_high_at < config.band_critical_at < 1


def test_band_for_covers_the_whole_range():
    config = DEFAULT_RISK_CONFIG
    assert config.band_for(0.0) is RiskBand.LOW
    assert config.band_for(config.band_medium_at) is RiskBand.MEDIUM
    assert config.band_for(config.band_high_at) is RiskBand.HIGH
    assert config.band_for(config.band_critical_at) is RiskBand.CRITICAL
    assert config.band_for(1.0) is RiskBand.CRITICAL


def test_band_for_is_monotonic():
    config = DEFAULT_RISK_CONFIG
    from services.risk_engine.models import BAND_ORDER

    previous = -1
    for step in range(0, 101):
        rank = BAND_ORDER[config.band_for(step / 100.0)]
        assert rank >= previous
        previous = rank


def test_every_band_maps_to_a_recommendation():
    """A band added without a recommendation must fail, not default to PROCEED."""
    for band in RiskBand:
        assert isinstance(DEFAULT_RISK_CONFIG.recommendation_for(band), RiskRecommendation)


def test_only_the_lowest_band_says_proceed():
    config = DEFAULT_RISK_CONFIG
    proceeding = [
        band for band in RiskBand if config.recommendation_for(band) is RiskRecommendation.PROCEED
    ]
    assert proceeding == [RiskBand.LOW]


def test_review_threshold_is_the_medium_boundary():
    """The reported operating point must be the one the engine actually uses.

    A separate number here would let the evaluation's detection and
    false-positive rates be computed at a threshold the system never applies.
    """
    config = DEFAULT_RISK_CONFIG
    assert config.review_threshold == config.band_medium_at


# --------------------------------------------------------------------------- #
# Every factor reads the config, and nothing else
# --------------------------------------------------------------------------- #
def test_every_factor_rule_names_real_config_fields():
    """A typo'd field name must fail here, not produce a silently different score."""
    for rule in FACTOR_RULES:
        for field in rule.config_fields():
            assert hasattr(DEFAULT_RISK_CONFIG, field), f"{rule.code} names missing {field}"
            assert isinstance(getattr(DEFAULT_RISK_CONFIG, field), (int, float))


def test_every_factor_has_the_bounds_its_shape_requires():
    for rule in FACTOR_RULES:
        if rule.shape is Shape.RATIO:
            assert rule.lo_field and rule.hi_field, rule.code
            lo = getattr(DEFAULT_RISK_CONFIG, rule.lo_field)
            hi = getattr(DEFAULT_RISK_CONFIG, rule.hi_field)
            assert hi > lo, f"{rule.code}: ramp bounds are not ordered"
        elif rule.shape is Shape.COUNT:
            assert rule.saturates_field, rule.code
            assert getattr(DEFAULT_RISK_CONFIG, rule.saturates_field) > 0
        elif rule.shape is Shape.SHORTFALL:
            assert rule.reference_field, rule.code
            assert getattr(DEFAULT_RISK_CONFIG, rule.reference_field) > 0
        else:
            assert rule.lo_field is None and rule.saturates_field is None, rule.code


def test_every_weight_is_one_of_the_four_declared_tiers():
    """Nineteen bespoke decimals would be nineteen unexplained choices."""
    tiers = {WEAK, MODERATE, STRONG, SEVERE}
    for rule in FACTOR_RULES:
        weight = getattr(DEFAULT_RISK_CONFIG, rule.weight_field)
        assert any(math.isclose(weight, tier) for tier in tiers), (
            f"{rule.code} uses weight {weight}, which is not one of the declared tiers"
        )


def test_factor_codes_are_unique():
    codes = [rule.code for rule in FACTOR_RULES]
    assert len(codes) == len(set(codes))


def test_soft_budget_is_weighted_below_hard_limit():
    """The deterministic engine already enforces the soft budget.

    Weighting it heavily here would double-count a control PACTRA already has,
    and would drift the advisory number toward looking like the decision.
    """
    config = DEFAULT_RISK_CONFIG
    assert config.amount_soft_budget_weight < config.amount_hard_limit_weight
