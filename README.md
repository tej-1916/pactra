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
│   ├── attack_lab/             # adversarial scenarios, runner, metrics,
│   │                           #   evaluation harness + CLI (Phase 6)
│   └── audit_ledger/           # append-only hash-chained events + verify/replay
├── adapters/                   # CommerceAdapter, PaymentAuthorizationAdapter,
│                               #   ToolAdapter, PaymentRailAdapter (Phase 8)
├── reports/attack-lab/         # generated evaluation JSON (gitignored)
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
Phase 5  Audit /verify endpoint + corruption test + event replay  [DONE]
Phase 6  Adversarial Attack Lab + evaluation harness (real metrics) [DONE]
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
make attack       # adversarial attack lab, SQLite scenarios only
make attack-full  # full evaluation incl. PostgreSQL concurrency attacks
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
locking, webhook races, `SKIP LOCKED` outbox claiming, audit sequence
serialization, and verification of a concurrently written chain. Those tests
skip loudly if no server is reachable — a guarantee that was not exercised must
never look like one that was:

```bash
docker compose -f infra/docker-compose.yml up -d
pytest -m postgres            # 17 PostgreSQL tests (concurrency + audit chain)
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

No Attack Lab or evaluation harness (Phase 6), no risk engine (Phase 7), no
protocol adapters (Phase 8), no frontend (Phase 9). No cryptographic signing of
user authorizations and no cryptographic merchant authentication — both remain
unimplemented, as in Phase 3. No transport-scoped security log for rejected
webhooks.

---

## Phase 5 — tamper-evident audit + deterministic replay (implemented)

Phase 5 proves two things and claims nothing beyond them:

```text
AUDIT EVENT MODIFIED  ->  VERIFICATION FAILURE
REPLAY                ->  READ-ONLY DETERMINISTIC STATE RECONSTRUCTION
```

No new migration. Both features read the `audit_events` table Phase 1 already
built; a snapshot, checkpoint or version table added for architectural
decoration would be a schema change with no invariant behind it.

### One hash function, and the bug that made it necessary

`compute_event_hash` is the only place an event hash is produced — the ledger
calls it when writing, the verifier calls it when recomputing. A verifier with
its own implementation either reports tampering that did not happen or misses
tampering that did, and the drift stays invisible until it matters.

Building the verifier surfaced a real defect. `created_at` is inside the hash
preimage; the writer passes an aware UTC value, but SQLite has no
timezone-aware type and returns a **naive** datetime on read, whose
`isoformat()` drops the `+00:00`. Recomputing from a persisted row produced a
different hash from the one stored beside it — so every chain verified inside
the writing session and failed the moment it was re-read, which is exactly what
`/verify` does.

The fix is `as_utc` normalization **inside** `compute_event_hash`, so both
callers get it. It is exact, not a guess: values are written as UTC
unconditionally. For an already-aware UTC input — every value the writer has
ever passed — the encoding is byte-identical, so **no historical event hash
changed**, and a test pins that.

The audit chain deliberately keeps its original canonical JSON rather than
adopting the stronger type-tagged encoder used for transaction digests.
Switching would change the preimage of every event and invalidate every hash
already written, so compatibility is preserved and the difference documented
instead of silently reconciled.

### Verification

```text
GET /api/v1/missions/{id}/audit/verify
```

```json
{ "valid": true, "events_checked": 17 }
```

```json
{ "valid": false, "events_checked": 6,
  "first_invalid_sequence": 5, "reason_code": "AUDIT_EVENT_HASH_MISMATCH" }
