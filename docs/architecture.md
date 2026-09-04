# PACTRA Architecture Notes (v2)

PACTRA is a **zero-trust adversarial transaction control plane** between
autonomous AI agents and payment infrastructure. The design assumption is that
the reasoning layer, merchant input, or a participating agent may be compromised;
transaction invariants must hold regardless. The LLM is never the security
boundary.

## Trust boundaries

```text
UNTRUSTED (must retain provenance + taint)
- user free text
- merchant descriptions, metadata, and agent responses
- LLM / agent outputs
- webhook payloads before signature verification

TRUSTED ONLY AFTER VALIDATION
- values that passed strict schemas + invariant checks
- verified authorizations (nonce + transaction digest + explicit approval origin)
- deterministic policy decisions
- provider webhooks with a verified signature

PRIVILEGED (never reachable from untrusted data or the LLM directly)
- payment executor
- authorization state and the pre-enrolled demo approver public key
- policy configuration and hard limits
- capability grants
```

## Authority lattice

Explicit, ordered authority. A lower level may never mutate state owned by a
higher level; attempts raise `AUTHORITY_ESCALATION`.

```text
USER POLICY
      >  SYSTEM SECURITY POLICY
      >  AUTHORIZATION
      >  TRUSTED INTERNAL SERVICE
      >  AGENT PROPOSAL
      >  MERCHANT DATA
```

The top level remains `USER_POLICY`, not "user-signed policy". The new proof
signs one transaction approval, not a general policy or a new authority level.
PACTRA therefore does not introduce `VERIFIED_USER_POLICY`; the existing
authority lattice remains unchanged and
the name does not claim a guarantee the code cannot deliver.

Example: merchant content asserting `budget = ₹100000` targets USER_POLICY from
MERCHANT authority → `AUTHORITY_ESCALATION` → DENY.

### Protected policy register

The full set of user-policy fields held at `USER_POLICY` authority — not just
budgets, because merchants also profit from widening the ground they are judged
on:

```text
soft_budget_inr, hard_limit_inr, currency, min_rating,
allowed_merchants, blocked_merchants, min_merchant_trust
```

Any merchant claim against any of these raises `AUTHORITY_ESCALATION`, is
recorded as a `SECURITY_VIOLATION`, and leaves the authoritative value untouched.

## Merchant identity and trust

Merchant identity and merchant reputation are **server-owned**. They never come
from the merchant payload:

```text
MerchantTransport   -> MerchantIdentity   (authenticated from the connection)
MerchantRegistry    -> MerchantRecord     (display name + trust score)
                       MerchantContext = identity + record
```

`ingest_merchant_offer(raw, context)` takes the trusted context *separately*
from the untrusted payload. Consequences:

* the provenance `source` of every merchant value is the **authenticated**
  merchant id, never `raw.merchant_id`;
* `merchant_trust` is read only from the registry — `RawMerchantOffer` has no
  such field at all, so self-assigning trust is structurally impossible;
* allow-lists, block-lists and minimum-trust checks evaluate the authenticated
  identity, so impersonation cannot bypass them;
* `raw.merchant_id` survives only as `claimed_merchant_id`. If it differs from
  the authenticated identity the offer is rejected with
  `MERCHANT_IDENTITY_MISMATCH` and a `SECURITY_VIOLATION` is appended.

The orchestrator carries `AuthenticatedQuote` values (identity + that merchant's
offers) rather than a flattened offer list, so identity is never lost between
transport and ingress.

Scope note: `IN_PROCESS_ADAPTER` authentication means identity comes from
server-side adapter registration, not from the wire. It is **not** cryptographic
authentication. Phase 2 anticipated mutual TLS / signed merchant assertions in
Phase 3; Phase 3 delivered transaction binding and authorization instead, so
cryptographic merchant authentication remains **unimplemented** and is not
claimed anywhere in the code.

## Invariant errors, not assertions

Security invariants are enforced with `require()` raising `InvariantViolation`,
never with `assert` — assertions are stripped under `python -O`, which would
silently remove the check in exactly the deployment mode where it matters most.

## Provenance model

Every security-sensitive value is wrapped with its origin and trust:

```json
{ "value": 3799, "source": "merchant-agent-7", "trust": "untrusted" }
{ "value": 4500, "source": "user-policy",       "trust": "authoritative" }
```

The kernel can answer, for any value: where it came from, who was allowed to
produce it, what authority the source held, whether it was transformed, and
whether it may influence a sensitive field.

## Taint model

Taint is carried as typed domain objects / explicit metadata — never as prompt
text. Merchant-controlled data **may** influence product description,
recommendations, rankings, and merchant-provided metadata. It **must never**
directly modify spending limits, authorization, capabilities, payment
destination, transaction policy, or approval state.

## Kernel pipeline

```text
Provenance Engine → Taint Tracking → Authority Lattice
→ Schema / Invariant Validator → Capability Firewall
→ Deterministic Policy Engine → Risk / Anomaly Engine (advisory)
→ Transaction Binding → Authorization / Human Approval
→ Replay Protection → Idempotency / Payment Reliability
→ Tamper-Evident Audit / Replay
```

Each stage is deterministic. The LLM feeds proposals into the top; nothing
downstream trusts it.

The Risk / Anomaly stage is the one stage that decides nothing. It is drawn in
the pipeline because that is where it reads from, not because anything waits on
it: Phase 7 invokes it on demand rather than from the mission path, precisely so
that risk can never become a barrier before payment. See "Advisory risk /
anomaly engine" below.

## Capability firewall

Principals hold explicit allow/deny capability sets enforced in code. A buyer
agent may `catalog.read`, `merchant.discover`, `offer.request`, `offer.rank`,
`payment.propose`; it is denied `payment.execute`, `refund.execute`,
`policy.modify`, `authorization.issue`, `merchant.modify`. A compromised LLM
cannot reach the privileged executor without a satisfied capability check.

## Transaction binding (implemented, Phase 3)

On approval, the authorization binds to the exact transaction. Nine fields are
covered:

```text
merchant_id, product_id, quantity, amount_inr, currency,
policy_version, offer_version, expires_at, nonce
```

The digest is **not** a concatenation. Naive concatenation is ambiguous —
`merchant_id="ab" | product_id="c"` and `"a" | "bc"` produce identical bytes, so
two different transactions would share a digest and one could be substituted for
the other after approval. Instead the preimage is built by
`packages/schemas/canonical.py`:

```text
transaction_digest = SHA256(
    "pactra-txn-bind-v1" || 0x1f || canonical_json({field: [type_tag, value]})
)
```

* **Structured** — sorted-key JSON, so field names are inside the preimage and
  no value can bleed across a field boundary.
* **Type-tagged** — `["i", 3799]` vs `["s", "3799"]` vs `["b", true]`; integer,
  string and boolean forms of the same token cannot collide.
* **Domain-separated** — a digest computed for one purpose cannot be replayed as
  a digest for another.
* **Float-free** — binary floats have no canonical decimal form, so the encoder
  rejects them; ratings enter the offer fingerprint scaled to integers.
