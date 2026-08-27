# PACTRA

**PACTRA — Adversarial Transaction Security Kernel for Agentic Commerce**
Expansion: *Policy-Aware Commerce Threat & Risk Architecture*
Razorpay Buildathon — Track 01: AI Growth & Agentic Commerce

PACTRA is a **zero-trust adversarial transaction control plane** between
autonomous AI agents and payment infrastructure. It is built for the hard case:
transaction safety must hold **even when the reasoning layer, merchant input, or
one participating agent is compromised**.

```text
THE AI MAY FAIL.        MERCHANT INPUT MAY BE MALICIOUS.
THE AI MAY HALLUCINATE. AN AGENT MAY BE COMPROMISED.
NETWORKS MAY FAIL.      MESSAGES MAY BE REPLAYED.
BUT TRANSACTION INVARIANTS MUST STILL HOLD.
```

**The LLM is never the security boundary and never authorizes or moves money.**

## Architecture — Adversarial Transaction Security Kernel

```text
USER → natural language → INTENT COMPILER → BUYER AGENT
   → Merchant A / B / C   (UNTRUSTED INPUT)
   ↓
┌───────────────── PACTRA SECURITY KERNEL ─────────────────┐
│ Provenance → Taint → Authority Lattice                   │
│   → Schema/Invariant Validator → Capability Firewall     │
│   → Deterministic Policy → Risk/Anomaly (advisory)       │
│   → Transaction Binding → Authorization/Approval          │
│   → Replay Protection → Idempotency/Payment Reliability   │
│   → Tamper-Evident Audit / Replay                         │
└──────────────────────────────────────────────────────────┘
   ↓
PAYMENT EXECUTOR → RAZORPAY TEST MODE
```

Never `LLM → Razorpay`. Every stage is deterministic Python; the LLM only feeds
proposals into the top of the kernel.

> This is v2. It supersedes the v1 "Secure Multi-Agent Commerce & Payment
> Gateway" direction, but **keeps** its still-valid requirements — deterministic
> policy, human approval, Razorpay test mode, hash-chained audit, idempotency,
> strict schemas, and testing — integrated into the adversarial design. See
> `PACTRA_BUILD_SPEC.md` and `docs/architecture.md`.

## Non-negotiable engineering rules

1. The LLM is never the security boundary; it proposes, the kernel decides.
2. No real-money payments in development; Razorpay test mode only.
3. Never commit API keys or secrets.
4. Security policy is deterministic code, never a prompt.
5. Untrusted data (user text, merchant content, LLM output) retains provenance
   and taint throughout the flow.
6. Lower-authority data can never modify higher-authority state.
7. Every external side effect is idempotent and auditable.
8. The system survives retries, crashes, duplicate requests, and replays.
9. No fake integrations and no fake metrics — measured numbers come from real
   runs; partial protocols are labeled `experimental` / `partial` / `simulated`.
10. Build the backend kernel and verify its invariants before any UI.

## Repository layout

```text
pactra/
├── apps/
│   ├── api/                    # FastAPI entrypoint, DB models, migrations
│   └── web/                    # Next.js dashboard + Adversarial Test Lab (later)
├── services/
│   ├── agent_orchestrator/     # mission state machine, mock merchants
│   ├── security_kernel/        # provenance, taint, authority, capability,
│   │                           #   invariants, binding, authorization, replay (Phase 2–3)
│   ├── policy_engine/          # deterministic policy, normalization, ranking
│   ├── payment_executor/       # provider protocol, idempotency, outbox (Phase 4)
│   ├── risk_engine/            # advisory risk/anomaly scoring (Phase 7)
│   ├── attack_lab/             # adversarial scenarios + runner (Phase 6)
│   └── audit_ledger/           # append-only hash-chained events + verify/replay
├── adapters/                   # CommerceAdapter, PaymentAuthorizationAdapter,
│                               #   ToolAdapter, PaymentRailAdapter (Phase 8)
├── benchmark/                  # security evaluation harness / real metrics (Phase 6)
├── packages/schemas/           # shared typed request/event/provenance schemas
├── infra/                      # Docker Compose (Postgres/Redis)
├── docs/architecture.md
├── tests/
├── PACTRA_BUILD_SPEC.md
├── CLAUDE_CODE_PROMPT.md
└── README.md
```

Directories for later phases are created as those phases begin.

## Critical invariants (the test contract)