```

Checks run in order — structure, position, genesis, linkage, recomputed hash —
and only the FIRST failure is reported. Tampering with one event invalidates its
own hash and every link after it; listing all of them would present one act of
tampering as dozens of findings and bury the position that matters.

```text
AUDIT_VALID | AUDIT_SEQUENCE_GAP | AUDIT_PREVIOUS_HASH_MISMATCH
AUDIT_EVENT_HASH_MISMATCH | AUDIT_GENESIS_INVALID | AUDIT_EVENT_MALFORMED
```

**The verifier never writes.** No repair path, no recompute-on-read, nothing
staged on the session. Tamper evidence is worthless if the verifier repairs
what it exists to detect, so the corruption tests re-read every tampered row
afterwards and assert it is still exactly as the attacker left it.

Corruption is proved by editing database rows directly, past the application —
because an attacker with database access does not go through `append_event`.
21 tests cover: payload edit, actor edit, event-type edit, `event_hash` edit,
`previous_hash` edit, a payload edit WITH a recomputed hash (caught one event
later by the next link), sequence renumbering, middle deletion, first-event
deletion, event injection, corrupt genesis, five malformed-row shapes, and two
tests that verification itself changes nothing.

### What a per-mission chain cannot detect — stated, not papered over

* **Tail truncation.** Deleting the last k events leaves `0..N-k-1`: still
  contiguous, still correctly linked. Detecting it needs an anchor outside the
  chain — a signed head, an external witness, a cross-mission ledger. Phase 5
  builds none of those.
* **Whole-chain deletion.** A mission with no events is indistinguishable from
  one whose events were all removed.

Middle deletion, reordering, renumbering, injection and any edit to a hashed
field ARE detected.

### Replay

```text
GET /api/v1/missions/{id}/replay
```

```text
EVENT HISTORY  ->  PURE DETERMINISTIC REDUCER  ->  RECONSTRUCTED STATE
```

Replay is a projection, not a rerun. It calls no merchant, no payment provider,
no authorization issuer, no executor and no webhook handler; it creates no
payment, consumes no authorization, appends no audit event and writes no row.

That is structural rather than disciplinary, and proved three independent ways:

1. **Import graph.** `services/audit_ledger/replay.py` is parsed by a test and
   may not import `services.payment_executor`, `services.security_kernel`, or
   the merchant adapters. The only `services` imports permitted are the mission
   state-machine predicates and the ledger's read path. A reducer that CAN reach
   an executor eventually will be asked to.
2. **Landmines.** `append_event`, `issue_authorization`, `consume_authorization`,
   `activate_authorization`, `create_payment_intent`, `dispatch_create`,
   `reconcile_intent`, `handle_webhook`, `enqueue_outbox_event`, both provider
   methods and both merchant-transport methods are each replaced with a function
   that raises. Replay of a mission with a full payment history touches none.
3. **Row census.** Every table counted before and after, with a commit in
   between: `audit_events`, `authorizations`, `payment_intents`, `outbox_events`,
   `webhook_events`, `missions` — all unchanged. Ten repeated replays accumulate
   nothing and return byte-identical results.

### Determinism

`reduce_events` reads no clock, generates no UUID, consults no environment and
performs no I/O. Timestamps are copied verbatim from event payloads as strings,
never parsed and re-formatted. 100 reductions of one event stream produce one
distinct serialized result, and reversing the retrieval order changes nothing —
the reducer sorts by `sequence`, which is the ordering the hash chain itself
commits to.

### The integrity gate

```text
events -> verify -> invalid ? REFUSED: trusted=false, state=null
                 -> valid   ? deterministic replay
```

An invalid chain yields **no projection at all** — not a projection with a
warning attached. A caller handed a state object will use it, and a flag beside
it does not stop that.

### Unknown events: fail closed

Audit events carry no schema or version field, and Phase 5 adds none. The
policy covers the thing that actually varies: an `event_type` this build does
not recognize is REFUSED (`REPLAY_UNSUPPORTED_EVENT_TYPE`).

An unrecognized event may be a security event, and a projection that silently
drops it does not merely omit information — it misrepresents what happened while
presenting itself as a faithful reconstruction. Every one of the 33 declared
`EventType` values has a reducer, and a test asserts the handler table equals the
enum exhaustively, so a new event type added without a rule fails a test rather
than distorting a projection. A known type with an uninterpretable payload is
refused the same way (`REPLAY_MALFORMED_EVENT`).

### Replay vs. persisted state

```json
{ "replay_state": "PAYMENT_SUCCEEDED",
  "persisted_state": "PAYMENT_SUCCEEDED", "matches": true }