* **Instant-exact** — timestamps are fixed-precision UTC, so the same moment
  hashes alike regardless of the writer's timezone.

`offer_version` is a server-computed fingerprint of the offer's
security-relevant content, and `policy_version` stamps the ruleset that
adjudicated. Because both are inside the digest, an approval cannot be carried
across an offer edit or a policy change.

`merchant_id` in the binding is always the transport-AUTHENTICATED identity,
never the merchant's self-asserted `claimed_merchant_id` — otherwise a spoofing
merchant could bind an authorization to the identity it was impersonating.

If price, merchant, product, quantity, currency, or either version changes after
approval, the digest no longer matches → `TRANSACTION_BINDING_FAILURE` → the
authorization can never be consumed.

## Authorization artifact (implemented, Phase 3)

```text
authorization_id, mission_id, transaction_digest, nonce, issued_at,
expires_at, status, policy_version, offer_version, binding_version,
consumed_at, bound_{merchant_id, product_id, quantity, amount_inr, currency},
approval_scheme, signing_key_id, approval_signature
```

```text
PENDING  --activate-->  ACTIVE  --consume-->  CONSUMED   (terminal)
   |                       |
   +-----------------------+--expire--> EXPIRED          (terminal)
   +-----------------------+--revoke--> REVOKED          (terminal)
```

The artifact remains server-issued, but its activation origin is explicit.
`POLICY_AUTO` represents a deterministic `ALLOW` and is not user approval.
`USER_ED25519` requires a LOCAL CRYPTOGRAPHIC APPROVAL PROOF from a pre-enrolled
DEMO USER-CONTROLLED SIGNING KEY. Migrated `LEGACY_SERVER` rows are explicitly
classified and fail closed for payment. The 256-bit `nonce` remains server-held
entropy; it is not a client token and is never returned or audited.

Issuance is gated by the `authorization.issue` capability, which is held only by
the `security-kernel` principal and explicitly **denied** to `buyer-agent`. That
is what makes `LLM OUTPUT -> NEVER AUTHORIZATION` structural rather than a
convention. A `DENY` policy decision issues no authorization at all.

## Replay protection and concurrency (implemented, Phase 3)

Every privileged state transition is a SINGLE atomic conditional UPDATE whose
WHERE clause carries the entire precondition. The database's `rowcount` is the
only thing that decides whether the transition happened:

```sql
UPDATE authorizations
   SET status='CONSUMED', consumed_at=:now
 WHERE authorization_id=:id
   AND status='ACTIVE'              -- not already consumed/revoked/expired
   AND transaction_digest=:digest   -- bound to THIS exact transaction
   AND expires_at > :now            -- still inside its window
```

There is deliberately no read-then-write and no in-memory boolean on the
decision path. Two requests that both observed `ACTIVE` will both issue this
UPDATE; exactly one gets `rowcount == 1`. The loser is told
`AUTHORIZATION_REPLAY_DETECTED` and changes nothing. The row is re-read after a
*failed* UPDATE only to classify why it failed — that read never grants
anything, because the transition was already refused by the database.

Storage-level invariants:

```text
authorizations.nonce UNIQUE
(status = 'CONSUMED') = (consumed_at IS NOT NULL)
```

The UNIQUE constraint makes a duplicated nonce impossible; the CHECK makes an
inconsistent consumption record impossible. Protection against *double*
consumption is the conditional UPDATE above, not either constraint.

Audit events for the lifecycle: `AUTHORIZATION_CREATED`,
`AUTHORIZATION_ACTIVATED`, `AUTHORIZATION_CONSUMED`, `AUTHORIZATION_EXPIRED`,
`AUTHORIZATION_REVOKED`, `AUTHORIZATION_REPLAY_DETECTED`,
`TRANSACTION_BINDING_FAILURE`. Payloads carry a truncated digest prefix — enough
to correlate events across a mission, not enough to be a copy of the artifact —
and never the nonce. Successful `USER_ED25519` activation instead records the
full digest plus safe scheme/key/authorization metadata; it never records the
signature or private key.

## LOCAL CRYPTOGRAPHIC APPROVAL PROOF (signed-authorization hardening)

The fixed algorithm is Ed25519 and the fixed domain is
`pactra-user-approval-v1`. Using the same type-tagged, sorted canonical encoder
as transaction binding, the server constructs:

```text
"pactra-user-approval-v1" || 0x1f || canonical_json({
  authorization_id, mission_id, binding_version,
  transaction_digest, signing_key_id
})
```

The signature encoding is exactly 128 lowercase hexadecimal characters (64
bytes). No endpoint accepts an algorithm, public key, arbitrary JSON message,
or caller-provided message bytes. The configured signing key ID resolves one
pre-enrolled public key. The corresponding private key is generated, stored,
and used only by the external demo signer.

The Phase 3 `pactra-txn-bind-v1` digest and its nine bound fields are unchanged.
The approval protocol signs that authoritative digest plus mission,
authorization, binding-version, and key context; it does not define another
transaction canonicalization. The challenge exposes those canonical fields,
exact message bytes as hex, and a readable merchant/product/quantity/amount/
currency/expiry summary. It does not expose the nonce, so the demo signer cannot
independently reconstruct the transaction digest.

Verification is fail-closed at three points:

1. before atomically changing `PENDING` to `ACTIVE`;
2. inside intent creation before consumption, intent/outbox insertion, or
   mission transition; and
3. inside dispatch immediately before provider lookup/create, together with a
   durable intent/authorization comparison.

Invalid proofs that reach the approval handler have their safe rejection audit
committed before an HTTP error is raised. Request-schema failures occur before
the handler and have no mission audit event. The security kernel is the single
source of `AUTHORIZATION_ACTIVATED`, removing the former route/orchestrator
duplicate.

This proves only local transaction approval by the configured demo key. It is
not production user identity, WebAuthn or passkey support, non-repudiation,
cryptographic merchant authentication, or independent security validation.
Limitations: one demo approver; no user/account system or authenticated approval
HTTP principal; local-key theft compromises approval; no credential recovery or
rotation UX; no trusted payment-detail display; broad server/provider compromise
is outside this proof; merchant authentication and external audit anchoring are
absent.

## Payment reliability (implemented, Phase 4)

Side effects are made reliable without unnecessary distributed complexity:

```text
DB TRANSACTION { PaymentIntent, AuthorizationConsume, AuditEvent, OutboxEvent }
      → COMMIT → Worker (separate process) → Payment Provider
```

The outbox row is written in the SAME transaction as the intent, so after
COMMIT the instruction to call the provider is exactly as durable as the
decision to pay. Combined with `payment_intents.idempotency_key UNIQUE` and
`provider_payment_id UNIQUE`, retries and crashes yield at most one logical
payment.

### The uncertain state is a first-class state

`PROVIDER_PENDING` exists because a provider timeout is not a failure — it is an
absence of information. A payment may or may not have been created. Resolving
that by guessing is the duplicate-charge bug in one direction and the
phantom-settlement bug in the other, so it is not resolved by guessing at all:

```text
PROCESSING --timeout--> PROVIDER_PENDING --reconcile--> SUCCEEDED
                                                      | FAILED_TERMINAL
                                                      | FAILED_RETRYABLE
```

For a provider with a verified idempotent-create contract, a positive not-found
lookup can make an intent retryable. Razorpay has no such verified contract, so
its durable create fence is permanent and an empty lookup remains uncertain.

### Never a blind retry

Before any Razorpay receipt lookup, the executor re-verifies authorization proof
and binding, atomically acquires `provider_create_fenced_at`, and commits it while
state remains `QUEUED`. Only that fence winner can continue toward the possible
initial POST. It re-verifies after the commit, exhausts exact deterministic-
receipt search, and re-verifies once more before POST when the result is empty.
The timestamp means create permission was consumed, not that provider I/O
occurred. Fenced recovery only searches: zero matches remain uncertain, one is
adopted, and multiple matches persist `provider_ambiguity_observed_at`. Once
observed, later weaker empty/single results cannot erase that ambiguity or claim
automatic success.

### A provider response may report state, never redefine the transaction

Provider responses are untrusted input even when the HTTP status is 200. Each is
checked against the durable intent — provider, amount, currency, idempotency key
— BEFORE `provider_payment_id` is linked and before any terminal transition. A
mismatch raises `PROVIDER_RESPONSE_MISMATCH`: nothing is linked, nothing is
settled, and the intent stays uncertain pending reconciliation.

The key check is strictest where correlation is weakest. While no provider
payment is linked, the idempotency key is the ONLY thing tying a response to
this intent, so a response omitting it — or naming a different key — is refused.
A payment with a coincidentally matching amount and currency must never be
adopted; settling against another party's charge is worse than a duplicate.
Once an id IS linked, the id is the correlation, and `link_provider_payment`
raises rather than relinking a different one — overwriting would hide a
duplicate and leave the first charge unreferenced.

### Worker claim/work split

Claiming and Razorpay fence/result handling run across durable boundaries:

```text
TX 1  claim event, persist IN_PROGRESS lease + attempt count  COMMIT
TX 2  verify, persist one-way create fence while QUEUED       COMMIT
TX 3  re-verify, exhaust receipt search, and only for the
      fence winner + zero matches, re-verify and invoke create COMMIT
```

A crash during provider I/O leaves a durable `IN_PROGRESS` lease rather than
rolling the claim back to an indistinguishable `PENDING`. Recovery is the lease
lapsing, so crash recovery falls out of the same field that schedules retries
instead of needing a reaper. The cost is that a slow dispatch can be re-claimed
while still running, which is why every handler is idempotent regardless.

Dead-lettering marks the outbox row `FAILED` but deliberately does NOT make the
payment intent terminal: "automatic recovery gave up" is a weaker claim than
"this payment definitively failed", and only the weaker one is supported.

### Webhooks

Verify (HMAC over RAW bytes, constant-time) → resolve the payment from
server-side state by `provider_payment_id` → deduplicate on
`UNIQUE(provider, provider_event_id)` → apply only what the state machine
permits. The webhook supplies a pointer, never an amount, merchant, or
authorization, so a verified-but-hostile webhook cannot restate what a payment
was for. Conflicting concurrent webhooks serialize on a `SELECT … FOR UPDATE` of
the intent row, so exactly one terminal transition applies.

A rejected signature is NOT audited. The ledger is mission-scoped and the only
thing naming a mission in a rejected delivery is the payload whose MAC just
failed; writing the event would mean picking a chain on the authority of a
forged body. A transport-scoped security log is the right home for rejections
and Phase 4 does not build one — so no code or comment claims a rejection event
exists.

### Audit sequence under concurrency

`append_event` takes a `SELECT … FOR UPDATE` on the mission row before
allocating a sequence. The `UNIQUE(mission_id, sequence)` constraint catches
duplicates, but only the row lock makes concurrent legitimate appends wait and
then observe the sequence the prior writer committed, keeping the chain
contiguous and its `previous_hash` links valid.

### Capability enforcement at privileged boundaries

Both privileged boundaries — `authorization.issue` and `payment.execute` — go
through `enforce_registered`, which re-resolves the principal against the
server-owned registry and requires the presented set to EQUAL it. A
`CapabilitySet` is a plain Pydantic schema, so untrusted code can construct one
that merely claims a capability; validating that claim against itself would make
the guard self-certifying. Principal authentication remains the trusted caller's
responsibility — the worker selects its principal internally, and no HTTP route
accepts one.

### Backend differences, stated rather than papered over

SQLite serializes writers with a database-wide lock and ignores `FOR UPDATE`; a
concurrency test there is refused by the database rather than by the code under
test. PostgreSQL is therefore AUTHORITATIVE for concurrent authorization
consumption, concurrent same-key creation, idempotency conflicts, payment row
locking, webhook races, `SKIP LOCKED` outbox claiming, and audit sequence
serialization. Those tests skip loudly when no server is reachable. No
production behaviour is weakened to make SQLite reproduce PostgreSQL semantics.

## Tamper-evident audit ledger (implemented, Phase 5)

```text
event_id, mission_id, sequence, event_type, actor, payload,
previous_hash, event_hash, created_at
```

`event_hash = SHA256(canonical_json({mission_id, sequence, event_type, actor,
payload, previous_hash, created_at}))`, with `previous_hash` inside the
preimage. Tamper-evident, **not** a blockchain.

### One hash function, both directions

`compute_event_hash` is the only place an event hash is produced. The ledger
calls it when appending; the verifier calls it when recomputing. There is
deliberately no second "verification" implementation — a verifier that hashes
slightly differently from the writer either reports tampering that did not
happen or misses tampering that did, and the drift stays invisible until it
matters.

### Audit payload canonicalization

`created_at` is inside the preimage, so the verifier has to present the exact
instant the writer did. The writer always passes an aware UTC value, but SQLite
has no timezone-aware type and returns a **naive** datetime on read, whose
`isoformat()` omits the `+00:00` offset. Recomputing from a persisted row
therefore produced a different hash from the one stored beside it — every chain
verified inside the writing session and failed the moment it was re-read, which
is exactly the condition `/verify` runs under.

The fix is `as_utc` normalization **inside** `compute_event_hash`, so both
callers get it. It is exact rather than a guess: values are written as UTC
unconditionally, so attaching UTC on read restores the original instant. For an
already-aware UTC input — every value the writer has ever passed — the encoding
is byte-identical, so **no historical event hash changed**. A test pins that.

Canonical JSON gives stable dict key order (`sort_keys`), compact separators,
and an exact JSON round trip for the strings, integers, booleans, nulls, nested
objects and float values these payloads carry.

**Compatibility limitation, stated rather than reconciled.** This is NOT the
type-tagged, domain-separated encoder in `packages/schemas/canonical.py` used
for transaction digests. That encoder is stronger — it makes `1`, `"1"` and
`true` unable to collide and rejects floats outright — but switching the audit
chain to it would change the preimage of every event and invalidate every
`event_hash` already written. Historical hash semantics are preserved instead.