```text
NO VALID AUTHORIZATION → NO PAYMENT
LLM OUTPUT → NEVER AUTHORIZATION
MERCHANT CONTENT → NEVER SYSTEM AUTHORITY
LOWER AUTHORITY DATA → CANNOT MODIFY HIGHER AUTHORITY POLICY
HARD LIMIT EXCEEDED → PAYMENT IMPOSSIBLE
TRANSACTION CHANGED AFTER APPROVAL → AUTHORIZATION INVALID
EXPIRED / REPLAYED APPROVAL → PAYMENT IMPOSSIBLE
DENIED CAPABILITY → PRIVILEGED EXECUTOR UNREACHABLE
SAME IDEMPOTENCY KEY → AT MOST ONE LOGICAL PAYMENT
AUDIT EVENT MODIFIED → VERIFICATION FAILURE
UNTRUSTED DATA → RETAINS PROVENANCE / TAINT
```

## Phase roadmap

```text
Phase 1  Domain + deterministic policy + audit chain            [DONE]
Phase 2  Security-kernel primitives: provenance, taint,
         authority lattice, capability firewall                 [DONE]
Phase 3  Transaction binding + authorization + replay protection [DONE]
Phase 4  Payment reliability: FakeProvider, idempotency, outbox,
         webhook verification, fault injection; Razorpay test  [DONE,
         Razorpay adapter partial — see below]
Phase 5  Audit /verify endpoint + corruption test + event replay
Phase 6  Adversarial Attack Lab + evaluation harness (real metrics)
Phase 7  Risk/anomaly engine (advisory only; ML optional)
Phase 8  Protocol adapter correction (4 adapter families)
Phase 9  Frontend, including the Adversarial Test Lab UI
Phase 10 Demo hardening: seeded data, one-command demo, metrics
```

---

## Phase 1 — backend vertical slice (implemented)

Phase 1 delivers the deterministic core that the kernel builds on: mission
creation, two mock merchant agents, offer normalization/ranking, the
deterministic policy engine, and an append-only, hash-chained audit ledger. No
LLM, no Razorpay, no frontend.

### Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # deps from pyproject.toml
cp .env.example .env             # placeholders only — no real secrets
```

For local runtime with PostgreSQL + Redis:

```bash
docker compose -f infra/docker-compose.yml up -d
cd apps/api && alembic upgrade head    # applies all migrations
```

### Run the API

```bash
cd apps/api
uvicorn apps.api.pactra.main:app --reload   # http://127.0.0.1:8000/docs
```

### Quality gates

```bash
make lint         # ruff check
make type-check   # mypy
make test         # pytest (uses in-memory SQLite; no Postgres required)
```

### Try a mission

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/missions \
  -H 'content-type: application/json' \
  -d '{
        "raw_query": "Find wireless earbuds under 4000, min rating 4.2",
        "quantity": 1,
        "constraints": {
          "category": "wireless_earbuds",
          "soft_budget_inr": 4000,
          "hard_limit_inr": 4500,
          "min_rating": 4.2,
          "currency": "INR"
        }
      }'
```

The best valid offer (₹4,299) exceeds the soft budget but not the hard ceiling,
so the mission ends in `AWAITING_APPROVAL` with a `REQUIRE_APPROVAL` policy
decision. `GET /api/v1/missions/{id}/events` returns the hash-chained audit
trail. The Nimbus merchant embeds a prompt-injection string in its product
description; normalization discards all free-form merchant text, so it never
reaches the policy engine — the first, foundational instance of the taint
guarantee that Phase 2 formalizes across the whole kernel.

---

## Phase 3 — transaction binding + authorization + replay protection (implemented)

Phase 3 makes an approval bind to **one exact transaction**, and makes that
binding one-time and expiring. There is still no payment execution: Phase 3
produces the artifact a future executor will require, and nothing more.

### Transaction binding

Nine fields are committed to by a single digest:

```text
merchant_id, product_id, quantity, amount_inr, currency,
policy_version, offer_version, expires_at, nonce
```

The digest is deliberately **not** built by concatenating strings — naive
concatenation lets `("ab", "c")` and `("a", "bc")` collide, so one approved
transaction could be swapped for another. Instead
`packages/schemas/canonical.py` produces a domain-separated, type-tagged,
sorted-key preimage:

```text
transaction_digest = SHA256(
    "pactra-txn-bind-v1" || 0x1f || canonical_json({field: [type_tag, value]})
)
```

Field names are inside the preimage, values are type-tagged so `1` / `"1"` /
`true` cannot collide, floats are rejected outright (no canonical form), and
timestamps are fixed-precision UTC.

```text
approved:  merchant=merchant_a product=P1 amount=3799 quantity=1 currency=INR
later:     amount=4399
result:    TRANSACTION_BINDING_FAILURE -> authorization invalid
           -> future payment path impossible
```

