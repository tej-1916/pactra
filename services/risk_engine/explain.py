"""Explanation rendering. Assembled from contributions, never from a model.

THE RULE, AND WHY IT IS NOT NEGOTIABLE
---------------------------------------
Every line of an explanation is derived from a ``RiskFactor`` the scorer
actually produced, or from a ``DataQuality`` count the extractor actually
measured. Nothing here calls an LLM, and nothing here can state a reason the
arithmetic did not produce.

That is not stylistic caution. An explanation is the only part of a risk score a
human reads, so it is the only part that can lie convincingly. A plausible
sentence about a merchant's "unusual pattern" attached to a score that was
actually driven by an amount ratio does not merely mislead — it teaches the
reader to trust the next such sentence. So the honest construction is the
mechanical one: `sum(factor.contribution) == raw_points` is asserted by a test,
and every rendered line names the factor and the number behind it.

WHAT AN EMPTY EXPLANATION MEANS
--------------------------------
A ``LOW`` assessment with no factors renders an explicit "no risk factors
contributed", not silence. Silence reads as "nothing was checked"; the engine
did check, and found nothing, which is a different and more useful statement.

WHAT GETS SAID EVEN THOUGH IT SCORED NOTHING
---------------------------------------------
Cold start and insufficient history contribute zero points — by design, since
absence of history is not evidence of malice. They are nonetheless stated in
every explanation that has them, because "0.08, LOW" from a merchant with five
hundred prior transactions and "0.08, LOW" from one seen for the first time are
the same number backed by very different amounts of knowledge, and a reader who
cannot tell them apart has been misled by omission.
"""

from __future__ import annotations

from services.risk_engine.models import (
    DataQuality,
    FeatureValue,
    RiskBand,
    RiskFactor,
    RiskRecommendation,
)

#: Prefix marking a line as provenance context rather than a scoring reason.
UNTRUSTED_EVIDENCE_NOTE = (
    "  (this counts kernel-written records OF untrusted behaviour; the record is "
    "trusted, the behaviour it describes was not)"
)


def render_factor(factor: RiskFactor) -> str:
    """One factor as a line: what it added, and why.

    The contribution is printed first because it is the part that is checkable.
    A reader can add the column up and get ``raw_points``.
    """
    line = f"+{factor.contribution:.3f}  {factor.code}: {factor.explanation}"
    if factor.derived_from_untrusted_evidence:
        line = f"{line}\n{UNTRUSTED_EVIDENCE_NOTE}"
    return line


def render_data_quality(quality: DataQuality) -> list[str]:
    """State what the assessment did and did not have to work with.

    Always emitted, including on a clean assessment. An explanation that only
    mentions data quality when it is poor lets a reader assume the baseline was
    solid every other time.
    """
    lines: list[str] = []
    if quality.cold_start:
        lines.append(
            "no prior observations exist for this merchant, so no behavioural "
            "baseline was computed and no anomaly factor could contribute — "
            "absence of history is not evidence of risk and is not scored as any"
        )
    elif not quality.history_available:
        lines.append(
            f"{quality.history_observations} prior observation(s) for this merchant, "
            "below the minimum required for a behavioural baseline; anomaly "
            "factors were skipped rather than estimated"
        )
    else:
        lines.append(
            f"behavioural baseline computed from {quality.history_observations} prior "
            f"observation(s), scoped by {quality.history_scope}"
        )

    if not quality.audit_chain_verified:
        lines.append(
            "the mission's audit chain did NOT verify — audit-derived features "
            "were read from history that cannot be trusted"
        )

    lines.append(
        f"{quality.features_available} feature(s) measured, "
        f"{quality.features_unavailable} unavailable"
    )
    return lines


def render_scope_note() -> str:
    """The standing disclosure about what PACTRA cannot baseline.

    Printed on every assessment rather than buried in documentation. The most
    conspicuous thing a transaction-risk engine is expected to know is how this
    purchase compares to the user's usual behaviour, and PACTRA cannot know that
    — there is no user identity in its data model. A reader who assumes it was
    considered has been misled, and the fix is to say so every time.
    """
    return (
        "scope: PACTRA has no user identity in its data model, so no per-user "
        "spending baseline, velocity, or behavioural deviation was computed or "
        "approximated. History is scoped by authenticated merchant only."
    )


def render_verdict(
    *,
    score: float,
    band: RiskBand,
    recommendation: RiskRecommendation,
) -> str:
    """The headline, worded so it cannot be mistaken for a decision."""
    return (
        f"risk index {score:.3f} ({band.value}) — advisory recommendation: "
        f"{recommendation.value}. This is a normalized risk index, NOT a fraud "
        "probability, and it authorizes nothing: the deterministic policy "
        "decision stands unchanged."
    )


def build_explanation(
    *,
    score: float,
    band: RiskBand,
    recommendation: RiskRecommendation,
    factors: list[RiskFactor],
    quality: DataQuality,
    policy_decision: str | None,
) -> list[str]:
    """The complete explanation, in reading order.

    Verdict, then the factors that produced it strongest-first, then what the
    engine had to work with, then the standing scope disclosure, then the
    authoritative decision it did not make.
    """
    lines = [render_verdict(score=score, band=band, recommendation=recommendation)]

    if factors:
        lines.extend(render_factor(factor) for factor in factors)
    else:
        lines.append(
            "no risk factors contributed: every configured factor was either "
            "below its threshold or had no data behind it"
        )

    lines.extend(render_data_quality(quality))
    lines.append(render_scope_note())

    if policy_decision is not None:
        lines.append(
            f"deterministic policy decision for this mission: {policy_decision} "
            "— unchanged by, and not derived from, this assessment"
        )
    return lines


def count_availability(features: dict[str, FeatureValue]) -> tuple[int, int]:
    """(available, unavailable). The denominator behind ``DataQuality``."""
    available = sum(1 for feature in features.values() if feature.available)
    return available, len(features) - available
