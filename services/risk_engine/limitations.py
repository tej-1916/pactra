"""Documented boundaries of what the advisory risk layer can claim.

SEPARATE FROM THE PHASE 6 LIST, DELIBERATELY
----------------------------------------------
``services/attack_lab/limitations.py`` holds KL-01..KL-07: the boundaries of
PACTRA's SECURITY contract. Those are unchanged by Phase 7 and none of them is
fixed by it. The ones here are boundaries of the RISK MEASUREMENT, which is a
different kind of claim — a security limitation says an attacker could do
something undetected, while a risk limitation says a number means less than it
looks like it means.

Folding the two lists together would blur that, and would also change what every
Phase 6 attack-lab report prints. So they stay apart, and each harness reports
its own.

These are NOT findings and NOT defects. Every one of them is a consequence of a
design decision made on purpose, stated so nobody has to discover it from the
numbers.
"""

from __future__ import annotations

from services.attack_lab.models import KnownLimitation

RISK_LIMITATIONS: tuple[KnownLimitation, ...] = (
    KnownLimitation(
        id="RL-01-no-user-identity-no-behavioural-baseline",
        title="There is no per-user baseline, because there is no user",
        detail=(
            "PACTRA's data model has no user identity: `missions` has no owner, "
            "no account, and no session principal. Every user-scoped feature the "
            "Phase 7 brief lists — spend deviation from the user's history, "
            "transaction velocity, distinct-merchant counts, repeated high-value "
            "attempts — is therefore ABSENT rather than approximated. The engine "
            "says so in every explanation rather than leaving a reader to assume "
            "it was considered. History is scoped by authenticated merchant only. "
            "Adding user-scoped risk means adding a user to the domain first."
        ),
        demonstrated_by="benign_cold_start_merchant",
    ),
    KnownLimitation(
        id="RL-02-score-is-an-index-not-a-probability",
        title="The score is a normalized risk index, not a fraud probability",
        detail=(
            "score = min(1, accumulated heuristic points / saturation points). "
            "The weights calibrate the BANDS — one severe signal reads HIGH, two "
            "read CRITICAL — and nothing calibrates a probability. No dataset "
            "exists against which a probabilistic reading could be validated, so "
            "0.80 does not mean an 80% chance of anything. `score_semantics` is a "
            "pinned literal on every assessment so a serialized float cannot lose "
            "that context."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="RL-03-evaluation-corpus-is-synthetic-and-authored",
        title="Every evaluation label is synthetic and written by the author",
        detail=(
            "The 17 evaluation scenarios are built from PACTRA's own domain "
            "models and driven through the real kernel, but their BENIGN/RISKY "
            "labels are authored, not observed. The corpus is a regression "
            "corpus: it detects a change in scoring behaviour. A detection rate "
            "measured on it is NOT evidence about real-world fraud, and the "
            "person who wrote the labels also wrote the weights — so a high score "
            "on it is close to self-consistency, not validation."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="RL-04-merchant-history-is-a-bounded-recent-window",
        title="Cross-mission merchant history is a bounded recent window",
        detail=(
            "Merchant violation counts scan the most recent 500 SECURITY_VIOLATION "
            "events; amount baselines use the most recent 200 authorizations. A "
            "risk assessment has to be cheap and an unbounded scan is not. The "
            "consequence is real: a merchant whose violations are older than the "
            "window is not counted, so these are 'recent history' counters, not "
            "'all history' counters."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="RL-05-not-invoked-automatically",
        title="The risk engine is not in the automatic mission path",
        detail=(
            "Phase 7 exposes assessment on demand (GET /risk) and on explicit "
            "request (POST /risk/assess). The orchestrator does not call it. That "
            "keeps the enforcement path and every mission's audit history exactly "
            "as Phase 1-6 left them, and it guarantees structurally that risk is "
            "never a barrier before payment. The cost is equally real: a mission "
            "nobody asks about has no assessment, and there is no background "
            "sweep. Listed as remaining debt, not as a feature."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="RL-06-advisory-recommendations-have-no-workflow",
        title="A recommendation is returned; nothing enforces or routes it",
        detail=(
            "REVIEW, REQUIRE_STRONGER_APPROVAL and ESCALATE are values in a "
            "response. Phase 7 builds no reviewer queue, no escalation channel, "
            "and no second approval step, and the existing approval flow does not "
            "read them. Wiring a recommendation into a workflow is exactly where "
            "an advisory layer could quietly acquire authority, so it is deferred "
            "rather than improvised."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="RL-07-no-held-out-evaluation-set",
        title="The reported metrics are development-set metrics, not generalization",
        detail=(
            "The review threshold (0.25) is the MEDIUM band boundary, which was "
            "derived from the four weight tiers before the evaluation corpus "
            "existed, and it was NOT re-tuned after observing results — a test "
            "pins review_threshold == band_medium_at so it cannot drift into a "
            "free parameter. But the 17 scenarios were authored AFTER the weights "
            "and threshold, by the same author, so the corpus was constructed "
            "with knowledge of the scoring rules. There is NO held-out set and "
            "none is claimed. Detection and false-positive rates measured here "
            "are development-set metrics; they say the heuristic behaves as "
            "designed on cases designed for it, not that it generalizes."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="RL-08-corpus-is-trivially-separable",
        title="The evaluation corpus is trivially separable",
        detail=(
            "Minimum risky score 0.2807, maximum benign score 0.1307: a "
            "separation margin of +0.1500 with no overlap at all, giving a "
            "synthetic ROC-AUC of 1.0 and identical 100%/0% results at every "
            "threshold from 0.15 to 0.25. That is a property of the CORPUS, not "
            "evidence of discrimination power — a benchmark with no hard cases "
            "cannot distinguish a good scorer from an adequate one. Only one "
            "risky family (risky_amount_anomaly, 0.2807) sits within 0.05 of the "
            "threshold, and no benign family does."
        ),
        demonstrated_by="risky_amount_anomaly",
    ),
    KnownLimitation(
        id="RL-09-benign-output-diversity-is-lower-than-family-count",
        title="Five of seven benign families produce an identical zero-factor result",
        detail=(
            "benign_low_value, benign_cold_start_merchant, "
            "benign_established_merchant, benign_competitive_selection and "
            "benign_settled_payment are distinct in CONSTRUCTION — different "
            "merchants, history depths, and payment outcomes — but all score "
            "0.0000 with no contributing factor. The benign half therefore "
            "exercises three distinct scoring OUTCOMES (0.0000, 0.0094, 0.1307), "
            "not seven, so the 0/70 false-positive count rests on less "
            "discriminating coverage than the family count suggests. Each risky "
            "family, by contrast, has a distinct factor signature."
        ),
        demonstrated_by=None,
    ),
)