### Verification

```text
GET /api/v1/missions/{id}/audit/verify   ->  { "valid": true, "events_checked": 17 }
```

Order events by `sequence`, then per event: structure → position → genesis →
linkage → recomputed hash. Only the FIRST failure is reported; tampering with
one event invalidates its own hash and every link after it, so listing all of
them would present one act of tampering as dozens of findings.

```text
AUDIT_VALID | AUDIT_SEQUENCE_GAP | AUDIT_PREVIOUS_HASH_MISMATCH
AUDIT_EVENT_HASH_MISMATCH | AUDIT_GENESIS_INVALID | AUDIT_EVENT_MALFORMED
```

The verifier **never writes**. Not to `event_hash`, `previous_hash`, `sequence`,
or `payload`; there is no repair path and no recompute-on-read. Tamper evidence
is worthless if the verifier repairs what it exists to detect.

### What a per-mission chain cannot detect

Stated as gaps, because they are:

* **Tail truncation.** Deleting the last k events leaves `0..N-k-1` — still
  contiguous, still correctly linked. Detecting it needs an anchor outside the
  chain (a signed head, an external witness, a cross-mission ledger). Phase 5
  builds none of those.
* **Whole-chain deletion.** A mission with no events is indistinguishable from
  one whose events were all removed. Same missing anchor.

Deleting a MIDDLE event, reordering, renumbering, injecting an event, and any
edit to a hashed field are all detected.

## Event history + replay (implemented, Phase 5)

```text
EVENT HISTORY  ->  PURE DETERMINISTIC REDUCER  ->  RECONSTRUCTED STATE
```

Replay is a **projection, not a rerun**. It does not call a merchant, a payment
provider, the authorization issuer, the payment executor, or a webhook handler;
it creates no payment, consumes or issues no authorization, appends no audit
event, and writes no row. That is structural rather than disciplinary:
`services/audit_ledger/replay.py` imports nothing from
`services.payment_executor`, `services.security_kernel`, or the merchant
adapters, and a test parses the module's imports to keep it so. The only
`services` imports are the mission state-machine predicates and the ledger's
read path.

`reduce_events` reads no clock, generates no UUID, consults no environment, and
performs no I/O. Timestamps in the projection are copied verbatim out of event
payloads as strings — never parsed and re-formatted, because a round trip is
where a precision or locale choice would sneak in.

### The integrity gate

```text
events -> verify chain -> invalid ? replay REFUSED (trusted=false, state=null)
                       -> valid   ? deterministic replay
```

An invalid chain yields **no projection at all** — not a projection with a
warning attached. A caller handed a state object will use it, and a flag beside
it does not stop that. `reduce_events` remains callable directly for
diagnostics; the API only reaches it through the gate.

### Reconstructing the payment state

The payment state is read from the `state` field `apply_payment_transition`
stamps into every payment transition payload — never inferred from the event
type. `PAYMENT_FAILED` is emitted for BOTH a retryable and a terminal failure,
and only the recorded state distinguishes them. Mission-state advance uses the
same `can_transition` guard as `apply_mission_state`, so an illegal move is
skipped and recorded rather than forced — which is what makes the replayed state
*equal* the persisted state instead of merely resembling it.

### Unknown events: fail closed

Audit events carry no schema or version field, and Phase 5 adds none — a
migration whose only purpose is to look forward-compatible is decoration. The
policy is about the thing that actually varies: an `event_type` this build does
not recognize.

That policy is REFUSAL (`REPLAY_UNSUPPORTED_EVENT_TYPE`). An unrecognized event
may be a security event, and a projection that silently drops it does not merely
omit information — it misrepresents what happened while presenting itself as a
faithful reconstruction. Every event type this build declares has a handler, and
a test asserts the handler table equals the `EventType` enum exhaustively, so a
new event type added without a reducer rule fails a test rather than distorting
a projection. A known type with an uninterpretable payload is refused the same
way (`REPLAY_MALFORMED_EVENT`).

### Persisted-state comparison

```text
{ "replay_state": "PAYMENT_SUCCEEDED", "persisted_state": "PAYMENT_SUCCEEDED",
  "matches": true }
```

DIAGNOSTIC ONLY. A mismatch is reported and **nothing is repaired**. Replay is
observability here, not recovery: the rows are what the kernel enforces against,
and letting a reconstruction overwrite them would hand authority to the derived
view. Where neither side holds an authorization or a payment, the comparison
reports `null` rather than `true` — claiming agreement about something that does
not exist is an assertion with no content behind it.

### Replay reason-code provenance

C1 writes a payment transition's stable `reason_code` into the same source
audit event as the transition. Replay and Decision Trace copy that recorded
value; they do not infer a reason from the event type or consult the mutable
PaymentIntent row.

## Adversarial Attack Lab (implemented, Phase 6)

```text
registry (explicit registration)
     ↓
runner: isolated backend per run → setup(ctx) → execute(ctx, state) → Observation
     ↓                              ↑ INCONCLUSIVE       ↑ ERROR
evaluation: N iterations × M scenarios → AttackRunReport
     ↓
metrics (measured) + text/JSON report + CLI exit code
```

`services/attack_lab/` runs 47 registered scenarios — 36 malicious, 10 benign
controls, 1 demonstrated known limitation — through the REAL kernel. Nothing
here is a stub that returns `blocked=True`.

### The lab constructs hostile inputs; it never relaxes a control

There is no `disable_security` flag, no test mode that weakens a check, and no
path that writes a privileged status past the kernel. Scenarios build the things
an attacker can actually build — a merchant adapter that lies about its
identity, a payload carrying injected instructions, a forged `CapabilitySet`, a
provider that answers 200 OK describing a different transaction — and call the
same entry points production calls. The one exception is the audit-tamper group,
which corrupts database rows DIRECTLY, because that is exactly what an attacker
with database access does and it is the only way to test the verifier rather
than the writer.

Legitimate starting state is built by CALLING `issue_authorization` and
`activate_authorization` under the `security-kernel` principal, never by
inserting a row with `status='ACTIVE'`. An authorization forged by direct INSERT
would let a scenario "prove" a control that never ran.

### Prompt injection is measured as causal influence, not as string absence

Searching an audit log for "ignore the budget" tests the search, not the system.
The scenario instead runs two full missions whose offers are byte-identical in
every security-relevant field and differ ONLY in free-form text, then compares
the outcomes: decision, amount, ranking, bound transaction, event sequence. If
injected content had any authority, the two would diverge. Equality across the
whole snapshot is the finding; the canary search runs too, as a weaker second
check.

### Fail closed: an exception is not a block

```text
setup raises            -> INCONCLUSIVE   (the attack never ran)
declared backend absent -> INCONCLUSIVE   (BACKEND_UNAVAILABLE)
execute raises          -> ERROR          (proved nothing, in either direction)
execute returns         -> BLOCKED / NOT_BLOCKED, from the measured Observation
```

