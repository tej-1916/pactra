# PACTRA Build Specification (v2 — Adversarial Transaction Security Kernel)

> **This document supersedes the v1 "Secure Multi-Agent Commerce & Payment
> Gateway" specification.** The engineering direction has changed from a
> protocol-routing gateway to a zero-trust, adversarial transaction control
> plane. Requirements from v1 that still hold (deterministic policy, human
> approval, Razorpay test mode, hash-chained audit, idempotency, strict schemas,
> testing) are preserved and integrated below — they are not discarded.

---

## 1. Product Identity

**Brand:** PACTRA
**Expansion:** Policy-Aware Commerce Threat & Risk Architecture
**Technical title:** PACTRA — Adversarial Transaction Security Kernel for Agentic Commerce
**Track:** Razorpay Buildathon Track 01 — AI Growth & Agentic Commerce

PACTRA is a zero-trust adversarial transaction control plane that sits between
autonomous AI agents and payment infrastructure. It assumes the reasoning layer,
merchant input, or a participating agent may be compromised, and guarantees that
transaction invariants still hold.

---

## 2. Thesis

The v1 thesis ("secure multi-agent commerce gateway") has been replaced by an
adversarial one:

> **Can agentic commerce remain transaction-safe even when the reasoning layer,
> merchant input, or one participating agent is compromised?**

PACTRA is designed around explicit failure assumptions:

```text
THE AI MAY FAIL.
THE AI MAY HALLUCINATE.
MERCHANT INPUT MAY BE MALICIOUS.
AN AGENT MAY BE COMPROMISED.
NETWORKS MAY FAIL.
MESSAGES MAY BE REPLAYED.

BUT TRANSACTION INVARIANTS MUST STILL HOLD.
```

**The LLM is never the security boundary.**

---

## 3. Problem

Agentic commerce lets an AI interpret intent, read untrusted merchant content,
call tools, and initiate financial actions. The failure modes are adversarial,
not merely accidental: prompt injection from merchant content, authority
escalation (untrusted data mutating trusted policy), capability escalation (a
compromised agent invoking privileged operations), price mutation after
approval, authorization replay, merchant identity spoofing, duplicate payments,
tamper of audit history, and hallucinated authorization state.

PACTRA places a deterministic, provenance-aware security kernel between agents
and payment rails so that none of these can move money.

---

## 4. Core Design Rule

```text
LLM / Agent proposes
        ↓
Strict schema validation
        ↓
Provenance inspection
        ↓
Authority validation
        ↓
Capability enforcement
        ↓
Deterministic policy evaluation
        ↓
Transaction binding
        ↓
Authorization validation
        ↓
Replay protection
        ↓
Idempotent executor
        ↓
Razorpay (test mode)
```

Never:

```text
LLM → Razorpay
```

---

## 5. Architecture — Adversarial Transaction Security Kernel

```text
                         USER
                          │  natural language
                          ▼
                   INTENT COMPILER
                          ▼
                     BUYER AGENT
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
     Merchant A      Merchant B       Merchant C     (UNTRUSTED INPUT)
          └───────────────┼────────────────┘
                          ▼
╔══════════════════════════════════════════════════════╗
║   PACTRA — ADVERSARIAL TRANSACTION SECURITY KERNEL    ║
║                                                       ║
║   Provenance Engine                                   ║
║        ↓                                              ║
║   Taint Tracking                                      ║
║        ↓                                              ║
║   Authority Lattice                                   ║
║        ↓                                              ║
║   Schema / Invariant Validator                        ║
║        ↓                                              ║
║   Capability Firewall                                 ║
║        ↓                                              ║
║   Deterministic Policy Engine                         ║
║        ↓                                              ║
║   Risk / Anomaly Engine (advisory only)               ║
║        ↓                                              ║
║   Transaction Binding                                 ║
║        ↓                                              ║
║   Authorization / Human Approval                      ║
║        ↓                                              ║
║   Replay Protection                                   ║
║        ↓                                              ║
║   Idempotency / Payment Reliability                   ║
║        ↓                                              ║
║   Tamper-Evident Audit / Replay                       ║
╚═══════════════════════╤═══════════════════════════════╝
                        ▼
                 PAYMENT EXECUTOR
                        ▼
                RAZORPAY TEST MODE
```

