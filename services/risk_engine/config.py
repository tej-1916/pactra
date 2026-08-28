"""Server-owned scoring configuration. Every weight has a written reason.

WHY THE WEIGHTS LIVE HERE AND NOWHERE ELSE
------------------------------------------
A scoring rule scattered across the code that applies it is a scoring rule
nobody can audit. Every threshold, ramp bound and weight in ``heuristic-v1`` is
declared in this one module, as a frozen model, with the rationale attached to
the constant rather than to a commit message.

Frozen and server-owned is a security property, not tidiness. ``RiskConfig`` is
``frozen=True`` with ``extra="forbid"``, there is no setter, no mutation helper,
and no API surface that accepts one. A caller — including a caller holding a
forged ``CapabilitySet`` — cannot widen a threshold to make a risky transaction
score low, because there is no code path through which a config reaches the
engine from outside the process. ``assess_mission`` takes an optional ``config``
argument for TESTS and for the evaluation harness; the HTTP routes never pass
one and never expose one, which a test asserts by parsing the route module.

FOUR WEIGHT TIERS, NOT NINETEEN MAGIC NUMBERS
---------------------------------------------
Each factor is assigned one of four documented tiers rather than a bespoke
constant. Nineteen independent decimals would be nineteen unexplainable
choices; four tiers force the real question — *how strong is this evidence?* —
to be answered on a scale a reader can hold in their head.

    WEAK      0.05  a mild signal, or one the deterministic kernel already owns
    MODERATE  0.15  a genuine concern on its own
    STRONG    0.35  evidence of adversarial or malfunctioning behaviour
    SEVERE    0.60  behaviour with no benign explanation

``SATURATION_POINTS = 1.0`` then falls out of the tiers rather than being picked:
one SEVERE signal reads 0.60 (HIGH — a human should look), two independent
SEVERE signals read 1.00 (CRITICAL — escalate). That is the intended calibration
of the BANDS, and it is the only calibration claimed. It is emphatically not a
calibration of probability.

RAMPS, NOT CLIFFS
-----------------
Factors grade with ``ramp(value, lo, hi)`` instead of firing on a threshold
comparison. Three reasons, in order of importance:

* **Monotonicity is testable.** A cliff makes "more of a risky thing never
  lowers its own contribution" trivially true but uninformative; a ramp makes it
  a real property, and ``tests/test_risk_properties.py`` checks it with
  Hypothesis across the whole input range.
* **A cliff invites gaming.** ``amount == 0.8999 * hard_limit`` scoring zero
  while ``0.9001`` scores full weight is a threshold an adversary can sit just
  under.
* **The explanation gets better.** "96% of the hard limit — 0.84 of the
  available weight" says more than "exceeded the 90% threshold".

WHAT IS DELIBERATELY WEIGHTED *LOW*
-----------------------------------
Exceeding the user's soft budget is WEAK, not MODERATE, even though it is the
most conspicuous number in a mission. The deterministic policy engine already
turns it into ``REQUIRE_APPROVAL`` — an actual control, with actual authority.
Scoring it heavily here would double-count a control PACTRA already has and
would let the advisory layer's number drift toward looking like the decision.
The risk engine is most useful where the deterministic kernel is silent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from services.risk_engine.models import RiskBand, RiskRecommendation

#: Identifies the engine as a whole: extraction + scoring + explanation.
ENGINE_VERSION = "pactra-risk-v1"

#: Identifies the SCORING RULES specifically. Bump whenever a weight, ramp bound
#: or factor changes in a way that could move a score, so two assessments can be
#: compared and a difference attributed to the mission rather than to the rules.
HEURISTIC_VERSION = "heuristic-v1"

#: What kind of model produced the score. A pinned string so a consumer can tell
#: a heuristic index from a model output without inspecting the version.
MODEL_TYPE_HEURISTIC = "DETERMINISTIC_HEURISTIC"


# --------------------------------------------------------------------------- #
# Weight tiers
# --------------------------------------------------------------------------- #
#: A mild signal, or one the deterministic kernel already enforces. Present so
#: the explanation can mention it; too small to move a band on its own.
WEAK = 0.05

#: A genuine concern. Three of these reach MEDIUM; they do not reach HIGH.
MODERATE = 0.15

#: Evidence of adversarial or malfunctioning behaviour. One reaches MEDIUM, two
#: reach HIGH.
STRONG = 0.35

#: Behaviour with no benign explanation. One reaches HIGH on its own; two reach
#: CRITICAL. Reserved for signals whose mere presence is the finding.
SEVERE = 0.60


def ramp(value: float, lo: float, hi: float) -> float:
    """Linear 0→1 interpolation of ``value`` across ``[lo, hi]``, clamped.

    Returns 0.0 at or below ``lo`` and 1.0 at or above ``hi``. Monotonically
    non-decreasing in ``value`` by construction, which is the property the
    factor contributions inherit and the property the scoring rests on:
    *more of a risky thing never contributes less risk*.

    ``hi <= lo`` is rejected rather than silently treated as a step function. A
    degenerate ramp is a configuration mistake, and turning it into a cliff at
    runtime would hide the mistake behind behaviour that looks deliberate.
    """
    if hi <= lo:
        raise ValueError(f"ramp requires hi > lo; got lo={lo!r}, hi={hi!r}")
    if value <= lo:
        return 0.0
    if value >= hi:
        return 1.0
    return (value - lo) / (hi - lo)


class RiskConfig(BaseModel):
    """Every tunable in ``heuristic-v1``, frozen and server-owned.

    Deliberately a flat model rather than nested groups: a flat surface is one a
    reader can diff against the factor table in ``heuristic.py`` line by line,
    and a test asserts that every declared factor reads at least one field from
    here — so a weight added without a factor, or a factor with a hardcoded
    number, both fail rather than drift.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # ---- normalization -------------------------------------------------- #
    #: Accumulated points at which the index reads 1.0. Derived from the tiers:
    #: two SEVERE signals (0.60 + 0.60) saturate comfortably, one does not.
    saturation_points: float = Field(default=1.0, gt=0.0)

    # ---- band boundaries ------------------------------------------------ #
    #: Chosen so a single MODERATE concern cannot leave LOW on its own, one
    #: STRONG signal reaches MEDIUM, one SEVERE reaches HIGH, and two SEVERE
    #: reach CRITICAL. The bands are what these numbers calibrate — nothing here
    #: calibrates a probability.
    band_medium_at: float = Field(default=0.25, gt=0.0, lt=1.0)
    band_high_at: float = Field(default=0.50, gt=0.0, lt=1.0)
    band_critical_at: float = Field(default=0.75, gt=0.0, lt=1.0)

    #: The score at and above which the advisory layer stops saying PROCEED.
    #: Used as the operating point for the evaluation harness's detection and
    #: false-positive rates. Equal to ``band_medium_at`` by construction: a
    #: separate number would let the reported rates be computed at an operating
    #: point the system does not actually use.
    review_threshold: float = Field(default=0.25, gt=0.0, le=1.0)

    # ---- amount --------------------------------------------------------- #
    #: A transaction consuming most of the absolute ceiling leaves no headroom:
    #: it is where price-mutation attacks aim, because a small upward edit is
    #: the difference between "approved" and "over the limit". Ramp starts at
    #: three quarters of the ceiling and saturates at the ceiling itself.
    #: Anything ABOVE the ceiling is DENIED deterministically and never reaches
    #: this factor at all.
    amount_hard_limit_weight: float = Field(default=MODERATE, gt=0.0)
    amount_hard_limit_ramp_lo: float = Field(default=0.75, ge=0.0)
    amount_hard_limit_ramp_hi: float = Field(default=1.00, gt=0.0)

    #: Exceeding the soft budget is already an enforced control
    #: (REQUIRE_APPROVAL). WEAK on purpose — see the module docstring on
    #: double-counting policy authority. Saturates at 1.5x the soft budget.
    amount_soft_budget_weight: float = Field(default=WEAK, gt=0.0)
    amount_soft_budget_ramp_lo: float = Field(default=1.00, ge=0.0)
    amount_soft_budget_ramp_hi: float = Field(default=1.50, gt=0.0)

    # ---- merchant ------------------------------------------------------- #
    #: An ADVISORY preference, deliberately distinct from the user's
    #: ``min_merchant_trust`` policy field. The policy field is authoritative and
    #: enforced; this one only colours a recommendation. Keeping them separate is
    #: what stops the advisory layer from appearing to raise a user's policy.
    preferred_merchant_trust: float = Field(default=0.80, ge=0.0, le=1.0)
    merchant_trust_weight: float = Field(default=MODERATE, gt=0.0)

    #: An authenticated but UNREGISTERED merchant has no reputation at all. This
    #: is a reputation fact the server owns, not an absence of behavioural
    #: history — which is why it scores while cold start does not. Exclusive
    #: with the trust-shortfall factor: an unknown merchant's trust is 0.0 by
    #: construction, so scoring both would count one fact twice.
    merchant_unknown_weight: float = Field(default=STRONG, gt=0.0)

    #: A merchant that has ever asserted an identity other than the one it
    #: authenticated as is behaving adversarially. There is no benign reading,
    #: so a single occurrence earns full weight.
    merchant_identity_mismatch_weight: float = Field(default=SEVERE, gt=0.0)
    merchant_identity_mismatch_saturates_at: float = Field(default=1.0, gt=0.0)

    #: Merchant attempts to write user-policy state (AUTHORITY_ESCALATION).
    #: STRONG rather than SEVERE: the lattice refuses these deterministically
    #: and a probing merchant is not the same as one that succeeded — but a
    #: pattern of probing is worth surfacing.
    merchant_escalation_weight: float = Field(default=STRONG, gt=0.0)
    merchant_escalation_saturates_at: float = Field(default=2.0, gt=0.0)

    #: Prior settled-vs-failed payments with this merchant. Gated: below
    #: ``min_merchant_payment_history`` observations the ratio is noise, so the
    #: feature reports UNAVAILABLE rather than a number.
    merchant_failure_ratio_weight: float = Field(default=MODERATE, gt=0.0)
    merchant_failure_ratio_ramp_lo: float = Field(default=0.20, ge=0.0)
    merchant_failure_ratio_ramp_hi: float = Field(default=0.60, gt=0.0)
    min_merchant_payment_history: int = Field(default=3, ge=1)

    # ---- authorization -------------------------------------------------- #
    #: A replay attempt against this mission's authorization. The kernel refuses
    #: it deterministically; its OCCURRENCE is nonetheless the clearest evidence
    #: available that somebody is attacking this specific transaction.
    replay_attempt_weight: float = Field(default=SEVERE, gt=0.0)
    replay_attempt_saturates_at: float = Field(default=1.0, gt=0.0)

    #: A transaction-binding failure means the transaction changed after
    #: approval. Same reasoning as replay: refused deterministically, and its
    #: occurrence has no benign explanation.
    binding_failure_weight: float = Field(default=SEVERE, gt=0.0)
    binding_failure_saturates_at: float = Field(default=1.0, gt=0.0)

    #: Authority-escalation attempts recorded on THIS mission, from any source.
    #: Overlaps the merchant-scoped factor by design: one is "this counterparty
    #: has a history", the other is "this transaction is under attack now".
    mission_escalation_weight: float = Field(default=STRONG, gt=0.0)
    mission_escalation_saturates_at: float = Field(default=2.0, gt=0.0)

    #: Consuming an authorization in the last fifth of its window is the shape
    #: of a held or stale approval. WEAK: expiry is enforced deterministically,
    #: so this only adds colour.
    authorization_age_weight: float = Field(default=WEAK, gt=0.0)
    authorization_age_ramp_lo: float = Field(default=0.80, ge=0.0)
    authorization_age_ramp_hi: float = Field(default=1.00, gt=0.0)

    # ---- payment -------------------------------------------------------- #
    #: Retry pressure. One attempt is the normal case and scores nothing; the
    #: ramp starts above it.
    payment_attempt_weight: float = Field(default=MODERATE, gt=0.0)
    payment_attempt_ramp_lo: float = Field(default=1.0, ge=0.0)
    payment_attempt_ramp_hi: float = Field(default=4.0, gt=0.0)

    #: Provider timeouts leave the payment in the uncertain state. A network is
    #: allowed one bad moment; a pattern is a different claim.
    provider_timeout_weight: float = Field(default=MODERATE, gt=0.0)
    provider_timeout_saturates_at: float = Field(default=2.0, gt=0.0)

    #: A provider response that does not describe the transaction PACTRA
    #: requested. The strongest payment-layer anomaly available, because the
    #: response was well-formed and authenticated at the transport layer and
    #: STILL described something else.
    provider_mismatch_weight: float = Field(default=STRONG, gt=0.0)
    provider_mismatch_saturates_at: float = Field(default=1.0, gt=0.0)

    #: An idempotency key presented for a materially different request.
    idempotency_conflict_weight: float = Field(default=STRONG, gt=0.0)
    idempotency_conflict_saturates_at: float = Field(default=1.0, gt=0.0)

    #: Duplicate and out-of-order webhooks are NORMAL under at-least-once
    #: delivery. Only volume carries information, so the weight is WEAK and the
    #: ramp is wide.
    webhook_anomaly_weight: float = Field(default=WEAK, gt=0.0)
    webhook_anomaly_saturates_at: float = Field(default=3.0, gt=0.0)

    #: One reconciliation is routine recovery and scores nothing; the ramp
    #: starts above it. Repeated reconciliation of one payment is not routine.
    reconciliation_weight: float = Field(default=WEAK, gt=0.0)
    reconciliation_ramp_lo: float = Field(default=1.0, ge=0.0)
    reconciliation_ramp_hi: float = Field(default=3.0, gt=0.0)

    # ---- integrity ------------------------------------------------------ #
    #: The mission's own hash chain does not verify. SEVERE because every
    #: audit-derived feature above was then read from history that cannot be
    #: trusted — the assessment says so rather than scoring on quietly.
    audit_integrity_weight: float = Field(default=SEVERE, gt=0.0)

    #: Proportion of this mission's offers the kernel rejected. WEAK: a rejected
    #: offer is the kernel working, and a discerning policy naturally rejects
    #: some. Only a high proportion is mildly informative.
    invalid_offer_weight: float = Field(default=WEAK, gt=0.0)
    invalid_offer_ramp_lo: float = Field(default=0.34, ge=0.0)
    invalid_offer_ramp_hi: float = Field(default=1.00, gt=0.0)
    #: Below this many offers a "proportion rejected" is not a proportion.
    min_offers_for_ratio: int = Field(default=2, ge=1)

    # ---- anomaly (history-gated) ---------------------------------------- #
    #: Prior observations required before ANY behavioural baseline is computed.
    #: Below it the anomaly features report INSUFFICIENT_HISTORY and contribute
    #: nothing — a baseline from four points is a number, not a baseline.
    min_history_observations: int = Field(default=5, ge=2)

    #: How far above the merchant's historical median this transaction sits.
    #: Ramp starts at 1.5x — a half-again larger purchase is unremarkable — and
    #: saturates at 3x.
    amount_anomaly_weight: float = Field(default=MODERATE, gt=0.0)
    amount_anomaly_ramp_lo: float = Field(default=1.50, ge=0.0)
    amount_anomaly_ramp_hi: float = Field(default=3.00, gt=0.0)

    # ---- band → recommendation ------------------------------------------ #
    def recommendation_for(self, band: RiskBand) -> RiskRecommendation:
        """Map a band to the advisory action.

        A total function over the enum with no default branch: adding a band
        without deciding what to recommend for it is a ``KeyError`` at import
        of the first assessment, not a silent ``PROCEED``.
        """
        return _BAND_RECOMMENDATION[band]

    def band_for(self, score: float) -> RiskBand:
        """Bucket a normalized score. Boundaries are inclusive at the bottom."""
        if score >= self.band_critical_at:
            return RiskBand.CRITICAL
        if score >= self.band_high_at:
            return RiskBand.HIGH
        if score >= self.band_medium_at:
            return RiskBand.MEDIUM
        return RiskBand.LOW


#: Deliberately module-level and exhaustive over ``RiskBand``.
_BAND_RECOMMENDATION: dict[RiskBand, RiskRecommendation] = {
    RiskBand.LOW: RiskRecommendation.PROCEED,
    RiskBand.MEDIUM: RiskRecommendation.REVIEW,
    RiskBand.HIGH: RiskRecommendation.REQUIRE_STRONGER_APPROVAL,
    RiskBand.CRITICAL: RiskRecommendation.ESCALATE,
}


#: The one configuration the running system uses. Frozen, module-owned, and
#: never reachable from a request: no route accepts a config, and there is no
#: function anywhere that replaces this binding.
DEFAULT_RISK_CONFIG = RiskConfig()