```

DIAGNOSTIC ONLY. A mismatch is reported and **never repaired**: the rows are what
the kernel enforces against, and letting a reconstruction overwrite them would
hand authority to the derived view. Where neither side holds an authorization or
a payment, the comparison reports `null` rather than `true`.

Replay is verified against eight real mission histories, each produced by the
actual kernel rather than hand-written events: ALLOW, REQUIRE_APPROVAL, DENY,
human approval over HTTP, the authorization lifecycle (created / activated /
consumed / revoked), a replayed authorization, a transaction-binding failure,
payment success, a lost-response timeout resolved by reconciliation, a transient
retry, a terminal failure, a webhook-settled payment with a duplicate delivery,
an idempotent retry, and an authority-escalation + identity-spoof attack.

### What replay cannot reconstruct

`last_reason_code` is `None` after a terminal provider failure.
`apply_payment_transition` writes `reason_code` to the `payment_intents` COLUMN
but not into the audit payload, so `PROVIDER_TERMINAL_FAILURE` is not in the
ledger. Replay leaves the field unknown rather than inferring it from the event
type — inferring would be fabricating a value the events do not contain. A test
asserts both halves (the column has it, the projection does not) so the gap
cannot drift unnoticed. Reason codes that ARE written into payloads (the
uncertainty and reconciliation paths) reconstruct normally.

### Measured cost

Real numbers from `pytest tests/test_audit_performance.py -s` on the development
machine, SQLite, in-process. Not a benchmark claim — the assertions in that file
are loose on purpose, sized to catch an accidental quadratic rather than a
millisecond regression, because a flaky performance gate teaches people to ignore
failures.

| events | verify | replay | verify/event | replay/event |
|---|---|---|---|---|
| 100 | 4.6 ms | 1.6 ms | 45.6 µs | 16.0 µs |
| 500 | 12.0 ms | 4.2 ms | 24.1 µs | 8.5 µs |
| 1000 | 25.8 ms | 9.2 ms | 25.7 µs | 9.2 µs |

Both are linear in chain length, asserted as a same-process RATIO between a
100-event and a 1000-event chain so machine speed cancels out. **No cache was
added**: none is needed at this cost, and a cache in front of a tamper-evidence
check is a way to serve a stale "valid" for a chain that has since been altered.

### PostgreSQL

Three Phase 5 tests join the PostgreSQL suite (17 total). Eight concurrent
legitimate appends produce sequences `0..7` whose `previous_hash` links verify —
the stronger property, since the existing test only proved the numbers came out
contiguous. Corruption is proved on PostgreSQL as well as SQLite because the two
backends round-trip timestamps differently, so a verifier correct on one could
still be wrong on the other. `append_event`'s `SELECT … FOR UPDATE` is unchanged.

### Endpoints added

```text
GET /api/v1/missions/{id}/audit/verify    # read-only; repairs nothing
GET /api/v1/missions/{id}/replay          # read-only; gated on verification
```

### Not implemented in Phase 5

No external anchor for the audit chain, so tail truncation and whole-chain
deletion remain undetectable (above). No Attack Lab or evaluation harness
(delivered in Phase 6, below), no risk engine (Phase 7), no protocol adapters
(Phase 8), no frontend (Phase 9). No cryptographic signing and no cryptographic
merchant authentication, as in Phases 3 and 4.

---

## Phase 6 — adversarial attack lab + evaluation harness (implemented)

Phase 6 stops describing PACTRA as secure and starts **measuring** it. 47
scenarios run through the real kernel — 36 malicious, 10 benign controls, and 1
demonstrated known limitation — and every number below came out of an executed
run. Nothing is hardcoded and nothing is asserted into existence.

```bash
python -m services.attack_lab.run --list
python -m services.attack_lab.run --all
python -m services.attack_lab.run --scenario authorization_replay
python -m services.attack_lab.run --category TRANSACTION --iterations 10
python -m services.attack_lab.run --all --iterations 10 --require-postgres \
    --out reports/attack-lab/run.json
