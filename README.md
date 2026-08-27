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
         webhook verification, fault injection; then Razorpay test
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
