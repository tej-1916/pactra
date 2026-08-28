"""The risk vocabulary must be incapable of being mistaken for authority.

These are type-level tests. They assert things the engine cannot do because the
models will not let it, rather than things it happens not to do today.
"""

from __future__ import annotations

import uuid

import pytest
from packages.schemas.domain import PolicyOutcome
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from pydantic import ValidationError
from services.risk_engine.models import (
    BAND_ORDER,
    DataQuality,
    FeatureSource,
    FeatureUnavailableReason,
    FeatureValue,
    RiskAssessment,
    RiskBand,
    RiskFactor,
    RiskRecommendation,
)


def _quality(**overrides) -> DataQuality:
    base = dict(
        history_available=False,
        history_observations=0,
        history_scope="authenticated_merchant",
        cold_start=True,
        features_available=5,
        features_unavailable=1,
        audit_chain_verified=True,
    )
    base.update(overrides)
    return DataQuality(**base)


def _assessment(**overrides) -> RiskAssessment:
    base = dict(
        mission_id=uuid.uuid4(),
        score=0.4,
        raw_points=0.4,
        saturation_points=1.0,
        band=RiskBand.MEDIUM,
        recommendation=RiskRecommendation.REVIEW,
        engine_version="pactra-risk-v1",
        model_type="DETERMINISTIC_HEURISTIC",
        model_version="heuristic-v1",
        data_quality=_quality(),
    )
    base.update(overrides)
    return RiskAssessment(**base)


# --------------------------------------------------------------------------- #
# The vocabularies must not overlap
# --------------------------------------------------------------------------- #
def test_recommendations_never_reuse_the_policy_vocabulary():
    """ALLOW and DENY belong to the deterministic engine and nothing else.

    If a risk recommendation could spell ALLOW, a downstream branch on a string
    could not tell an adjudication from advice.
    """
    policy_words = {outcome.value for outcome in PolicyOutcome}
    risk_words = {recommendation.value for recommendation in RiskRecommendation}
    assert policy_words.isdisjoint(risk_words), (
        f"risk recommendations overlap the policy vocabulary: {sorted(policy_words & risk_words)}"
    )


def test_critical_band_is_not_a_denial():
    """CRITICAL is the loudest advice, and advice is all it is."""
    assert RiskBand.CRITICAL.value not in {outcome.value for outcome in PolicyOutcome}
    assert BAND_ORDER[RiskBand.CRITICAL] > BAND_ORDER[RiskBand.LOW]


def test_every_band_is_ordered():
    assert set(BAND_ORDER) == set(RiskBand)
    assert sorted(BAND_ORDER.values()) == list(range(len(RiskBand)))


# --------------------------------------------------------------------------- #
# An assessment cannot claim authority
# --------------------------------------------------------------------------- #
def test_advisory_flag_cannot_be_turned_off():
    """``advisory`` is a Literal[True]: there is no non-advisory assessment."""
    with pytest.raises(ValidationError):
        _assessment(advisory=False)


def test_score_semantics_cannot_be_restated_as_a_probability():
    with pytest.raises(ValidationError):
        _assessment(score_semantics="FRAUD_PROBABILITY")


def test_assessment_rejects_unknown_fields():
    """No caller can smuggle an authorization or an override onto an assessment."""
    for hostile in (
        {"authorization_id": str(uuid.uuid4())},
        {"final_decision": "ALLOW"},
        {"override_policy": True},
        {"capability": "payment.execute"},
    ):
        with pytest.raises(ValidationError):
            _assessment(**hostile)


def test_assessment_has_no_field_that_could_authorize_anything():
    """A structural audit of the field list, not a spot check."""
    forbidden = {
        "authorization_id",
        "nonce",
        "transaction_digest",
        "capability",
        "capabilities",
        "final_decision",
        "decision",
        "approved",
        "allow",
        "deny",
    }
    present = set(RiskAssessment.model_fields)
    assert forbidden.isdisjoint(present), sorted(forbidden & present)


