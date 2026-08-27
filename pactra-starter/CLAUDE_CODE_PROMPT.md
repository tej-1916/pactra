# PACTRA — Master Build Prompt (v2 — Adversarial Transaction Security Kernel)

You are the principal engineer building **PACTRA — Adversarial Transaction
Security Kernel for Agentic Commerce** (expansion: *Policy-Aware Commerce Threat
& Risk Architecture*). Razorpay Buildathon Track 01 — AI Growth & Agentic
Commerce.

Read `PACTRA_BUILD_SPEC.md` (v2) and `docs/architecture.md` completely before
modifying code. This prompt supersedes the v1 "Secure Multi-Agent Commerce &
Payment Gateway" prompt.

## Thesis

Build for the adversarial case: **agentic commerce must remain transaction-safe
even when the reasoning layer, merchant input, or one participating agent is
compromised.**

```text
THE AI MAY FAIL.        MERCHANT INPUT MAY BE MALICIOUS.
THE AI MAY HALLUCINATE. AN AGENT MAY BE COMPROMISED.
NETWORKS MAY FAIL.      MESSAGES MAY BE REPLAYED.
BUT TRANSACTION INVARIANTS MUST STILL HOLD.
```

## Core rule

**The LLM is never the security boundary and never authorizes or executes a
payment.** The only correct path is:

```text
LLM / Agent proposes → strict schema validation → provenance inspection
→ authority validation → capability enforcement → deterministic policy
→ transaction binding → authorization validation → replay protection
→ idempotent executor → Razorpay (test mode) → audit event
```

Never `LLM → Razorpay`.

## Working style

1. Inspect the repository first; summarize what exists before changing it.
2. Classify existing work as KEEP / MODIFY / REPLACE / REMOVE / DEFER. Never do a
   destructive rewrite without justification.
3. Work in small vertical increments; one class of security invariant per phase.
4. Do not invent integrations that are not implemented. Label anything partial as
   `experimental` / `partial` / `simulated`.
5. No secrets in source. No real payment credentials. Razorpay **test mode only**.
6. Prefer explicit typed domain objects and deterministic state machines over
   hidden agent behavior. Security policy is deterministic Python, never a prompt.
7. Every important behavior requires tests. Do not fake metrics — all reported
   numbers come from real runs.
8. State acceptance criteria before each phase; run tests and show exact results
   after each phase.
9. Do not start the frontend until the backend kernel invariants hold and are
   tested.

## Required stack

Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, Alembic.
State/cache: Redis only where it earns its place. Frontend: Next.js + TypeScript
(later). Payments: Razorpay test mode only. Testing: pytest + property/invariant
tests. Containers: Docker Compose. LLM: provider abstraction, structured output
only, mock fallback for tests — introduced only in a later phase.

## The kernel (build order inside each mission)

```text
Provenance Engine → Taint Tracking → Authority Lattice
→ Schema/Invariant Validator → Capability Firewall
→ Deterministic Policy Engine → Risk/Anomaly Engine (advisory)
→ Transaction Binding → Authorization/Human Approval
→ Replay Protection → Idempotency/Payment Reliability
→ Tamper-Evident Audit/Replay
```

## Phase plan (incremental)

- **Phase 1 — Domain + deterministic policy + audit chain.** DONE. Domain models,
  mission state machine, mock merchants, normalization, ranking, deterministic
  policy engine, append-only hash-chained audit, tests.
- **Phase 2 — Security-kernel primitives (NEXT).** Provenance-wrapped values,
  taint tracking as typed objects, authority lattice with `AUTHORITY_ESCALATION`,
  capability firewall enforced in code. Update policy vocabulary to
  `ALLOW / REQUIRE_APPROVAL / DENY`. Acceptance: lower-authority data cannot
  modify higher-authority state; denied capability makes the privileged executor
  unreachable; untrusted values retain provenance/taint end to end.