### Authorization artifact

```text
PENDING  --activate-->  ACTIVE  --consume-->  CONSUMED   (terminal)
   |                       |
   +-----------------------+--expire--> EXPIRED          (terminal)
   +-----------------------+--revoke--> REVOKED          (terminal)
```

**Server-issued, not cryptographically signed.** Phase 3 implements no signing
and no signature verification, so nothing here is described as signed. The
artifact is authoritative because it is minted, held, and consumed entirely
inside the trusted server boundary. The 256-bit `nonce` is server-held entropy
that makes the artifact unique and its digest unpredictable — it is never
returned by the API and never written into an audit payload.

Issuance requires the `authorization.issue` capability, held only by the
`security-kernel` principal and explicitly denied to `buyer-agent`. A `DENY`
policy decision issues no authorization at all.

### Replay protection and concurrency

Consumption is a single atomic conditional UPDATE; the database's `rowcount` is
the decision. There is no read-then-write and no in-memory boolean on the
decision path:

```sql
UPDATE authorizations
   SET status='CONSUMED', consumed_at=:now
 WHERE authorization_id=:id
   AND status='ACTIVE' AND transaction_digest=:digest AND expires_at > :now
```

Two requests that both observed `ACTIVE` both issue this UPDATE; exactly one
gets `rowcount == 1`. The loser gets `AUTHORIZATION_REPLAY_DETECTED` and changes
nothing. Storage adds `authorizations.nonce UNIQUE` and a CHECK that a
consumption timestamp exists if and only if the row is `CONSUMED`.

### Endpoints added

```text
GET  /api/v1/missions/{id}/authorization          # artifact, never the nonce
POST /api/v1/missions/{id}/authorization/approve  # PENDING -> ACTIVE
```

Approval grants no payment capability — there is no executor yet. It moves the
artifact into the only state from which it can later be consumed exactly once,
against exactly the transaction it is bound to.

### Audit events

```text
AUTHORIZATION_CREATED     AUTHORIZATION_ACTIVATED   AUTHORIZATION_CONSUMED
AUTHORIZATION_EXPIRED     AUTHORIZATION_REVOKED     AUTHORIZATION_REPLAY_DETECTED
TRANSACTION_BINDING_FAILURE
```

Payloads carry a truncated digest prefix — enough to correlate events across a
mission, not enough to reproduce the artifact — and never the nonce.

### Try it

```bash
# 1. Create a mission that needs approval (best offer 4299 > soft budget 4000)
MISSION=$(curl -s -X POST http://127.0.0.1:8000/api/v1/missions \
  -H 'content-type: application/json' \
  -d '{"quantity":1,"constraints":{"category":"wireless_earbuds",
       "soft_budget_inr":4000,"hard_limit_inr":4500,"min_rating":4.2,
       "currency":"INR"}}' | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 2. Inspect the PENDING authorization (note: no nonce is returned)
curl -s http://127.0.0.1:8000/api/v1/missions/$MISSION/authorization

# 3. Approve it -> ACTIVE, mission reaches AUTHORIZED
curl -s -X POST http://127.0.0.1:8000/api/v1/missions/$MISSION/authorization/approve
```

### Not implemented in Phase 3

No payment execution, no Razorpay, no transactional outbox, no frontend, no risk
model, no Attack Lab. No cryptographic signing of any kind — neither user
authorization signatures nor merchant authentication (mutual TLS / signed
merchant assertions remain unimplemented, despite Phase 2 having anticipated
them here).

---

## Phase 4 — payment reliability (implemented)

Phase 4 is where money can finally move, and therefore where the interesting
question is not "does a payment succeed?" but **"can the system be made to pay
twice, pay the wrong thing, or claim a payment it did not make?"** Every
mechanism below exists to answer no to one of those.

### The path from an approved mission to a provider call

```text
POST /missions/{id}/payment          (Idempotency-Key: required)
      │  no amount, no merchant, no capability set — there are no such fields
      ▼
ONE DB TRANSACTION
  INSERT payment_intents          UNIQUE(idempotency_key) decides same-key races
  consume_authorization(...)      Phase 3 atomic conditional UPDATE
  INSERT audit_events             PAYMENT_INTENT_CREATED / PAYMENT_QUEUED
  INSERT outbox_events            PAYMENT_CREATE_REQUESTED
COMMIT
      ▼
python -m services.payment_executor.run_worker      (a SEPARATE process)
      ▼
PaymentProvider  →  FakePaymentProvider | RazorpayTestPaymentProvider (partial)
```