def test_score_is_bounded_by_the_schema():
    with pytest.raises(ValidationError):
        _assessment(score=1.4)
    with pytest.raises(ValidationError):
        _assessment(score=-0.1)


def test_only_a_digest_prefix_is_carried_never_the_whole_digest():
    """The assessment names the transaction; it does not copy the commitment."""
    assert "transaction_digest" not in RiskAssessment.model_fields
    assert "transaction_digest_prefix" in RiskAssessment.model_fields


# --------------------------------------------------------------------------- #
# Audit payload safety
# --------------------------------------------------------------------------- #
def test_audit_payload_carries_codes_not_observations():
    """A ledger reader learns the verdict, not the mission's contents."""
    assessment = _assessment(
        factors=[
            RiskFactor(
                code="AMOUNT_NEAR_HARD_LIMIT",
                feature="amount_to_hard_limit_ratio",
                contribution=0.12,
                weight=0.15,
                observed=0.96,
                explanation="the amount is 96% of the hard limit",
            )
        ]
    )
    payload = assessment.audit_payload()
    assert payload["factor_codes"] == ["AMOUNT_NEAR_HARD_LIMIT"]
    assert payload["advisory"] is True
    assert payload["score_semantics"] == "NORMALIZED_RISK_INDEX"

    flat = repr(payload)
    # No observed value, no feature name, no weight table.
    assert "0.96" not in flat
    assert "amount_to_hard_limit_ratio" not in flat
    assert "weight" not in flat


def test_audit_payload_is_json_safe():
    """The ledger canonicalizes payloads; a non-serializable value breaks a chain."""
    import json

    json.dumps(_assessment().audit_payload())


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #
def test_unavailable_feature_is_not_zero():
    """The distinction the whole engine depends on."""
    feature = FeatureValue(
        name="merchant_failed_payment_ratio",
        value=None,
        source=FeatureSource.PAYMENT_INTENT_ROW,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        available=False,
        unavailable_reason=FeatureUnavailableReason.INSUFFICIENT_HISTORY,
        source_detail="prior payments",
    )
    assert feature.numeric is None
    assert feature.value != 0.0


def test_available_feature_exposes_a_float():
    feature = FeatureValue(
        name="merchant_trust",
        value=0.9,
        source=FeatureSource.MERCHANT_REGISTRY,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        source_detail="registry",
    )
    assert feature.numeric == pytest.approx(0.9)


def test_feature_values_are_frozen():
    """A measured value must not be editable after extraction."""
    feature = FeatureValue(
        name="merchant_trust",
        value=0.9,
        source=FeatureSource.MERCHANT_REGISTRY,
        authority=AuthorityLevel.TRUSTED_INTERNAL_SERVICE,
        trust=TrustLevel.TRUSTED,
        source_detail="registry",
    )
    with pytest.raises(ValidationError):
        feature.value = 0.1


def test_a_factor_must_contribute_something():
    """A zero-contribution factor is noise in an explanation."""
    with pytest.raises(ValidationError):
        RiskFactor(
            code="X",
            feature="y",
            contribution=0.0,
            weight=0.1,
            explanation="nothing",
        )


def test_a_factor_cannot_reduce_risk():
    """A negative contribution would let a benign signal cancel a hostile one."""
    with pytest.raises(ValidationError):
        RiskFactor(
            code="X",
            feature="y",
            contribution=-0.2,
            weight=0.1,
            explanation="reassuring",
        )


def test_factor_codes_are_machine_stable():
    with pytest.raises(ValidationError):
        RiskFactor(
            code="lower case code",
            feature="y",
            contribution=0.1,
            weight=0.1,
            explanation="x",
        )


def test_data_quality_never_reports_a_user_scope():
    """PACTRA has no user identity; a user-scoped baseline cannot be claimed."""
    quality = _quality()
    assert "user" not in quality.history_scope