"Expected AUTHORIZATION_REPLAY_DETECTED, got a TypeError" is a scenario that
proved nothing, and recording it as a security success would be the exact
fabrication this phase exists to prevent. ERROR and INCONCLUSIVE runs are
excluded from every rate's denominator and reported separately — never counted
on the safe side.

Two failures caught during construction are worth recording, because both would
have produced a confident wrong answer:

* The timeout-after-create scenario drove the worker with `drain`, which loops
  until the outbox empties. Handling a lost response enqueues its OWN
  reconciliation, so one drain ran both turns and the scenario sampled the state
  after reconciliation had already resolved it — reporting NOT_BLOCKED while the
  financial invariant had held perfectly. Stepping one event at a time is what
  makes the intermediate uncertain state observable.
* The audit tampers were written as raw SQL binding `str(mission_id)`.
  SQLAlchemy's `Uuid` column stores dash-less hex on SQLite, so every tamper
  matched zero rows, the untouched chain verified, and all six scenarios reported
  the verifier as broken. They now use typed Core statements AND assert the
  statement changed a row; a tamper that touched nothing raises rather than
  reporting a verdict.

### Benign controls, and why FP/FN needs them

A kernel that denied every request would score a perfect block rate. Ten benign
controls run the same real paths with `expected_status = NOT_BLOCKED`, so a
control that comes back BLOCKED is counted as a false positive rather than
quietly re-labelled. Without them there is no honest false-positive rate at all.

### Metric definitions

Denominators exclude ERROR and INCONCLUSIVE; a rate over an empty denominator is
`None` and renders as `n/a`, never as 0% or 100%.

```text
attack_block_rate            = blocked / decisive malicious runs
attack_success_rate          = not_blocked / decisive malicious runs
false_negative_rate          = the same quantity (stated, not disguised)
false_positive_rate          = controls blocked / decisive control runs
invariant_preservation_rate  = invariant_preserved is True / runs that measured one
replay_attack_success_rate   = replays with an unauthorized effect / replay attempts
duplicate_payment_rate       = runs with >1 logical or >1 provider payment / attempts
reason_match_rate            = observed code == expected code / runs declaring one
p50/p95/p99                  = nearest-rank over execute_ms of decisive runs
```

`false_negative_rate` and `attack_success_rate` are identical under these
definitions — a false negative IS a hostile scenario that came back
NOT_BLOCKED. Both names are reported because both are asked for, and the equality
is stated rather than hidden by computing them from slightly different subsets.

Latency is harness-local: in-process, in-memory SQLite (local PostgreSQL for the
concurrency group), no network and no concurrent load. It detects a regression
in this harness; it is not a deployed-enforcement figure.

### Findings are derived, never authored

`derive_findings` builds a `SecurityFinding` only from a hostile run that
actually came back NOT_BLOCKED, copying that run's own measured effects in as
evidence. There is no function that could produce one otherwise, which is how
"do not invent findings" is enforced rather than merely intended.

Known limitations are a SEPARATE structure. A finding is a defect that should be
fixed; a limitation is something the design cannot do and does not claim to do.
Reporting them together would make the honest disclosures look like defects.

### Scenario isolation

Every SQLite run gets its own in-memory engine with a freshly created schema,
disposed afterwards; every PostgreSQL run truncates first. If scenario N could
observe rows scenario N-1 left behind, "the payment intent count did not change"
would stop being evidence about scenario N.

### PostgreSQL is where the races are proven

The six CONCURRENCY scenarios declare `Backend.POSTGRES`. With no server they
report INCONCLUSIVE with `BACKEND_UNAVAILABLE` — never BLOCKED, and never
silently degraded to SQLite, where the loser of a race is refused by the
database rather than by the code under test.

### CLI

```bash
python -m services.attack_lab.run --list
python -m services.attack_lab.run --all
python -m services.attack_lab.run --scenario authorization_replay
python -m services.attack_lab.run --category TRANSACTION --iterations 10
python -m services.attack_lab.run --all --json --out reports/attack-lab/run.json
```

Exit 0 when every hostile scenario was blocked and every critical one exercised;
exit 1 on a bypass, a wrongly-blocked control, a CRITICAL scenario that did not
reach its expected outcome (including by erroring), or `--require-postgres` with
no server. A critical control that could not be exercised is a critical control
that was not proven.

**CLI only.** No HTTP surface executes attacks. An endpoint that ran these would
be an endpoint that creates authorizations and payments, so Phase 6 does not add
one. Reports are filesystem JSON under a gitignored `reports/attack-lab/`; no
migration and no table were added, because nothing in the kernel reads them.

## Advisory risk / anomaly engine (implemented, Phase 7)

```text
mission rows + merchant registry + audit ledger
        ↓  features.py        READ-ONLY SELECTs, every value carries its source
        ↓  anomaly.py         merchant-scoped baseline, or an explicit refusal
        ↓  heuristic.py       20 declarative rules → RiskFactor list → points
        ↓  normalize          score = min(1, points / saturation)
        ↓  band → recommendation
        ↓  explain.py         text built FROM the contributions, never a model
        ↓  RiskAssessment     advisory: Literal[True]
```

`services/risk_engine/` scores a mission, explains the score, and recommends an
action. It decides nothing. The deterministic kernel — provenance, authority
lattice, capability firewall, policy engine, transaction binding, authorization,
replay protection, idempotency — is unchanged by Phase 7 and remains the only
thing that can permit or refuse a transaction.

### RISK SCORE ≠ AUTHORITY, made structural

The rule is enforced by things that do not exist rather than by discipline:

* **The vocabularies are disjoint.** `RiskRecommendation` is `PROCEED / REVIEW /
  REQUIRE_STRONGER_APPROVAL / ESCALATE`. It has no `ALLOW` and no `DENY` — those
  belong to `PolicyOutcome` — so no log line, report, or API response carrying a
  risk value can be read as an adjudication, and no downstream branch on a
  string can confuse the two.
* **`RiskAssessment` has no field to act on.** No authorization id, no capability,
  no decision, no override. `advisory` is a `Literal[True]`, so a non-advisory
  assessment fails validation rather than being constructed.
* **The engine cannot reach anything privileged.** The risk core imports nothing
  from `services.payment_executor`, `services.security_kernel.authorization`,
  `services.security_kernel.binding`, the merchant adapters, or the
  orchestrator. `tests/test_risk_isolation.py` parses the import graph of every
  core module and fails if it ever can, then replaces every side-effecting
  function with a landmine, then counts every table before and after.
* **`assess_mission` takes no score, band, threshold, weight, or capability.**
  There is no parameter through which a caller could supply one, and neither
  HTTP route declares a request body at all.

A `CRITICAL` assessment of an `ALLOW` mission leaves it `AUTHORIZED` with a
spendable authorization. A `LOW` assessment of a `DENY` mission leaves it
`CANCELLED` with no authorization at all. Both are asserted.

### What the score means, stated precisely

```text
score = min(1, accumulated points / saturation_points)     saturation = 1.0
```