**No HTTP request ever reaches a payment provider.** The route commits a durable
intent and returns; the provider is reached only from the outbox worker, which
is a different process on purpose. That is what makes `LLM → Razorpay`
structurally impossible rather than merely discouraged.

### The payment state machine

```text
CREATED → QUEUED → PROCESSING ─┬─→ SUCCEEDED          (terminal)
                               ├─→ FAILED_TERMINAL    (terminal)
                               ├─→ FAILED_RETRYABLE ──→ QUEUED
                               └─→ PROVIDER_PENDING   (the UNCERTAIN state)

PROVIDER_PENDING → SUCCEEDED | FAILED_TERMINAL | FAILED_RETRYABLE
```

`PROVIDER_PENDING` is the whole design. A provider timeout is **not** a failure
— it is an absence of information, and a payment may or may not exist. Treating
it as failure re-creates a payment that already exists; treating it as success
records money that never moved. So it becomes uncertainty, and only
reconciliation resolves it.

`FAILED_RETRYABLE` is reachable from `PROVIDER_PENDING` through exactly one
route: a provider that positively reports holding **no** payment for the key.
No timer, no elapsed time, and no attempt count promotes an uncertain payment
back to retryable, because none of those is evidence about whether money moved.

### Never a blind retry

Before **every** create attempt the executor asks the provider what it holds for
the durable idempotency key:

```text
lookup succeeds, payment found     → validate, adopt it, DO NOT create
lookup succeeds, nothing found     → safe to create; no duplicate is possible
lookup FAILS                       → stay uncertain, reconcile later,
                                     NEVER fall through to create
```

This deliberately does not rely on the provider deduplicating creates.
`NonIdempotentFakePaymentProvider` — a provider that creates a brand-new payment
on every create call — is used in the crash-recovery tests precisely so
provider-side idempotency cannot hide a PACTRA blind-retry bug.

### A provider response may report state, never redefine the transaction

Every provider response is validated against the durable intent — `provider`,
`amount_inr`, `currency`, and the idempotency key — *before* the provider id is
linked and *before* any success/failure transition. A mismatch raises
`PROVIDER_RESPONSE_MISMATCH`, which:

* does **not** link `provider_payment_id`,
* does **not** mark the intent succeeded,
* leaves the intent uncertain and schedules reconciliation.

The key check is strictest exactly where it matters most. While no provider
payment is linked yet, the idempotency key is the **only** thing tying a
response to this intent, so a response that omits it — or names a different one
— is refused outright. A payment with a coincidentally equal amount and currency
must never be adopted as ours; settling against someone else's charge would be
worse than a duplicate. Once an id **is** linked, correlation is established by
that id, and `link_provider_payment` refuses to relink a different one.

### Webhooks

```text
1. verify HMAC over the RAW bytes   (constant-time compare)
2. resolve the payment by provider_payment_id   (server-side; the webhook
                                                 supplies a pointer, never an
                                                 amount, merchant, or authorization)
3. deduplicate on UNIQUE(provider, provider_event_id)
4. apply ONLY what the state machine permits
```

Duplicate → the unique index refuses the second insert. Delayed → terminal
states have no outgoing transitions. Out-of-order → the transition table, not
the arrival order, decides. Conflicting concurrent webhooks → both serialize on
a `SELECT ... FOR UPDATE` of the intent row, so exactly one terminal transition
applies and the loser is recorded as out-of-order.

**An invalid signature is NOT audited, and the code says so.** The audit ledger
is mission-scoped, and the only thing naming a mission in a rejected delivery is
the payload whose signature just failed. Writing that event would mean choosing
a mission chain on the authority of a forged body. A transport-scoped security
log is the right home for rejections; Phase 4 does not build one, and nothing in
the code or comments claims otherwise.

### Transactional outbox and the worker

The outbox row is written in the *same* transaction as the payment intent, so
after `COMMIT` the instruction to call the provider is exactly as durable as the
decision to pay. Claiming is dialect-appropriate rather than pretended-portable:
`SELECT … FOR UPDATE SKIP LOCKED` on PostgreSQL, an atomic conditional UPDATE
decided by `rowcount` elsewhere. Neither uses a read-then-write in Python.

The worker uses **two transactions**, and the split is the crash-recovery story:

```text
TX 1   claim the event, persist IN_PROGRESS + the attempt   COMMIT
TX 2   do the provider work, persist result, acknowledge    COMMIT
```

A crash during provider I/O therefore leaves a durable `IN_PROGRESS` lease
rather than rolling the claim back to an indistinguishable `PENDING`. Recovery
is the lease lapsing — no separate reaper — and the cost is that a slow dispatch
may be re-claimed while still running, which is why every handler is idempotent
regardless.

