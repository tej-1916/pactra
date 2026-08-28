"""Typed risk vocabulary. Advisory by construction, not by promise.

THREE THINGS THIS MODULE MAKES STRUCTURALLY IMPOSSIBLE
------------------------------------------------------
1. **Risk cannot be mistaken for a decision.** ``RiskRecommendation`` has no
   ``ALLOW`` and no ``DENY``. Those words belong to
   ``packages.schemas.domain.PolicyOutcome`` and to the deterministic engine
   that owns them. A report, a log line, or an API response carrying a risk
   recommendation therefore cannot be misread as an adjudication, and a caller
   cannot pattern-match a risk value into a policy branch.

2. **A score cannot arrive from outside.** ``RiskAssessment`` is built by the
   engine from measured features; there is no constructor path that accepts a
   caller's score, and every model here is ``extra="forbid"``, so a request
   body carrying ``{"score": 0.0}`` is rejected rather than absorbed.

3. **A number cannot appear without a source.** Every ``FeatureValue`` carries
   its ``FeatureSource``, ``AuthorityLevel`` and ``TrustLevel``, reusing the
   kernel's own provenance vocabulary rather than a parallel one invented here.
   A feature is not trusted because it is numeric.

WHAT ``score`` MEANS, STATED PRECISELY
--------------------------------------
It is a **normalized risk index** in ``[0, 1]``: accumulated heuristic points
divided by a documented saturation point, clamped. It is NOT a probability and
NOT a fraud likelihood. No calibration data exists to support a probabilistic
reading, so none is claimed — ``model_type`` says ``DETERMINISTIC_HEURISTIC``
and ``score_semantics`` says ``NORMALIZED_RISK_INDEX`` in every serialized
assessment, so a consumer cannot lose that context.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from packages.schemas.domain import new_uuid, utcnow
from packages.schemas.provenance import AuthorityLevel, TrustLevel
from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


class RiskBand(str, Enum):
    """Coarse buckets over the normalized index.

    ``CRITICAL`` is deliberately NOT a synonym for ``DENY``. It is the loudest
    thing an advisory layer can say, and the loudest thing an advisory layer can
    say is still advice. A transaction the deterministic engine permitted stays
    permitted at ``CRITICAL``; a transaction it denied stays denied at ``LOW``.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


#: Ascending severity, so a comparison never depends on enum declaration order
#: surviving a refactor.
BAND_ORDER: dict[RiskBand, int] = {
    RiskBand.LOW: 0,
    RiskBand.MEDIUM: 1,
    RiskBand.HIGH: 2,
    RiskBand.CRITICAL: 3,
}


class RiskRecommendation(str, Enum):
    """What the advisory layer suggests a human or a workflow should do.

    Every member names an action taken by somebody ELSE. None of them names an
    action the risk engine takes, because the risk engine takes none.
    """

    PROCEED = "PROCEED"
    REVIEW = "REVIEW"
    REQUIRE_STRONGER_APPROVAL = "REQUIRE_STRONGER_APPROVAL"
    ESCALATE = "ESCALATE"


class FeatureSource(str, Enum):
    """Where a feature's value physically came from.

    An enum rather than a free string: a source that is not on this list cannot
    be spelled, so a feature cannot quietly acquire an undocumented origin.
    ``MERCHANT_PAYLOAD`` exists and is deliberately UNUSED in
    ``heuristic-v1`` — it is here so that if a future feature ever does read
    merchant-controlled data, it has to say so in the type rather than blend in.
    """

    #: Server-owned reputation table. The ONLY source of merchant trust.
    MERCHANT_REGISTRY = "MERCHANT_REGISTRY"
    #: User policy captured at the trusted API boundary (USER_POLICY authority).
    USER_POLICY = "USER_POLICY"
    #: Output of the deterministic policy engine.
    POLICY_DECISION = "POLICY_DECISION"
    #: The kernel-issued authorization artifact.
    AUTHORIZATION_ROW = "AUTHORIZATION_ROW"
    #: Durable payment intent state.
    PAYMENT_INTENT_ROW = "PAYMENT_INTENT_ROW"
    #: The hash-chained audit ledger.
    AUDIT_LEDGER = "AUDIT_LEDGER"
    #: The missions/offers rows written by the kernel after normalization.
    MISSION_ROW = "MISSION_ROW"
    #: Merchant-controlled payload. Never read by heuristic-v1.
    MERCHANT_PAYLOAD = "MERCHANT_PAYLOAD"