```

### The lab builds hostile inputs; it never turns a control off

There is no `disable_security` flag to find, because none exists. Scenarios
construct what an attacker can actually construct — a merchant adapter that lies
about its identity, a payload carrying injected instructions, a forged
`CapabilitySet`, a provider whose 200 OK describes a different transaction — and
call the same entry points production calls. Starting state is built by
*calling* `issue_authorization` and `activate_authorization`, never by inserting
a row with `status='ACTIVE'`: an authorization forged past the kernel would let a
scenario "prove" a control that never ran.

The one deliberate exception is the audit group, which corrupts rows **directly
in the database**. That is what an attacker with database access does, and it is
the only way to test the verifier instead of the writer.

### Prompt injection, measured as causal influence

Searching an audit log for "ignore the budget" and printing BLOCKED tests the
search, not the system. So the scenario runs **two full missions** whose offers
are byte-identical in every security-relevant field and differ only in free-form
text, then compares decision, amount, ranking, bound transaction and event
sequence. If injected content carried any authority the two would diverge:

```text
clean twin:  ALLOW  requested_amount=3799   AUTHORIZED
injected:    ALLOW  requested_amount=3799   AUTHORIZED
capabilities_escalated: []       payment_intents_created: 0
injected_text_in_audit_payloads: false
```

The injected title is still persisted verbatim on the offer row — merchant
content is *stored*, not laundered — and that is the point: it exists, and it
influences nothing.

### An exception is not a block

```text
setup raises            -> INCONCLUSIVE   the attack never ran
declared backend absent -> INCONCLUSIVE   BACKEND_UNAVAILABLE
execute raises          -> ERROR          proved nothing, in either direction
execute returns         -> BLOCKED / NOT_BLOCKED, from the measured Observation
```

"Expected `AUTHORIZATION_REPLAY_DETECTED`, got a `TypeError`" is a scenario that
established nothing, and recording it as a success would be exactly the
fabrication this phase exists to prevent. ERROR and INCONCLUSIVE runs are
excluded from every denominator and reported separately — never counted on the
safe side.

**Two harness bugs found this way, both of which would have lied confidently:**

1. `provider_timeout_after_create` reported NOT_BLOCKED. Tracing all fourteen
   steps showed the financial invariant had held perfectly — one create call, one
   provider payment, one logical payment, the *original* payment recovered. The
   scenario drove the worker with `drain`, which loops until the outbox empties;
   handling a lost response enqueues its own reconciliation, so one drain ran
   both turns and the scenario sampled the state *after* reconciliation resolved
   it. Stepping one event at a time is what makes the uncertain state observable.
2. Every audit tamper reported the verifier as broken. The tampers were raw SQL
   binding `str(mission_id)`, and SQLAlchemy's `Uuid` column stores dash-less hex
   on SQLite — so every statement matched **zero rows** and the untouched chain
   correctly verified. They now use typed Core statements *and* assert the
   statement changed a row; a tamper that touches nothing raises rather than
   reporting a verdict.

Neither was a PACTRA defect, and neither was papered over.

### A check that cannot fail is not a check

The critical duplicate-payment scenario is run in the test suite against a
provider that records a payment and then denies holding it. A duplicate genuinely
results, and the scenario must report NOT_BLOCKED:

```text
provider_payments_ever_created: 2   duplicate_effect: true
recovered_original_payment: false   -> NOT_BLOCKED
```

Without that, the BLOCKED it reports for real PACTRA would be unfalsifiable. The
same mutation test exists for prompt injection's differential comparison.

### Benign controls, and why FP/FN needs them

A kernel that denied everything would score a perfect block rate. Ten controls —
an allowed transaction, human approval, valid consumption, a settled payment, an
idempotent retry, transient-failure recovery, a genuine webhook, reconciliation,
chain verification, trusted replay — run the same real paths with
`expected_status = NOT_BLOCKED`. A control that comes back BLOCKED is counted as
a false positive rather than quietly re-labelled.

### Metric definitions

Denominators exclude ERROR and INCONCLUSIVE. A rate over an empty denominator is
`None` and prints as `n/a`, never as 0% or 100% — "zero attacks succeeded out of
zero valid runs" is not perfect security.

```text
attack_block_rate            = blocked / decisive malicious runs
attack_success_rate          = not_blocked / decisive malicious runs
false_negative_rate          = the same quantity, stated rather than disguised
false_positive_rate          = controls blocked / decisive control runs
invariant_preservation_rate  = invariant_preserved / runs that measured one
replay_attack_success_rate   = replays with an unauthorized effect / attempts
duplicate_payment_rate       = runs with >1 logical or >1 provider payment / attempts
reason_match_rate            = observed code == expected code / runs declaring one
p50/p95/p99                  = nearest-rank over execute_ms of decisive runs
```

`false_negative_rate` and `attack_success_rate` are **identical** under these
definitions: a false negative is a hostile scenario that came back NOT_BLOCKED.
Both are reported because both are asked for, and the equality is stated instead
of hidden by computing them over slightly different subsets.

### Measured run

Generated by `python -m services.attack_lab.run --all --iterations 10
--require-postgres` on the development machine (Linux, Python 3.14, in-memory
SQLite + local PostgreSQL 16 via `infra/docker-compose.yml`), 2026-08-28.
Reproduce with that exact command; results are not committed.

```text
iterations 10     scenarios 47     runs 470     postgres exercised: yes

