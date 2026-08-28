"""An explanation must be an account of the score, not a story beside it."""

from __future__ import annotations

import pytest
from services.risk_engine.config import DEFAULT_RISK_CONFIG
from services.risk_engine.explain import (
    build_explanation,
    count_availability,
    render_factor,
    render_scope_note,
    render_verdict,
)
from services.risk_engine.heuristic import normalize, score
from services.risk_engine.models import DataQuality, RiskBand, RiskFactor, RiskRecommendation
from tests.test_risk_heuristic import feature, features

CONFIG = DEFAULT_RISK_CONFIG


def _quality(**overrides) -> DataQuality:
    base = dict(
        history_available=True,
        history_observations=6,
        history_scope="authenticated_merchant",
        cold_start=False,
        features_available=20,
        features_unavailable=3,
        audit_chain_verified=True,
    )
    base.update(overrides)
    return DataQuality(**base)


def _explain(payload, quality=None, policy="ALLOW"):
    factors, points = score(payload, config=CONFIG)
    value = normalize(points, config=CONFIG)
    band = CONFIG.band_for(value)
    return (
        build_explanation(
            score=value,
            band=band,
            recommendation=CONFIG.recommendation_for(band),
            factors=factors,
            quality=quality or _quality(),
            policy_decision=policy,
        ),
        factors,
        value,
    )


# --------------------------------------------------------------------------- #
# Every line is backed by a number
# --------------------------------------------------------------------------- #
def test_every_factor_appears_in_the_explanation():
    payload = features(
        amount_to_hard_limit_ratio=0.96,
        authorization_replay_attempts=1,
        merchant_known=False,
    )
    lines, factors, _ = _explain(payload)
    joined = "\n".join(lines)
    for factor in factors:
        assert factor.code in joined


def test_the_explanation_states_no_reason_the_scorer_did_not_produce():
    """The check that would catch a hallucinated risk reason.

    Every non-narrative line must name a factor the scorer emitted. The fixed
    narrative lines are enumerated explicitly, so a NEW unexplained sentence
    appearing in the explanation fails here.
    """
    payload = features(amount_to_hard_limit_ratio=0.96)
    lines, factors, _ = _explain(payload)
    codes = {factor.code for factor in factors}

    narrative_markers = (
        "risk index",
        "prior observation",
        "no prior observations",
        "behavioural baseline",
        "feature(s) measured",
        "scope:",
        "deterministic policy decision",
        "audit chain did NOT verify",
        "no risk factors contributed",
        "this counts kernel-written records",
    )
    for line in lines:
        stripped = line.strip()
        if any(marker in stripped for marker in narrative_markers):
            continue
        assert any(code in stripped for code in codes), f"unexplained line: {stripped!r}"


def test_contributions_printed_sum_to_the_score():
    """A reader can add the column up and get the raw points."""
    payload = features(
        amount_to_hard_limit_ratio=0.96, provider_timeout_events=2, payment_attempts=3
    )
    factors, points = score(payload, config=CONFIG)
    printed = [render_factor(f).split()[0] for f in factors]
    assert sum(float(value.lstrip("+")) for value in printed) == pytest.approx(points, abs=5e-3)


def test_an_empty_explanation_says_so_rather_than_being_silent():
    lines, factors, _ = _explain({})
    assert factors == []
    assert any("no risk factors contributed" in line for line in lines)


# --------------------------------------------------------------------------- #
# The disclosures that must always be present
# --------------------------------------------------------------------------- #
def test_the_verdict_never_reads_as_a_decision():
    line = render_verdict(
        score=0.9, band=RiskBand.CRITICAL, recommendation=RiskRecommendation.ESCALATE
    )
    assert "authorizes nothing" in line
    assert "NOT a fraud probability" in line
    assert "ALLOW" not in line
    assert "DENY" not in line


def test_the_scope_note_discloses_the_absence_of_user_history_every_time():
    """The most conspicuous thing a risk engine is expected to know, and cannot."""
    note = render_scope_note()
    assert "no user identity" in note
    for payload in ({}, features(amount_to_hard_limit_ratio=0.99)):
        lines, _, _ = _explain(payload)
        assert note in lines


def test_the_policy_decision_is_reported_as_unchanged():
    lines, _, _ = _explain(features(authorization_replay_attempts=1), policy="ALLOW")
    tail = "\n".join(lines)
    assert "ALLOW" in tail
    assert "unchanged by, and not derived from, this assessment" in tail


def test_a_critical_score_does_not_claim_to_have_denied_anything():
    lines, _, value = _explain(
        features(authorization_replay_attempts=1, transaction_binding_failures=1),
        policy="ALLOW",
    )
    assert CONFIG.band_for(value) is RiskBand.CRITICAL
    joined = "\n".join(lines)
    assert "DENY" not in joined
    assert "blocked" not in joined.lower()


# --------------------------------------------------------------------------- #
# Data quality is stated, not only when it is bad
# --------------------------------------------------------------------------- #
def test_cold_start_is_stated_and_explicitly_not_scored():
    lines, factors, value = _explain(
        {}, quality=_quality(cold_start=True, history_available=False, history_observations=0)
    )
    assert value == 0.0
    joined = "\n".join(lines)
    assert "no prior observations" in joined
    assert "not evidence of risk" in joined


def test_thin_history_is_distinguished_from_cold_start():
    lines, _, _ = _explain(
        {}, quality=_quality(cold_start=False, history_available=False, history_observations=2)
    )
    joined = "\n".join(lines)
    assert "2 prior observation" in joined
    assert "below the minimum" in joined


def test_healthy_history_is_stated_too():
    lines, _, _ = _explain({}, quality=_quality())
    assert any("baseline computed from 6 prior observation" in line for line in lines)


def test_an_unverified_audit_chain_is_called_out():
    lines, _, _ = _explain({}, quality=_quality(audit_chain_verified=False))
    assert any("did NOT verify" in line for line in lines)


def test_untrusted_evidence_provenance_is_rendered():
    line = render_factor(
        RiskFactor(
            code="MERCHANT_IDENTITY_MISMATCH_HISTORY",
            feature="merchant_identity_mismatch_events",
            contribution=0.6,
            weight=0.6,
            observed=1,
            explanation="spoofed once",
            derived_from_untrusted_evidence=True,
        )
    )
    assert "the record is trusted, the behaviour it describes was not" in line


def test_count_availability_matches_the_feature_map():
    payload = {
        **features(merchant_trust=0.9),
        "merchant_failed_payment_ratio": feature(
            "merchant_failed_payment_ratio", None, available=False
        ),
    }
    assert count_availability(payload) == (1, 1)
