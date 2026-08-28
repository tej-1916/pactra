"""PACTRA advisory risk / anomaly engine (Phase 7).

RISK SCORE IS NOT AUTHORITY
---------------------------
This package scores, explains, and recommends. It never decides. The
deterministic security kernel — provenance, authority lattice, capability
firewall, policy engine, transaction binding, authorization, replay protection,
idempotency — remains the only thing that can permit or refuse a transaction,
and it is unchanged by anything here.

Concretely, and enforced by tests rather than by convention:

* Nothing in the risk core imports ``services.payment_executor``, the merchant
  adapters, or the authorization write path, so there is no function it could
  reach that moves money or mints an artifact
  (``tests/test_risk_isolation.py`` parses the import graph).
* ``RiskAssessment`` has no field, and the engine no parameter, capable of
  carrying an authorization, a policy override, or a caller-supplied score.
* A ``DENY`` from the deterministic engine stays ``DENY`` at every band,
  including ``LOW``; a ``CRITICAL`` band refuses nothing on its own.

The recommendation vocabulary is deliberately disjoint from the policy
vocabulary — ``PROCEED / REVIEW / REQUIRE_STRONGER_APPROVAL / ESCALATE``, never
``ALLOW`` or ``DENY`` — so no report, log line, or API response can be read as
though risk had adjudicated something.
"""

from __future__ import annotations

from services.risk_engine.config import (
    DEFAULT_RISK_CONFIG,
    ENGINE_VERSION,
    HEURISTIC_VERSION,
    RiskConfig,
)
from services.risk_engine.engine import assess_mission, record_assessment
from services.risk_engine.models import (
    DataQuality,
    FeatureSource,
    FeatureValue,
    RiskAssessment,
    RiskBand,
    RiskFactor,
    RiskRecommendation,
)

__all__ = [
    "DEFAULT_RISK_CONFIG",
    "ENGINE_VERSION",
    "HEURISTIC_VERSION",
    "DataQuality",
    "FeatureSource",
    "FeatureValue",
    "RiskAssessment",
    "RiskBand",
    "RiskConfig",
    "RiskFactor",
    "RiskRecommendation",
    "assess_mission",
    "record_assessment",
]