Each stage is deterministic Python. The kernel is the security boundary; the
LLM only feeds proposals into the top of it.

---

## 6. Kernel Stages

### 6.1 Provenance Engine
Every security-sensitive value carries its origin and trust level:

```json
{
  "price":      { "value": 3799, "source": "merchant-agent-7", "trust": "untrusted" },
  "hard_limit": { "value": 4500, "source": "user-policy",       "trust": "authoritative" }
}
```

The kernel can always answer: where did this value come from, who was allowed to
produce it, what authority level the source had, whether it was transformed, and
whether it may influence a sensitive field.

### 6.2 Taint Tracking
Untrusted data stays marked untrusted throughout the flow, implemented as typed
domain objects / explicit metadata — **not** as prompt instructions.

Merchant-controlled data *may* influence: product description, recommendations,
rankings, merchant-provided metadata.

Merchant-controlled data *must never* directly modify: user spending limits,
authorization, capabilities, payment destination, transaction policy, approval
state.

### 6.3 Authority Lattice
Explicit ordered authority levels:

```text
USER-SIGNED POLICY  >  SYSTEM SECURITY POLICY  >  AUTHORIZATION
>  TRUSTED INTERNAL SERVICE  >  AGENT PROPOSAL  >  MERCHANT DATA
```

A lower-authority source may never modify higher-authority state. Attempts
raise `AUTHORITY_ESCALATION`:

```text
merchant says: budget = ₹100000
→ source: MERCHANT, target: USER_POLICY → AUTHORITY_ESCALATION → DENY
```

### 6.4 Schema / Invariant Validator
All agent/LLM/merchant output must pass strict Pydantic schemas plus explicit
invariant checks before any deterministic component acts on it.

### 6.5 Capability Firewall
Principals hold explicit allow/deny capability sets enforced in deterministic
code. Example Buyer Agent:

```text
ALLOW: catalog.read, merchant.discover, offer.request, offer.rank, payment.propose
DENY:  payment.execute, refund.execute, policy.modify, authorization.issue, merchant.modify
```

A compromised LLM still cannot invoke a denied capability; the privileged
executor is unreachable without a satisfied capability check.

### 6.6 Deterministic Policy Engine
Never an LLM prompt. Policies: hard transaction ceiling, soft budget, daily
spend limit, currency restrictions, merchant allow/deny list, merchant trust
requirement, minimum rating, approval threshold, offer expiration, price
mutation, authorization expiration. Decisions: `ALLOW`, `REQUIRE_APPROVAL`,
`DENY`, each with machine-readable reason codes.

### 6.7 Risk / Anomaly Engine (advisory only)
Optional, added after core invariants hold. May score risk, recommend review,
or escalate. **May not** authorize a payment, change a hard policy, or override
any deterministic security rule. Deterministic heuristic first; ML (XGBoost /
LightGBM / Isolation Forest) deferred.

### 6.8 Transaction Binding
On approval, the authorization is bound to the exact transaction via a digest:

```text
transaction_digest = SHA256(
  merchant_id + product_id + quantity + amount + currency
  + policy_version + offer_version + expiry + nonce )
```

If price, merchant, product, quantity, currency, or policy version changes after
approval, the authorization becomes invalid:

```text
approved ₹3799 → merchant changes to ₹4399 → TRANSACTION_BINDING_FAILURE → PAYMENT DENIED
```

### 6.9 Authorization / Human Approval
Authorizations are nonce-bound, expiring, one-time-use where appropriate, and
associated with a transaction digest.