A **normalized risk index** in `[0, 1]`. It is **not** a fraud probability and is
never described as one: no data exists against which a probabilistic reading
could be calibrated, so `score_semantics` is a pinned literal
(`NORMALIZED_RISK_INDEX`) on every assessment and a test sweeps the package for
the phrase.

Bands: `LOW < 0.25 ≤ MEDIUM < 0.50 ≤ HIGH < 0.75 ≤ CRITICAL`. What IS calibrated
is the band scale, and only that: one severe signal reads HIGH, two read
CRITICAL. `CRITICAL` is not `DENY`.

### Four weight tiers, not twenty magic numbers

Every number lives in one frozen, server-owned `RiskConfig`. Each of the 20
factors is assigned one of four documented tiers, which forces the real question
— *how strong is this evidence?* — onto a scale a reader can hold in their head:

```text
WEAK      0.05  a mild signal, or one the deterministic kernel already owns
MODERATE  0.15  a genuine concern on its own
STRONG    0.35  evidence of adversarial or malfunctioning behaviour
SEVERE    0.60  behaviour with no benign explanation
```

Factors grade with `ramp(value, lo, hi)` rather than firing on a threshold
comparison. A cliff at `0.9 × hard_limit` is a line an adversary can sit just
under; a ramp is also monotone by construction, which is what lets Hypothesis
check *more of a risky thing never contributes less risk* across the whole input
range instead of at hand-picked points.

Nothing can subtract. A long clean record must not net out a single
identity-spoof event, so contributions are strictly positive and reasons to be
reassured stay out of the arithmetic.

**Exceeding the soft budget is deliberately WEAK.** The policy engine already
turns it into `REQUIRE_APPROVAL` — an actual control with actual authority.
Weighting it heavily here would double-count a control PACTRA already has and
would drift the advisory number toward looking like the decision. The risk engine
is most useful where the kernel is silent.

### Feature provenance: a number is not trusted for being numeric

`FEATURE_SPECS` is the authoritative table of what each feature reads and at what
authority, reusing the kernel's own `AuthorityLevel` / `TrustLevel` rather than a
parallel vocabulary. Three rules it encodes:

* **Merchant trust comes from the server-owned `MerchantRegistry`, never a
  payload.** `RawMerchantOffer` has no `merchant_trust` field and `extra="ignore"`
  drops the key, so a merchant asserting `trust: 1.0` has it discarded at the
  schema boundary — the defence is structural and the risk engine simply never
  goes looking. `FeatureSource.MERCHANT_PAYLOAD` exists in the enum and is
  deliberately unused; a test asserts no feature claims it.
* **Audit-derived counts keep their provenance.** Several features count
  `SECURITY_VIOLATION` events: records the KERNEL wrote, about behaviour a
  MERCHANT attempted. `derived_from_untrusted_evidence=True` travels with those
  values and is rendered in the explanation, rather than being laundered into
  "trusted, because the row is ours".
* **Absent is not zero.** A feature with nothing behind it is `available=False`
  with a reason, never `0.0`. "No prior payments with this merchant" scored as "a
  perfect payment record" is the easiest way to make a risk engine quietly wrong
  in the direction that costs money.

Identity-spoof counts are attributed to the AUTHENTICATED merchant, never the
one it impersonated — otherwise the victim carries the finding.

### What PACTRA cannot baseline, stated rather than approximated

**There is no user identity in the data model.** `missions` has no owner, no
account, no session principal. So every user-scoped feature the risk brief lists
— spend deviation from the user's history, transaction velocity, distinct-merchant
counts, repeated high-value attempts — is **absent**, not estimated. Every
explanation says so:

```text
scope: PACTRA has no user identity in its data model, so no per-user spending
baseline, velocity, or behavioural deviation was computed or approximated.
History is scoped by authenticated merchant only.
```

What CAN be baselined is per-merchant: `authorizations.bound_merchant_id` /
`bound_amount_inr` are server-written records of transactions actually approved
against an authenticated identity. Authorizations rather than settled payments,
because most missions legitimately stop at approval and a payment-only
population would sit below the observation gate almost always, leaving the
anomaly layer permanently dark. The **median** rather than the mean: the mean is
moved by the single largest prior transaction, which is exactly the observation
an attacker would like to contribute.

Two features are also deliberately absent because their source is empty by
design: rejected-webhook counts (Phase 4 does not audit rejected signatures — the
only thing naming a mission in a forged delivery is the payload whose MAC just
failed) and capability-denial counts (raised as an exception, never audited).
Implementing them would produce features that are permanently zero.

### Cold start is handled, not scored

Below `min_history_observations` (5) the anomaly features report
`INSUFFICIENT_HISTORY` and contribute exactly nothing — no global default, no
prior, no smoothed estimate. "This purchase is 3.1× the median" computed from two
observations has the shape of evidence and none of the substance.

Cold start itself adds **no** risk. Not knowing a counterparty is not evidence
against them, and scoring it would make every first transaction suspicious. The
distinction that does score is different: an authenticated merchant ABSENT FROM
THE REGISTRY has no reputation, which is a fact the server owns, not knowledge
the server lacks. `MERCHANT_UNKNOWN` is `STRONG`; cold start is zero. A test
pins both halves.

`DataQuality` reports observation counts instead of a "confidence" number: a
confidence figure implies a calibrated posterior, and nothing here is calibrated.

### Explanations come from the arithmetic

```text
+0.600  AUTHORIZATION_REPLAY_HISTORY: 1 authorization replay attempt(s) were
        detected and refused on this mission (100% of the available weight)
+0.123  AMOUNT_NEAR_HARD_LIMIT: the amount is 96% of the hard limit, leaving
        little headroom before the absolute ceiling (82% of the available weight)
```

`sum(factor.contribution) == raw_points` exactly — asserted by a unit test and by
a Hypothesis property — so a reader can add the column up and get the score. No
LLM is anywhere in this path, and no risk module may import one (a test checks
the import graph). An explanation is the only part of a score a human reads, so
it is the only part that can lie convincingly; the honest construction is the
mechanical one.

A factor exists only when it contributed something. An empty explanation says
"no risk factors contributed" rather than nothing at all, because silence reads
as "nothing was checked".

### Placement: on demand, not in the mission path

```text
GET  /api/v1/missions/{id}/risk          computes, writes NOTHING
POST /api/v1/missions/{id}/risk/assess   computes, records one RISK_ASSESSED event
```

The orchestrator does **not** call the risk engine, and this is a decision rather
than an omission. Emitting an advisory event on every mission would put it
permanently inside the hash-chained history Phase 5's replay reconstructs, would
change every mission's event sequence, and would give the enforcement path a step
whose only output is advice. Risk must never be a barrier before payment; the
cleanest guarantee is that the payment path never calls it. The cost is real and
is listed as remaining debt (RL-05): a mission nobody asks about has no
assessment.

Neither route accepts a body. Weights reach the engine only from the frozen
module binding, so a request cannot score itself against different rules. A HIGH
band returns 200 with advice — a route that returned 403 would be enforcing.