- **Phase 3 — Transaction binding + authorization + replay.** Transaction digest,
  nonce-bound expiring one-time authorizations. Acceptance: mutated transaction →
  `TRANSACTION_BINDING_FAILURE`; expired/replayed approval → DENY.
- **Phase 4 — Payment reliability.** `PaymentProvider` protocol,
  `FakePaymentProvider`, idempotency key, transactional outbox, webhook signature
  verification, duplicate/delayed webhook handling, reconciliation, fault
  injection (timeout before/after provider creation, repeated webhook). Then
  `RazorpayTestPaymentProvider`. Acceptance: same idempotency key → at most one
  logical payment across retries and crashes.
- **Phase 5 — Tamper-evident audit + event replay.**
  `GET /api/v1/missions/{id}/audit/verify` → `{ "valid": true, "events_checked": N }`;
  corruption test proves failure; deterministic `REPLAY MISSION` from events.
- **Phase 6 — Adversarial Attack Lab + evaluation harness.** 15 named scenarios,
  structured result records, real metrics (block rate, bypass rate, replay
  success, duplicate-payment rate, false pos/neg, p50/p95/p99 latency).
- **Phase 7 — Risk/anomaly engine (advisory only).** Deterministic heuristic
  first; optional ML (XGBoost/LightGBM/Isolation Forest). ML may score/recommend/
  escalate but may never authorize, change hard policy, or override a rule.
- **Phase 8 — Protocol adapter correction.** `CommerceAdapter`,
  `PaymentAuthorizationAdapter`, `ToolAdapter`, `PaymentRailAdapter` over an
  internal normalized transaction model. No fake integrations.
- **Phase 9 — Frontend**, including the Adversarial Test Lab UI.
- **Phase 10 — Demo hardening.** Seeded data, one-command demo, real metrics.

## Demo story (target)

Happy path (intent → agents → offer → policy → approval → Razorpay test → audit
verify), then Attack 1 prompt injection (BLOCKED), Attack 2 price mutation
(`TRANSACTION_BINDING_FAILURE`), Attack 3 replay (`AUTHORIZATION_REPLAY_DETECTED`),
a forced payment-timeout retry (no duplicate logical payment), an audit
corruption (verification fails), and a benchmark of real metrics.

## Critical invariants (test these)

```text
NO VALID AUTHORIZATION → NO PAYMENT
LLM OUTPUT → NEVER AUTHORIZATION
MERCHANT CONTENT → NEVER SYSTEM AUTHORITY
LOWER AUTHORITY DATA → CANNOT MODIFY HIGHER AUTHORITY POLICY
HARD LIMIT EXCEEDED → PAYMENT IMPOSSIBLE
TRANSACTION CHANGED AFTER APPROVAL → AUTHORIZATION INVALID
EXPIRED APPROVAL → PAYMENT IMPOSSIBLE
REPLAYED APPROVAL → PAYMENT IMPOSSIBLE
DENIED CAPABILITY → PRIVILEGED EXECUTOR UNREACHABLE
SAME IDEMPOTENCY KEY → AT MOST ONE LOGICAL PAYMENT
AUDIT EVENT MODIFIED → VERIFICATION FAILURE
UNTRUSTED DATA → RETAINS PROVENANCE / TAINT
```

If a feature violates an invariant, remove the feature.

## What NOT to build

No Kubernetes for show, no blockchain audit log, no sprawling microservices, no
gratuitous agents, no unjustified vector DB / RAG, no LLM-based security policy,
no fake protocol integrations, no fabricated metrics.

## Communication protocol

Start of each phase, report: `PHASE / GOAL / FILES TO CHANGE / RISKS /
ACCEPTANCE CRITERIA`. End of each phase, report: `COMPLETED / TESTS / FAILURES /
SECURITY IMPACT / NEXT PHASE`. If something cannot be done truthfully, say so.

## Start

1. Inspect the repository and re-read the v2 spec + architecture notes.
2. Show the Phase 2 plan (security-kernel primitives) only.
3. Implement Phase 2, verify its invariants with tests, then stop.
4. Do not build later phases or the frontend prematurely.