Dead-lettering sets the outbox row to `FAILED` and stops the worker spinning. It
deliberately does **not** make the payment intent terminal: "automatic recovery
gave up" is not the same claim as "this payment definitively failed", and
recording the stronger claim would be recording something unverified.

### Separation of duties

```text
security-kernel   may issue authorizations, DENIED payment.execute
payment-executor  may execute payments,     DENIED authorization.issue
buyer-agent       (what an LLM acts through) DENIED both
```

The component that can *create* an authorization cannot *spend* it. Both
privileged boundaries enforce through `enforce_registered`, which re-resolves
the principal against the server-owned registry and requires the presented set
to equal it. A `CapabilitySet` is a plain schema, so untrusted code can build
one that simply claims a capability; checking that claim against itself would
make the guard self-certifying.

### SQLite vs PostgreSQL — stated honestly

SQLite runs the fast unit suite. It is **not** where the concurrency guarantees
are proven, and it is not treated as if it were:

| | SQLite | PostgreSQL |
|---|---|---|
| Writer model | one database-wide writer lock | row-level locks + MVCC |
| `FOR UPDATE` | accepted and ignored | a real row lock |
| `SKIP LOCKED` | unavailable — conditional UPDATE fallback | used as intended |
| A losing racer | often refused by SQLite's lock | refused by the code under test |

A "concurrency" test on SQLite runs under a regime that removes most of the
concurrency, so the loser is refused by the database rather than by the logic
being tested. **PostgreSQL is authoritative** for concurrent authorization
consumption, concurrent same-key creation, idempotency conflicts, payment row
locking, webhook races, `SKIP LOCKED` outbox claiming, and audit sequence
serialization. Those tests skip loudly if no server is reachable — a guarantee
that was not exercised must never look like one that was:

```bash
docker compose -f infra/docker-compose.yml up -d
pytest -m postgres            # 14 PostgreSQL concurrency tests
```

No production behaviour is weakened to make SQLite imitate PostgreSQL.

### Razorpay — `partial`, and not claimed as more

The adapter is test-mode only: a non-`rzp_test_` key is refused in `__init__`,
before it can be stored in an attribute. Secrets come from the environment with
no source-code fallback, and `__repr__` is redacted by construction.

What is genuinely implemented and tested offline: the test-mode guard and
webhook signature verification (`X-Razorpay-Signature` = hex HMAC-SHA256 of the
raw body, per Razorpay's documentation). Three limitations, stated as gaps:

1. **Razorpay does not document receipt uniqueness.** PACTRA sends its
   idempotency key as the Order `receipt` and reconciles via
   `GET /v1/orders?receipt=…`. That is a *correlation handle*, not provider-side
   idempotency, and it is not claimed as such. Duplicate prevention rests
   entirely on PACTRA's own `UNIQUE(idempotency_key)` and the
   PROVIDER_PENDING/reconciliation path — which is why those were built without
   assuming provider help. If a receipt search returns more than one order, the
   adapter **refuses** rather than adopting one arbitrarily: two orders for one
   receipt is the duplicate this phase exists to detect, and picking the first
   would resolve the lookup by discarding the evidence.
2. **An Order is not a Payment.** The server-side API creates an Order; the
   Payment appears when a customer completes Checkout. A complete end-to-end
   Razorpay payment needs a Checkout front end, which Phase 4 does not build.
3. **The HTTP paths have not been exercised against the live Razorpay API.**
   They are tested against a stub client, which proves this adapter's
   *interpretation* of a response — not that Razorpay replies that way.

Provider-independent reliability, proven against `FakePaymentProvider`, is the
deliverable. Razorpay is an adapter over it.

### Endpoints added

```text
POST /api/v1/missions/{id}/payment    # 201 created / 200 already existed
                                      # requires Idempotency-Key
GET  /api/v1/missions/{id}/payment    # reports PROVIDER_PENDING as itself
POST /api/v1/webhooks/{provider}      # raw body + provider signature header
```

```bash
python -m services.payment_executor.run_worker --provider fake
```

### Not implemented in Phase 4

No audit `/verify` endpoint or mission replay (Phase 5), no Attack Lab or
evaluation harness (Phase 6), no risk engine (Phase 7), no protocol adapters
(Phase 8), no frontend (Phase 9). No cryptographic signing of user
authorizations and no cryptographic merchant authentication — both remain
unimplemented, as in Phase 3. No transport-scoped security log for rejected
webhooks.