attack runs                   360  (decisive 360)
attacks blocked               360
attacks NOT blocked             0
errors                          0
inconclusive                    0
known-limitation runs          10  (excluded from attack rates)

benign control runs           100  (decisive 100)
controls correctly allowed    100
controls wrongly blocked        0

attack_block_rate             100.00%   = 360/360
attack_success_rate             0.00%   = 0/360
invariant_preservation_rate   100.00%   over 460 runs that measured one
replay_attack_success_rate      0.00%   = 0/30
duplicate_payment_rate          0.00%   = 0/40
false_positive_rate             0.00%   = 0/100
false_negative_rate             0.00%   = 0/360
reason_match_rate             100.00%   = 320/320

latency (attack execution only, harness-local — NOT production enforcement):
  samples 470   p50 18.48 ms   p95 267.86 ms   p99 536.47 ms
  min 1.59 ms   max 692.95 ms   mean 52.62 ms
```

Per category, all 10 iterations:

| category | runs | blocked | not blocked | errors | inconclusive |
|---|---|---|---|---|---|
| INPUT_TRUST | 40 | 40 | 0 | 0 | 0 |
| AUTHORITY | 30 | 30 | 0 | 0 | 0 |
| TRANSACTION | 60 | 60 | 0 | 0 | 0 |
| PAYMENT_RELIABILITY | 70 | 70 | 0 | 0 | 0 |
| WEBHOOK | 30 | 30 | 0 | 0 | 0 |
| AUDIT | 70 | 70 | 0 | 0 | 0 |
| CONCURRENCY (PostgreSQL) | 60 | 60 | 0 | 0 | 0 |
| BENIGN_CONTROL | 100 | 0 (correct) | 100 | 0 | 0 |
| KNOWN_LIMITATION | 10 | — | 10 | 0 | 0 |

The latency spread is honest rather than flattering: a scenario that runs two
complete missions costs far more than one that presents a mutated digest, and
`execute_ms` includes whichever it is. It measures this harness, not a
deployment.

### Scenario inventory

**INPUT_TRUST** — merchant prompt injection · merchant identity spoof · merchant
trust forgery · malformed agent output

**AUTHORITY** — authority escalation (hard limit) · policy mutation (all seven
protected fields) · capability escalation (five forged capability sets)

**TRANSACTION** — hard budget bypass · transaction mutation (all nine bound
fields) · authorization replay · stale authorization · policy-version mutation ·
offer-version mutation

**PAYMENT_RELIABILITY** — idempotency conflict · duplicate payment · provider
timeout after create · provider amount / currency / idempotency-key mismatch ·
wrong provider adapter

**WEBHOOK** — forged signature (four forgeries) · duplicate/replayed webhook ·
out-of-order and delayed webhook

**AUDIT** — payload tamper · event_hash tamper · previous_hash tamper · actor
tamper · payload edit *with* a recomputed hash · middle-event deletion · event
injection (refused at two layers)

**CONCURRENCY (PostgreSQL)** — concurrent authorization consumption · concurrent
same-key payment · conflicting idempotency key · outbox double-claim ·
conflicting terminal webhooks · concurrent audit append

**BENIGN_CONTROL** — the ten legitimate flows listed above

### PostgreSQL is where the races are proven

SQLite serializes writers with a whole-database lock, so a race there is refused
by the database declining to let the interleaving happen — not by the code under
test. The six concurrency scenarios declare PostgreSQL and report INCONCLUSIVE
with `BACKEND_UNAVAILABLE` when no server is reachable. They are never BLOCKED in
that case, and never silently degraded to SQLite:

```text
pg_concurrent_authorization_consumption   8 attempts -> 1 winner, 7 refused
                                          with AUTHORIZATION_REPLAY_DETECTED