### 6.10 Replay Protection
A consumed authorization cannot be reused:

```text
reuse old approval → AUTHORIZATION_REPLAY_DETECTED → DENY
```

### 6.11 Idempotency / Payment Reliability
Persistent payment intent, idempotency key, retry-safe execution, duplicate
prevention, webhook signature verification, duplicate/delayed webhook handling,
reconciliation, crash recovery. Uses a **transactional outbox** where it
improves correctness:

```text
DB TRANSACTION { PaymentIntent, AuditEvent, OutboxEvent } → COMMIT → Worker → Provider
```

No unnecessary distributed complexity.

### 6.12 Tamper-Evident Audit / Replay
Hash-chained event ledger (see §9) with a verification endpoint and
deterministic mission reconstruction from event history (see §8).

---

## 7. Data Model

Existing tables: `missions`, `mission_constraints`, `offers`,
`policy_decisions`, `audit_events`.

New / extended tables:

```text
capabilities            # principal -> allow/deny sets, limits
authorizations          # nonce, transaction_digest, expiry, consumed, bound fields
payment_intents         # idempotency_key UNIQUE, provider_payment_id UNIQUE, state
payments                # settled payment records
outbox_events           # transactional outbox for reliable side effects
risk_scores             # advisory risk scores per mission/transaction
```

Provenance/versioning columns: `offers.offer_version`, `policy_decisions.policy_version`,
and provenance/trust metadata on security-sensitive values.

Uniqueness invariants:

```text
payment_intents.idempotency_key UNIQUE
audit_events(mission_id, sequence) UNIQUE
provider_payment_id UNIQUE
authorizations.nonce UNIQUE
```

---

## 8. Event History + Replay

Persist important mission transitions as events, e.g. `MISSION_CREATED`,
`INTENT_PARSED`, `MERCHANT_DISCOVERY_STARTED`, `OFFER_RECEIVED`,
`OFFER_SELECTED`, `POLICY_EVALUATED`, `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`,
`PAYMENT_REQUESTED`, `PAYMENT_TIMEOUT`, `PAYMENT_RECONCILED`,
`PAYMENT_CONFIRMED`. Support deterministic `REPLAY MISSION` — reconstruct mission
state purely from the event history.

---

## 9. Tamper-Evident Audit Ledger

Each event contains `event_id`, `mission_id`, `sequence`, `event_type`, `actor`,
`payload`, `previous_hash`, `event_hash`, `created_at`. Canonical serialization +
SHA-256. Verification returns e.g. `{ "valid": true, "events_checked": 37 }`; a
modified event yields `AUDIT_INTEGRITY_FAILURE`. This is tamper-evident, **not**
a blockchain.

---

## 10. Adversarial Attack Lab

An explicit, runnable adversarial testing system covering at least: Merchant
Prompt Injection, Budget Escalation, Capability Escalation, Price Mutation,
Authorization Replay, Merchant Identity Spoofing, Duplicate Payment, Stale
Approval, Malformed Agent Output, Tool Injection, Payment Timeout, Duplicate
Webhook, Delayed Webhook, Forged Metadata, Policy Manipulation Attempt.

Every attack produces a structured record:

```text
attack_name, attack_input, expected_defense, observed_result,
blocked/succeeded, reason_code, latency, affected_component
```

The frontend will later expose an **Adversarial Test Lab** to run and observe
these.

---

## 11. Security Evaluation Harness

Do not claim security — measure it. Generate many normal and adversarial
scenarios and compute metrics from **actual runs only**: Attack Block Rate,
Policy Bypass Rate, Replay Success Rate, Duplicate Payment Rate, False
Positive/Negative Rate, and p50/p95/p99 enforcement latency. Never fabricate
metrics.

---

## 12. Protocol Layer (corrected)

The v1 design incorrectly treated ACP / AP2 / MCP / x402 as interchangeable
protocols. They operate at different layers. Instead, define distinct adapter
families over an internal normalized transaction model:

```text
CommerceAdapter               # discovery / offers
PaymentAuthorizationAdapter   # authorization artifacts
ToolAdapter                   # agent tool invocation surface
PaymentRailAdapter            # payment execution rails (Razorpay test)
```

Only claim support for a protocol that is actually implemented. Anything
incomplete is labeled `experimental`, `partial`, or `simulated`. No fake
integrations.

---

## 13. Razorpay Integration

Test mode only. Properties: bounded, explainable, gated, auditable, retry-safe.
The payment executor is never directly exposed to LLM tool calls.

---

## 14. Reliability Requirements (must be tested)

duplicate mission request; duplicate approval request; payment API timeout;
crash before provider response; crash after provider response; repeated webhook;
out-of-order/delayed webhook; stale merchant offer; malformed agent output;
merchant prompt injection; merchant price mutation; authorization replay; policy
limit violation; authority escalation; capability escalation; forged merchant
identity.

---

## 15. What We Are NOT Building

No Kubernetes for show, no blockchain audit log, no sprawling microservices, no
gratuitous agents, no unjustified vector DB / RAG, no LLM-based security policy,
no fake protocol integrations, no fake metrics. Complexity must come from solving
real engineering problems.

---

## 16. Build Phases (revised, incremental)

```text
Phase 1  — Domain + deterministic policy + audit chain            [DONE]
Phase 2  — Security-kernel primitives: provenance, taint,
           authority lattice, capability firewall                 [NEXT]
Phase 3  — Transaction binding + authorization + replay protection
Phase 4  — Payment reliability: FakeProvider, idempotency, outbox,
           webhook verification, fault injection; then Razorpay test
Phase 5  — Audit /verify endpoint + corruption test + event replay
Phase 6  — Adversarial Attack Lab + evaluation harness (real metrics)
Phase 7  — Risk / anomaly engine (advisory only; ML optional)
Phase 8  — Protocol adapter correction (4 adapter families)
Phase 9  — Frontend, including Adversarial Test Lab UI
Phase 10 — Demo hardening: seeded data, one-command demo, metrics
```

Each phase verifies its security invariants with tests before the next begins.

---

## 17. Critical Invariants (the test contract)

```text
NO VALID AUTHORIZATION                       → NO PAYMENT
LLM OUTPUT                                    → NEVER AUTHORIZATION
MERCHANT CONTENT                              → NEVER SYSTEM AUTHORITY
LOWER AUTHORITY DATA                          → CANNOT MODIFY HIGHER AUTHORITY POLICY
HARD LIMIT EXCEEDED                           → PAYMENT IMPOSSIBLE
TRANSACTION CHANGED AFTER APPROVAL            → AUTHORIZATION INVALID
EXPIRED APPROVAL                              → PAYMENT IMPOSSIBLE
REPLAYED APPROVAL                             → PAYMENT IMPOSSIBLE
DENIED CAPABILITY                             → PRIVILEGED EXECUTOR UNREACHABLE
SAME IDEMPOTENCY KEY                          → AT MOST ONE LOGICAL PAYMENT
AUDIT EVENT MODIFIED                          → VERIFICATION FAILURE
UNTRUSTED DATA                                → RETAINS PROVENANCE / TAINT
```

If a feature violates one of these invariants, remove the feature.

---

## 18. Definition of Done

PACTRA is done when a mission runs end-to-end with ≥2 merchant agents;
deterministic policy and human approval are enforced; transaction binding
invalidates mutated transactions; authorization replay and expiry are blocked;
capability-denied operations are unreachable; a Razorpay test payment succeeds
and duplicates are prevented; every transition is auditable and audit hashes
verify; missions can be replayed from history; a prompt-injection / authority-
escalation attempt is blocked; a forced payment failure recovers safely; the
attack lab and evaluation harness report real metrics; and the repo runs from
clean setup instructions.
