# PACTRA verification evidence

The consolidated record of what was actually executed for the submission
release, what it produced, and — just as importantly — what it does not prove.

Every number here came out of a run. Nothing is estimated, extrapolated, or
asserted into existence. Where a claim would be stronger than the evidence
behind it, the weaker claim is the one recorded.

Release commit: branch `release/submission`, HEAD
`513afc019ddae1dd69accb8ae3971905078a2b96`.

---

## 1. Backend quality gates

```text
pytest        1364 tests passed
ruff          passed
mypy          passed
```

Reproduce:

```bash
make lint          # ruff check
make type-check    # mypy
make test          # pytest, in-memory SQLite; no PostgreSQL required
```

The PostgreSQL-marked tests are the authoritative ones for concurrency. They
skip loudly rather than silently when no server is reachable — a guarantee that
was not exercised must never look like one that was:

```bash
docker compose -f infra/docker-compose.yml up -d
pytest -m postgres
```

## 2. Frontend quality gates

```text
vitest              355 tests passed
tsc --noEmit        passed
eslint              passed
next build          passed (production build)
fresh-clone repro   passed
```

Reproduce, from `apps/web/`:

```bash
npm install
npm run lint && npm run typecheck && npm test && npm run build
```

Two notes, recorded rather than suppressed:

* **Two non-blocking Turbopack filesystem-tracing warnings remain** in the
  production build. They do not fail the build and no output is affected.
* **The generated reference JSON is now tracked in git.** `src/data/*.generated.json`
  is exported from backend source by `npm run export-reference`; tracking it is
  what makes a fresh clone reproduce the build without a Python environment.

## 3. Attack Lab — authored adversarial regression harness

```bash
docker compose -f infra/docker-compose.yml up -d
make attack-full
# = python -m services.attack_lab.run --all --iterations 10 --require-postgres \
#       --out reports/attack-lab/run.json
```

Result, 2026-09-04, development machine (Linux, in-memory SQLite per run, local
PostgreSQL via `infra/docker-compose.yml`):

```text
scenarios                     67
iterations                    10
total runs                   670
postgres exercised           yes

malicious runs               530   → 530 blocked, 0 not blocked
benign control runs          130   → 130 correctly allowed, 0 wrongly blocked
known-limitation runs         10   → reported separately, never counted blocked

bypasses                       0
errors                         0
inconclusive                   0
findings                       0

attack_block_rate         100.00%   = 530/530
duplicate_payment_rate      0.00%   = 0/40
replay_attack_success_rate  0.00%   = 0/30
false_positive_rate         0.00%   = 0/130
false_negative_rate         0.00%   = 0/530
reason_match_rate         100.00%   = 490/490
```

By category:

| category | runs | blocked | not blocked | errors | inconclusive |
|---|---|---|---|---|---|
| INPUT_TRUST | 40 | 40 | 0 | 0 | 0 |
| AUTHORITY | 30 | 30 | 0 | 0 | 0 |
| TRANSACTION | 100 | 100 | 0 | 0 | 0 |
| PAYMENT_RELIABILITY | 70 | 70 | 0 | 0 | 0 |
| WEBHOOK | 30 | 30 | 0 | 0 | 0 |
| AUDIT | 70 | 70 | 0 | 0 | 0 |
| CONCURRENCY (PostgreSQL) | 60 | 60 | 0 | 0 | 0 |
| ADAPTER | 130 | 130 | 0 | 0 | 0 |
| BENIGN_CONTROL | 130 | 0 (correct) | 130 | 0 | 0 |
| KNOWN_LIMITATION | 10 | — | 10 | 0 | 0 |

Harness-local latency over 670 samples: p50 9.02 ms, p95 167.09 ms,
p99 389.94 ms, min 1.27 ms, max 582.75 ms, mean 32.52 ms. This measures the
harness, not deployed enforcement (KL-07).

### What this evidence is

An **authored adversarial regression harness**. Every scenario builds hostile
input an attacker could actually build and calls the same entry points
production calls; there is no `disable_security` flag, because none exists. The
result is reproducible proof that these scenarios are refused by the real kernel.

### What this evidence is not

* **Not certification.** No standard was assessed against and none is claimed.
* **Not independent validation.** The scenarios and the system share an author.
* **Not evidence about attacks nobody wrote.** A 0% success rate is a statement
  about this corpus, not about the space of possible attacks.
* **Not a security guarantee.** Denominators exclude ERROR and INCONCLUSIVE
  runs; both were zero here, and both are reported separately when they are not.

Reports are gitignored on purpose. A fresh clone shows **RUNNER NOT CONNECTED**
in the console rather than a stale number.

## 4. Razorpay TEST MODE

Razorpay **test mode only**. A key id that does not begin with `rzp_test_` is
refused before a provider object can be constructed; placeholder or missing key,
API secret, and webhook secret values fail closed.

A real Razorpay TEST Order was created through the payment executor:

```text
Razorpay Order id                       order_TY3cA0B9NrAM4B
amount                                  ₹4,299  =  429900 paise
currency                                INR
Razorpay Order status observed          created
PACTRA payment state                    PROVIDER_PENDING
exact remote receipt matches observed   1
durable provider-create fence           set
provider ambiguity marker               null
restart proof                           zero second POST /v1/orders
```

### What this proves

A real Razorpay TEST Order was created, exactly once, by the fenced dispatch
path — and that a restart did **not** produce a second create.

### What this does NOT prove

