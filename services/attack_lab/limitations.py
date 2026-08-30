"""Documented boundaries of the claimed security contract.

These are NOT findings. A finding is a defect that should be fixed; a known
limitation is something the current design cannot do and does not claim to do.
Reporting them in one list would make the honest disclosures look like defects
and the defects look like disclosures, so they are separate structures with
separate sections in every report.

Nothing in Phase 6 fixes any of these, and nothing in Phase 6 claims to. The
Attack Lab may DEMONSTRATE one — ``audit_tail_truncation`` does — but a
demonstrated limitation is never counted as a blocked attack.
"""

from __future__ import annotations

from services.attack_lab.models import KnownLimitation

KNOWN_LIMITATIONS: tuple[KnownLimitation, ...] = (
    KnownLimitation(
        id="KL-01-audit-tail-truncation",
        title="Tail truncation and whole-chain deletion are undetectable",
        detail=(
            "A per-mission hash chain has no anchor outside itself. Deleting the "
            "last k events leaves 0..N-k-1: still contiguous, still correctly "
            "linked, still hashing correctly. A mission with no events is "
            "indistinguishable from one whose events were all removed. Detecting "
            "either requires a signed head, an external witness, or a "
            "cross-mission ledger; Phase 5 built none and Phase 6 adds none. "
            "Middle deletion, reordering, renumbering, injection and any edit to "
            "a hashed field ARE detected."
        ),
        demonstrated_by="audit_tail_truncation",
    ),
    KnownLimitation(
        id="KL-02-terminal-reason-code-not-replayable",
        title="A terminal provider failure's reason code is not in the ledger",
        detail=(
            "`apply_payment_transition` writes `reason_code` to the "
            "`payment_intents` column but not into the audit payload, so "
            "PROVIDER_TERMINAL_FAILURE cannot be reconstructed from event history. "
            "Replay leaves `last_reason_code` as None rather than inferring it "
            "from the event type, because inferring would fabricate a value the "
            "events do not contain. The Attack Lab does not reconstruct it either."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="KL-03-audit-canonicalization-is-weaker",
        title="Audit canonicalization is weaker than the transaction encoder",
        detail=(
            "The audit chain uses sorted-key JSON, not the type-tagged, "
            "domain-separated encoder in packages/schemas/canonical.py used for "
            'transaction digests. The stronger encoder makes 1, "1" and true '
            "unable to collide and rejects floats outright. Switching the chain to "
            "it would change the preimage of every event and invalidate every "
            "event_hash already written, so compatibility is preserved instead. "
            "Phase 6 does not rewrite historical hashes."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="KL-04-no-cryptographic-user-authorization",
        title="Signed approval uses one demo key, not production user identity",
        detail=(
            "USER_ED25519 provides a LOCAL CRYPTOGRAPHIC APPROVAL PROOF with one "
            "pre-enrolled DEMO USER-CONTROLLED SIGNING KEY. There is no user/account "
            "system, authenticated approval HTTP principal, trusted payment-detail "
            "display, or production credential recovery/rotation UX. Local key theft "
            "compromises demo approval, and broad server/database compromise remains "
            "outside the proof. This is not production identity, WebAuthn/passkey "
            "support, non-repudiation, or independent security validation."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="KL-05-no-cryptographic-merchant-authentication",
        title="Merchant identity is registration-based, not cryptographic",
        detail=(
            "IN_PROCESS_ADAPTER authentication means identity comes from "
            "server-side adapter registration, not from the wire. There is no "
            "mutual TLS and no signed merchant assertion. The identity-spoof "
            "scenario proves a merchant cannot talk its way into another "
            "merchant's identity through the payload; it does not prove a network "
            "attacker cannot impersonate a merchant connection, because no "
            "cryptographic binding exists to break."
        ),
        demonstrated_by="merchant_identity_spoof",
    ),
    KnownLimitation(
        id="KL-06-reconciliation-trusts-a-negative-provider-answer",
        title="Reconciliation trusts a provider that reports holding no payment",
        detail=(
            "FAILED_RETRYABLE is reachable from PROVIDER_PENDING through exactly "
            "one route: a provider that POSITIVELY reports holding no payment for "
            "the idempotency key. That is the correct design — no timer and no "
            "attempt count is evidence about whether money moved — but it does "
            "rest on the provider answering truthfully. A provider that creates a "
            "payment and then denies holding it can induce a duplicate. Measured "
            "directly: with such a lying provider substituted, "
            "provider_timeout_after_create reports NOT_BLOCKED with two provider "
            "payments, which is what tests/test_attack_lab_scenarios.py asserts to "
            "prove the scenario can detect a real duplicate at all. This is a "
            "boundary of what any client-side protocol can guarantee, not a defect "
            "PACTRA can close on its own."
        ),
        demonstrated_by=None,
    ),
    KnownLimitation(
        id="KL-07-latency-is-harness-local",
        title="Reported latency is harness-local, not production enforcement latency",
        detail=(
            "p50/p95/p99 are measured over in-process attack execution against an "
            "in-memory SQLite database (or a local PostgreSQL for the concurrency "
            "scenarios). There is no network, no connection pool, and no "
            "concurrent load. The numbers are useful for detecting a regression in "
            "this harness and are not a claim about deployed enforcement latency."
        ),
        demonstrated_by=None,
    ),
)