class FeatureUnavailableReason(str, Enum):
    """Why a declared feature has no value on this assessment.

    ``None`` is not the same as ``0`` and this enum is how the difference stays
    visible. "No prior payments with this merchant" must not be scored as "a
    perfect payment record", and "no policy decision yet" must not be scored as
    "an amount of zero".
    """

    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NO_POLICY_DECISION = "NO_POLICY_DECISION"
    NO_AUTHORIZATION = "NO_AUTHORIZATION"
    NO_PAYMENT_INTENT = "NO_PAYMENT_INTENT"
    NO_OFFERS = "NO_OFFERS"
    NO_SELECTED_MERCHANT = "NO_SELECTED_MERCHANT"


FeatureScalar = float | int | bool | None


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #


class FeatureValue(BaseModel):
    """One measured input, inseparable from where it came from.

    ``derived_from_untrusted_evidence`` is the subtle one. Several features
    count SECURITY_VIOLATION events — records the KERNEL wrote, at kernel
    authority, ABOUT something a merchant attempted. The record is trustworthy;
    the behaviour it describes originated untrusted. Flattening that into
    "trusted, because the row is ours" would lose exactly the provenance the
    rest of PACTRA spends its effort preserving, so the flag travels with the
    value and is rendered in the explanation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=80)
    value: FeatureScalar = None
    source: FeatureSource
    authority: AuthorityLevel
    trust: TrustLevel
    #: The record is server-written, but the phenomenon it describes came from
    #: an untrusted party. Provenance is preserved rather than laundered.
    derived_from_untrusted_evidence: bool = False
    #: False means "not measured", never "measured as zero".
    available: bool = True
    unavailable_reason: FeatureUnavailableReason | None = None
    #: Plain-language statement of where this number came from. Rendered into
    #: reports so a reader never has to guess whether a value was authoritative.
    source_detail: str = Field(min_length=1, max_length=200)

    @property
    def numeric(self) -> float | None:
        """The value as a float, or ``None`` when it was not measured."""
        if not self.available or self.value is None:
            return None
        return float(self.value)


# --------------------------------------------------------------------------- #
# Factors
# --------------------------------------------------------------------------- #


class RiskFactor(BaseModel):
    """One reason the score is what it is.

    ``contribution`` is the exact number of points this factor added, and the
    sum of every factor's contribution equals ``RiskAssessment.raw_points`` to
    the last representable digit — asserted by a test. That equality is what
    makes the explanation an account of the score rather than a story told
    beside it.

    A factor exists only when it contributed something. A zero-contribution
    factor would be noise in an explanation whose whole value is that every line
    in it moved the number.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Stable machine code, e.g. ``AMOUNT_NEAR_HARD_LIMIT``. Safe for an audit
    #: payload and for a downstream workflow to branch on.
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9_]+$")
    #: The feature this factor read. Always present in ``feature_values``.
    feature: str = Field(min_length=1, max_length=80)
    #: Points added. Always positive: a factor that reduced risk would let a
    #: hostile signal be cancelled out by a benign one, which is how a scoring
    #: system gets talked out of a finding.
    contribution: float = Field(gt=0.0)
    #: The configured maximum for this factor, so a reader can see how much of
    #: the available weight the observation actually earned.
    weight: float = Field(gt=0.0)
    observed: FeatureScalar = None
    #: Where the ramp starts. Below this the factor contributes nothing.
    threshold: float | None = None
    #: Where the ramp saturates at full weight.
    saturates_at: float | None = None
    #: Sentence built from the numbers above. Never model-generated.
    explanation: str = Field(min_length=1, max_length=400)
    derived_from_untrusted_evidence: bool = False


# --------------------------------------------------------------------------- #
# Data quality
# --------------------------------------------------------------------------- #