* not **paid**
* not **captured**
* not **settled**
* no customer completed **Checkout**
* no provider **webhook** was delivered

An Order is not a Payment. The server-side API creates an Order; the Payment
appears when a customer completes Checkout, and a complete end-to-end Razorpay
payment needs a Checkout front end this repository does not build.

### The duplicate-receipt correction

We tested the assumption rather than trusting it:

> **Razorpay's TEST API accepted two Order creates with the same receipt** —
> same amount, currency, receipt, and notes.

Consequences, applied throughout this repository:

* PACTRA does **not** claim Razorpay rejects duplicate receipts.
* Receipt uniqueness is **not** an idempotence mechanism here.
* There is **no** receipt-uniqueness acknowledgement flag, and none is required.
* Provider duplicate-receipt behaviour is **not** treated as a safety guarantee.

The safety design is entirely local:

1. `UNIQUE(payment_intents.idempotency_key)` — at most one logical PACTRA payment.
2. Exactly **one** automatic initial-create permission, consumed by a durable
   one-way fence (`provider_create_fenced_at`) committed *before* the POST.
3. **Exhaustive deterministic receipt reconciliation** across every relevant
   Orders page before a create can be considered.
4. A **durable, monotonic ambiguity marker** (`provider_ambiguity_observed_at`):
   once multiple exact Orders are observed, later empty or single-match results
   cannot erase that observation or claim success automatically.
5. Restart and crash recovery perform **reconciliation only** after fence
   consumption. There is **no blind replacement create** after ambiguity or a
   crash; the intent stays uncertain until reconciliation succeeds or an
   operator reviews it.

The fence is deliberately conservative: it proves only that PACTRA consumed
create permission, never that a POST was dispatched or reached Razorpay.
Availability is traded away for duplicate-payment safety, on purpose.

## 5. Audit and replay over the real Razorpay mission

Measured on the same mission that produced `order_TY3cA0B9NrAM4B`:

```text
audit events                            22
audit verification                      AUDIT_VALID
replay                                  REPLAY_OK
replay trusted                          true
replayed vs persisted state             matched
Decision Trace stages                   ADMIT → BIND → EXECUTE
AUTHORITY_ESCALATION attempt            refused
authorization scheme                    USER_ED25519
payment state                           PROVIDER_PENDING
```

Reproduce for any mission:

```bash
curl -s http://127.0.0.1:8000/api/v1/missions/$MISSION/audit/verify
curl -s http://127.0.0.1:8000/api/v1/missions/$MISSION/replay
```

Audit and replay are **downstream evidence**, not a stage of the pipeline. The
verifier never writes, has no repair path, and reports only the first failure.
Replay is a projection gated on verification: an invalid chain yields
`trusted=false`, `state=null`, and `decision_trace=[]` — no projection at all,
rather than a projection with a warning attached.

`USER_ED25519` is a **local cryptographic demo approval proof** from one
pre-enrolled demo key. It is not verified human identity, not WebAuthn or
passkeys, not a hardware key, and not non-repudiation.

The audit ledger is a per-mission hash chain: **tamper-evident, not immutable**.
There is no blockchain, no Merkle tree, and no external anchor — which is exactly
why tail truncation and whole-chain deletion by a database attacker remain
undetectable (KL-01).

## 6. Database state

```text
migration head                 0010_provider_ambiguity
pre-migration backup           NONE existed
post-migration backup          taken and verified before runtime
```

Recorded plainly because the honest version matters: **no pre-migration backup
existed.** The verified backup was taken *after* the migration and before
runtime. Nothing in this repository should be read as claiming a pre-migration
backup was available.

## 7. Advisory risk engine evaluation

The risk engine's own evaluation is a **synthetic, authored** corpus and is
reported separately from every security number above, because a heuristic's
accuracy is not a security property.

```bash
make risk-eval
# = python -m services.risk_engine.run --evaluate --iterations 10 \
#       --out reports/risk-engine/run.json
```

17 authored scenario families × 10 deterministic repetitions = 170 assessments.
Its 100% / 0% figures are **development-set metrics** over a trivially separable
corpus with no held-out set (RL-07, RL-08, RL-09), authored by the same person
who chose the weights. They support no claim about real-world fraud. Risk
scoring is advisory only and can never allow, deny, or gate a payment.

Full treatment: the Phase 7 sections of [`../README.md`](../README.md) and
[`architecture.md`](architecture.md).

## 8. Summary of the claim boundary

| We proved | We did not prove |
|---|---|
| 1364 backend tests, ruff, mypy pass | anything about deployed production behaviour |
| 355 frontend tests, typecheck, lint, production build, fresh-clone repro pass | absence of frontend defects |
| 67 scenarios × 10 iterations, 0 bypasses, 0 errors, 0 inconclusive, 0 findings | security against attacks outside this authored corpus |
| PostgreSQL concurrency exercised | multi-node or multi-region guarantees |
| a real Razorpay **TEST** Order created exactly once, fenced, restart-safe | paid, captured, settled, Checkout completed, or webhook delivered |
| `AUDIT_VALID` + `REPLAY_OK` + trusted replay matching persisted state on a real mission | immutable storage, external anchoring, or tail-truncation detection |
| a local Ed25519 approval proof bound to one exact transaction | verified human identity, WebAuthn, passkeys, hardware keys, non-repudiation |
| deterministic refusal of an `AUTHORITY_ESCALATION` attempt | semantic fidelity between natural language and structured intent |