### The RISK_ASSESSED event is inert in replay

Audit events carry no version field, and Phase 5's reducer refuses an event type
it does not recognise, so a new type cannot be silently dropped from a
reconstruction. `RISK_ASSESSED` therefore gets a handler — and that handler
touches nothing except a list no other rule reads. A mission replayed with the
event present reconstructs identically to one without it; a test compares the
whole projection field by field.

It is **not** in `SECURITY_EVENT_TYPES`. A risk assessment is an opinion, and
listing it beside `AUTHORIZATION_REPLAY_DETECTED` would put an opinion in the
ordered history of refusals.

The advisory reducer is deliberately lenient where every enforcement reducer
refuses: a malformed `SECURITY_VIOLATION` means the security history cannot be
reconstructed, while an unreadable advisory note costs the projection nothing.
Refusing a whole replay because an advisory note was corrupt would hand the
advisory layer the power to break a reconstruction — precisely the authority it
must not have. Inert in the reducer does not mean exempt from the hash chain: a
tampered `RISK_ASSESSED` payload still fails `/audit/verify`.

The payload carries the verdict, the factor CODES, and the versions — never raw
feature values, never the weight table, never a full digest.

### No migration

No `risk_scores` table. Assessments are computed on demand and optionally
persisted as an existing-shape audit event; `audit_events.event_type` is
`String(40)` and `payload` is `JSON`, so no DDL is required. `alembic check`
reports no new upgrade operations. Nothing in the kernel reads a risk row, so a
table would be decoration.

### Measured evaluation (SYNTHETIC corpus)

17 labelled scenarios × 10 iterations = 170 assessments, run through the REAL
kernel in Phase 6's isolated per-run databases. **Every label is authored, not
observed.** No real fraud data exists in this project and none is claimed.

```text
benign mean score      0.0200        risky mean score   0.5090
mean separation        0.4890
review threshold       0.25   (the operating point the engine actually uses)
risk detection rate    100.00%   (100/100 risky flagged)
false positive rate      0.00%   (0/70  benign flagged)
false negative rate      0.00%   (0/100 risky missed)
p50 / p95 / p99        10.87 / 17.96 / 24.64 ms   (harness-local; KL-07 applies)
deterministic across iterations: true
```

Threshold sweep, reported and not tuned — nothing fits an operating point to
these results:

```text
threshold   detection            false positives
     0.10   100.00% (100/100)    14.29% (10/70)
     0.25   100.00% (100/100)     0.00% (0/70)   <- configured
     0.50    50.00% (50/100)      0.00% (0/70)
     0.75    10.00% (10/100)      0.00% (0/70)
```

`risk_detection_rate` is **not** `attack_block_rate`. The block rate is a Phase 6
security guarantee about the deterministic kernel; this is a quality measurement
of an advisory heuristic over a synthetic corpus. They are separate metrics,
computed by separate code over separate corpora, and conflating them would let a
heuristic's accuracy be read as a security property.

**Read the 100% / 0% honestly.** The exact supportable claim is "100% detection
and 0% false positives across the 17 authored synthetic Phase 7 evaluation
scenario families, at the configured review threshold of 0.25, across 10
deterministic repetitions each" — not "100% fraud detection" and not "0% false
positives in the real world". The corpus is small, trivially separable, authored
after the weights by the same author, and there is no held-out set (RL-07..RL-09
below). What these numbers legitimately support: the heuristic separates the two
halves of this corpus, reproduces exactly across repetitions, and does not flag a
legitimately-approved high-value purchase. What they do not support: any claim
about real-world fraud, or about cases the corpus does not contain.

### How the review threshold was chosen — and what that means for the metrics

`review_threshold = 0.25`, and it is **not a free parameter**: it is the MEDIUM
band boundary, tied to it structurally and pinned by
`test_review_threshold_is_the_medium_boundary`. The band boundaries were derived
from the four weight tiers (one SEVERE = 0.60 reads HIGH; two SEVERE saturate to
CRITICAL), and that derivation is documented on the constants themselves in
`config.py`. It was **not** re-tuned after observing evaluation results, and it
cannot drift into a tunable without failing that test.

**But there is no held-out set, and none is claimed.** The 17 scenarios were
authored *after* the weights and threshold existed, by the same author. The
corpus was therefore constructed with knowledge of the scoring rules, which
makes every number below a **development-set metric**, not a generalization
estimate. Reported as RL-07.

### The corpus is trivially separable — stated, because it changes the reading

```text
minimum risky score      0.2807   (risky_amount_anomaly)
maximum benign score     0.1307   (benign_high_value_authorized)
separation margin       +0.1500   no overlap whatsoever
synthetic authored ROC-AUC   1.0  (rank statistic over authored labels only)
```

Identical 100% / 0% results hold at every threshold from 0.15 to 0.25, so the
headline is not knife-edge threshold-sensitive — but it is not sensitive because
the benchmark contains no hard cases. A corpus with no overlap cannot distinguish
a good scorer from an adequate one. Only one risky family sits within 0.05 of the
threshold (`risky_amount_anomaly`, +0.0307); no benign family does. Reported as
RL-08.

The benign half is also narrower in output than in construction: five of its
seven families (`benign_low_value`, `benign_cold_start_merchant`,
`benign_established_merchant`, `benign_competitive_selection`,
`benign_settled_payment`) are built differently but all score 0.0000 with no
contributing factor, so the benign side exercises **three** distinct scoring
outcomes rather than seven. Each of the ten risky families has a distinct factor
signature. Reported as RL-09.

### What "10 iterations" measures

Deterministic repetition, not dataset diversity. Each iteration rebuilds its
scenario in a **fresh isolated in-memory database** and re-runs the same
construction; there is no randomisation and no seed strategy, and the harness
asserts every family produced an identical score across all ten
(`deterministic_across_iterations: true`). So:

> **170 assessments = 17 authored scenario families × 10 deterministic
> repetitions.** They are not 170 independent transactions. The repetitions
> measure repeatability and construction stability; they add no semantic
> coverage and do not widen the evidence base.

### Metric formulas, fixed before the numbers

```text
T = review_threshold = 0.25            flagged  <=>  score >= T   (inclusive)

risk_detection_rate = |{RISKY  : score >= T}| / |RISKY |  = 100/100
false_positive_rate = |{BENIGN : score >= T}| / |BENIGN|  =   0/70
false_negative_rate = |{RISKY  : score <  T}| / |RISKY |  =   0/100
```

`false_negative_rate == 1 − risk_detection_rate` by construction, computed from
the same subset. Rates are re-derived from the evaluation rows, never stored
constants. A rate over an empty denominator is `None` and renders `n/a`.

### ML: not added

`ML_ADDED: NO`. The deterministic baseline is complete, explainable, and its
exact contributions are checkable. Adding a model would require labels, and the
only labels available are the synthetic ones authored above — whose ground truth
is defined by exactly the conditions the features measure. A model trained on
them would learn the heuristic's own generative rule and report its own inputs
back as a discovery: leakage by construction, not by accident. Adding XGBoost or
an Isolation Forest to a corpus like this would produce a more impressive
dependency list and strictly less interpretability.