class DataQuality(BaseModel):
    """How much the assessment actually had to work with.

    Reported INSTEAD of a "confidence" number. A confidence figure implies a
    calibrated posterior, and nothing here is calibrated; these are counts,
    which are honestly measurable and mean exactly what they say.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: True when enough prior observations exist to compute a behavioural
    #: baseline at all. False disables every anomaly factor rather than
    #: defaulting them to zero.
    history_available: bool
    history_observations: int = Field(ge=0)
    #: What the history is scoped BY. Never "user": PACTRA has no user identity
    #: in its data model, so no per-user baseline is available or claimed.
    history_scope: str = Field(min_length=1, max_length=40)
    #: No prior observations at all for this counterparty.
    cold_start: bool
    features_available: int = Field(ge=0)
    features_unavailable: int = Field(ge=0)
    #: Whether the mission's own audit chain verified. A false here means every
    #: audit-derived feature was read from history that does not verify, which
    #: the assessment says out loud rather than scoring silently.
    audit_chain_verified: bool


# --------------------------------------------------------------------------- #
# The assessment
# --------------------------------------------------------------------------- #


class RiskAssessment(BaseModel):
    """The complete advisory result for one mission at one moment.

    Read the field list for what is NOT here: no authorization id to consume, no
    policy override, no decision, no mutable state, no capability. There is
    nothing in this object a caller could act on except by choosing to, which is
    the definition of advice.

    ``policy_decision`` and ``policy_reason_codes`` are copied in READ-ONLY, so
    a consumer holding an assessment can see the authoritative outcome beside
    the advisory one and cannot mistake the second for the first.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_id: uuid.UUID = Field(default_factory=new_uuid)
    mission_id: uuid.UUID
    #: Truncated prefix of the bound transaction digest, when the mission holds
    #: an authorization. Same rule as Phase 3/4 audit payloads: enough to
    #: correlate, never a copy of the commitment.
    transaction_digest_prefix: str | None = None

    score: float = Field(ge=0.0, le=1.0)
    #: The un-normalized point total, so the arithmetic is reproducible.
    raw_points: float = Field(ge=0.0)
    #: Points at which the index reads 1.0. Published so ``score`` can be
    #: re-derived by the reader instead of taken on faith.
    saturation_points: float = Field(gt=0.0)
    band: RiskBand
    recommendation: RiskRecommendation

    feature_values: dict[str, FeatureValue] = Field(default_factory=dict)
    factors: list[RiskFactor] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)

    evaluated_at: datetime = Field(default_factory=utcnow)
    engine_version: str = Field(min_length=1, max_length=40)
    model_type: str = Field(min_length=1, max_length=40)
    model_version: str = Field(min_length=1, max_length=40)
    #: Pinned string, not free text: a serialized assessment must never be read
    #: as a probability just because it is a float between 0 and 1.
    score_semantics: Literal["NORMALIZED_RISK_INDEX"] = "NORMALIZED_RISK_INDEX"
    data_quality: DataQuality

    #: The authoritative outcome, copied for context only.
    policy_decision: str | None = None
    policy_reason_codes: list[str] = Field(default_factory=list)

    #: Pinned true. A literal rather than a comment so that any code path
    #: attempting to construct a non-advisory assessment fails validation.
    advisory: Literal[True] = True

    def audit_payload(self) -> dict:
        """The safe projection for a ``RISK_ASSESSED`` audit event.

        Carries the verdict, the factor CODES, and the versions — never raw
        feature values, never the merchant payload, never a full digest, and
        never a weight table. A downstream reader learns what the engine
        concluded and which controls it read; it does not learn enough to
        reconstruct the mission's contents from the ledger alone.
        """
        return {
            "assessment_id": str(self.assessment_id),
            "score": round(self.score, 6),
            "band": self.band.value,
            "recommendation": self.recommendation.value,
            "engine_version": self.engine_version,
            "model_type": self.model_type,
            "model_version": self.model_version,
            "score_semantics": self.score_semantics,
            "factor_codes": [factor.code for factor in self.factors],
            "advisory": True,
            "history_available": self.data_quality.history_available,
            "cold_start": self.data_quality.cold_start,
            "audit_chain_verified": self.data_quality.audit_chain_verified,
        }