pg_concurrent_same_key_payment            8 attempts -> 1 created, 1 provider payment
pg_conflicting_idempotency_key            1 created, 1 IDEMPOTENCY_CONFLICT,
                                          loser's authorization left unspent
pg_outbox_double_claim                    8 workers -> 1 claim, attempt count 1
pg_concurrent_terminal_webhook_race       success + failure -> 1 transition
pg_concurrent_audit_append                8 appends -> sequences 0..7, chain verifies
```

### Exit codes, for CI

```text
0  every hostile scenario blocked and every critical one exercised
1  an attack got through, a control was wrongly blocked, a CRITICAL scenario
   did not reach its expected outcome (including by erroring), or
   --require-postgres was set with no server
2  usage error
```

A CRITICAL scenario that ERRORs exits non-zero, deliberately: a critical control
that could not be exercised is a critical control that was not proven.

### Known limitations, reported every run

These are **not findings**. A finding is a defect to fix; a limitation is
something the design cannot do and does not claim to do. They are separate
structures with separate report sections.

| id | limitation |
|---|---|
| KL-01 | Tail truncation and whole-chain deletion are undetectable without an external anchor. **Demonstrated** by `audit_tail_truncation`, and never counted as a blocked attack. |
| KL-02 | A terminal provider failure's reason code is not in the ledger, so replay cannot reconstruct it. |
| KL-03 | Audit canonicalization is weaker than the transaction-digest encoder; historical hashes are preserved rather than rewritten. |
| KL-04 | Authorizations are server-issued, not cryptographically signed. |
| KL-05 | Merchant identity is registration-based, not cryptographic. |
| KL-06 | Reconciliation trusts a provider that positively reports holding no payment. A provider that lies can induce a duplicate — measured directly, and it is the mutation test that proves the scenario can detect one. |
| KL-07 | Reported latency is harness-local, not deployed enforcement latency. |

### Not implemented in Phase 6

No HTTP surface executes attacks — an endpoint that ran these would be an
endpoint that creates authorizations and payments, so none was added. No new
table and no migration: nothing in the kernel reads an evaluation report, and a
migration whose only purpose is to look thorough is decoration. Reports are
filesystem JSON under a gitignored `reports/attack-lab/`. No risk engine
(Phase 7), no protocol adapters (Phase 8), no frontend (Phase 9). No
cryptographic signing and no cryptographic merchant authentication, as in
Phases 3, 4 and 5.