### Known limitations of the measurement (RL-01..RL-06)

Reported on every evaluation run, and kept SEPARATE from the Phase 6 security
limitations. A security limitation says an attacker could do something
undetected; a risk limitation says a number means less than it looks like.

```text
RL-01  no user identity in the domain, so no per-user behavioural baseline
RL-02  the score is a normalized risk index, not a fraud probability
RL-03  the evaluation corpus is synthetic and its labels are authored
RL-04  cross-mission merchant history is a bounded recent window (500 / 200)
RL-05  the engine is not invoked automatically by the mission path
RL-06  a recommendation is returned; no workflow consumes or enforces it
RL-07  no held-out evaluation set; the reported rates are development-set metrics
RL-08  the corpus is trivially separable (margin +0.1500, synthetic AUC 1.0)
RL-09  five of seven benign families produce an identical zero-factor result
```

Phase 7 itself changed none of KL-01 through KL-07. The later signed-approval
hardening narrows KL-04 to the explicitly limited demo-key model; external audit
anchoring, merchant authentication, and reconciliation remain unchanged.

## Protocol adapters (corrected)

Phase 8 treats integration as a boundary between external representation and
the existing kernel, never as an alternate route around it:

```text
external bytes / document
  -> sealed server-owned adapter registry
  -> family + exact protocol-version resolution
  -> protocol-specific translation
  -> canonical candidate + per-field provenance (still tainted/untrusted)
  -> existing capability / ingress / policy / binding / authorization path
  -> existing payment executor and PaymentProvider rail
```

ACP / AP2 / MCP / x402 / Razorpay are not interchangeable. The declared
families are:

* `CommerceAdapter`: external merchant/catalog/offer representation into
  candidate commerce data. It has no `MerchantContext` or trust field; the
  existing ingress receives transport identity separately and resolves trust
  from the server-owned merchant registry.
* `PaymentAuthorizationAdapter`: external authorization intention into
  `CandidateAuthorizationRequest`. The candidate shares no artifact-only field
  with PACTRA's `Authorization`; it cannot be consumed, and only the existing
  `issue_authorization` path can mint the server-held artifact.
* `ToolAdapter`: external invocation into a closed `CandidateOperation` set.
  The operation-to-capability mapping is server-owned and contains no
  privileged capability.
* `AgentCommunicationAdapter`: declared for classification, with no base class
  or implementation because no repository-grounded requirement justifies one.
* `PaymentRailAdapter`: the already-stable Phase 4 `PaymentProvider` protocol.
  Rails execute and therefore do not belong in the pure translation registry.

### Protocol support matrix

`services/adapters/support.py` is the one machine-readable source. The CLI
renders it as JSON, and tests hold both human tables, the translating registry,
and the existing rail registry to it.

| Protocol/system | Actual role | Adapter family | What is really implemented | Status |
|---|---|---|---|---|
| `Razorpay` | Payment provider / rail | `PaymentRailAdapter` | Existing Phase 4 test-mode Orders API adapter and webhook verification; Checkout and live-API validation remain absent | `PARTIAL` |
| `MCP` | Tool/context protocol | `ToolAdapter` | Thin JSON-RPC 2.0 `tools/call` request translation for three closed revisions and five non-privileged `pactra.*` tool names; no server or transport | `PARTIAL` |
| `AP2` | External payment authorization | `PaymentAuthorizationAdapter` | The generic family and candidate-only PACTRA reference adapter exist; no AP2 schema or adapter exists | `PLANNED` |
| `x402` | Not classified from repository evidence | `(unassigned)` | No code and no compatibility claim | `PLANNED` |
| `ACP` | Not classified from repository evidence | `(unassigned)` | No code and no compatibility claim | `PLANNED` |
| `pactra.commerce.v1` | PACTRA-native commerce format | `CommerceAdapter` | Strict catalog/offer translation into candidate merchant data, with claims, provenance, taint and unknown metadata preserved | `IMPLEMENTED` |
| `pactra.authorization-intent.v1` | PACTRA-native authorization-intent format | `PaymentAuthorizationAdapter` | Strict translation into a candidate request; no artifact issuance or external signature verification | `IMPLEMENTED` |

MCP is a partial request-shape adapter, not an MCP server. It implements no
transport, lifecycle/`initialize`, capability negotiation, `tools/list`,
response, resource, prompt, sampling or notification surface. Its closed
revision set is 2024-11-05, 2025-03-26 and 2025-06-18, matching the official
`tools/call` specifications. Request IDs are validated as JSON-RPC string or
integer IDs. Nested arguments and `_meta` are refused because this narrow
boundary cannot preserve them faithfully; accepting and discarding either
would make the translation claim broader than its output.

### Registry and authority boundary

The translating registry is populated from an explicit built-in tuple, then
sealed. There is no discovery/import-by-name path, no caller-supplied registry
parameter on `translate`, and no runtime registration, replacement,
deregistration or trust mutation. Resolution requires an adapter ID, expected
family and exact supported protocol version; no unknown value falls back to a
default.

The descriptor supplies adapter identity, never the payload or implementation.
The descriptor is frozen and capped at `AGENT_PROPOSAL` / `UNTRUSTED`; after an
implementation returns, the common translation boundary independently checks
family/payload pairing, every provenance authority, taint and trust value.

This also closes the confused-deputy path. A trusted registered implementation
does not lend authority to its input. `CandidateOperation` contains no
principal, capabilities or approval flag; a principal selected by trusted glue
is re-resolved from `capability_registry`, and the required capability comes
from the server-owned operation table. A caller claiming `payment-executor`
therefore does not acquire its identity, while `payment.execute` has no
canonical operation to translate into at all.

### Translation isolation

All translating entry points are synchronous and take no database session.
The adapter import graph cannot reach payment creation, authorization writes,
transaction binding, merchant transports, audit writes, risk evaluation or the
ORM. Tests additionally run every adapter against populated state and compare
row counts plus policy/authorization values before and after. Translation
creates and consumes no authorization, creates no payment intent or outbox/audit
row, mutates no policy, and calls no provider or merchant transport.

The 13 hostile adapter scenarios and 3 benign controls are reported as a Phase
8 expansion. The original Phase 6 benchmark is selected by a fixed 47-ID list,
not by categories, so later adapter controls cannot move its denominator.
Adapter-originated bindings use Phase 3 unchanged; amount, currency, merchant,
product and quantity mutations all recompute the existing digest and fail
consumption.

No migration and no dependency were required by Phase 8. No authenticated
protocol ingress or verifier for external authorization references exists. ACP,
AP2 and x402 stay planned. Razorpay
stays partial/test-mode with every Phase 4 limitation unchanged.

## Authority principle (unchanged from v1, restated)

Lower layers can never override higher layers. Hard limits, authorization, and
policy configuration are authoritative; agent proposals and merchant data are
not.
