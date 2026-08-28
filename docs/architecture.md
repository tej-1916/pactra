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
- verified authorizations (nonce + transaction digest)
- deterministic policy decisions
- provider webhooks with a verified signature

PRIVILEGED (never reachable from untrusted data or the LLM directly)
- payment executor
- authorization / signing material
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

The top level is named `USER_POLICY`, not "user-signed policy": it is
authoritative because it is established server-side at the trusted API boundary,
**not** because it carries a cryptographic signature. No signing exists yet. A
`VERIFIED_USER_POLICY` level may be introduced if real signing is ever
implemented. Phase 3 did NOT implement it — it delivered transaction binding and
server-issued authorization artifacts instead — so the level is still absent and
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
consumed_at, bound_{merchant_id, product_id, quantity, amount_inr, currency}
```

```text
PENDING  --activate-->  ACTIVE  --consume-->  CONSUMED   (terminal)
   |                       |
   +-----------------------+--expire--> EXPIRED          (terminal)
   +-----------------------+--revoke--> REVOKED          (terminal)
```

**This is a server-issued authorization artifact, NOT a cryptographically
signed one.** Phase 3 implements no signing and no signature verification. The
artifact is authoritative because it is minted, held, and consumed entirely
inside the trusted server boundary — never because it carries a verifiable user
signature. The 256-bit `nonce` is server-held entropy that makes each
authorization unique and its digest unpredictable; it is not a key, not a token
issued to a client, and is never returned by the API or written to an audit
payload. Cryptographic user signatures remain future work, and the
`VERIFIED_USER_POLICY` authority level anticipated in Phase 2 is therefore still
not introduced.

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
and never the nonce.

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

`FAILED_RETRYABLE` is reachable from `PROVIDER_PENDING` through exactly one
route: a provider that positively reports holding no payment for the key. No
elapsed timer and no attempt count promotes an uncertain payment back to
retryable, because neither is evidence about whether money moved.

### Never a blind retry

Before every create attempt the executor looks the durable idempotency key up at
the provider. A found payment is validated and adopted without a second create;
a positively-empty answer makes creation safe; a *failed* lookup keeps the
intent uncertain and never falls through to create. This does not assume the
provider deduplicates creates — a deliberately non-idempotent test provider is
used so provider-side idempotency cannot mask a PACTRA blind-retry bug.

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

Claiming and handling run in SEPARATE transactions:

```text
TX 1  claim event, persist IN_PROGRESS lease + attempt count   COMMIT
TX 2  provider I/O, persist local result, acknowledge event    COMMIT
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

### What replay cannot reconstruct

`ReplayedPayment.last_reason_code` is `None` after a terminal provider failure.
`apply_payment_transition` writes `reason_code` to the `payment_intents` COLUMN
but not into the audit payload, so `PROVIDER_TERMINAL_FAILURE` is not in the
ledger. Replay leaves the field unknown instead of inferring it from the event
type — inferring would be fabricating a value the events do not contain. The gap
is asserted by a test so it cannot drift unnoticed. Reason codes that ARE written
into payloads (the uncertainty and reconciliation paths) reconstruct normally.

## Adversarial validation

An Attack Lab runs named adversarial scenarios and records structured results
(`attack_name, attack_input, expected_defense, observed_result, blocked/
succeeded, reason_code, latency, affected_component`). An evaluation harness
generates many normal and adversarial scenarios and reports metrics from real
runs only.

## Protocol adapters (corrected)

ACP / AP2 / MCP / x402 are not interchangeable; they sit at different layers.
PACTRA normalizes to an internal transaction model and exposes distinct adapter
families — `CommerceAdapter`, `PaymentAuthorizationAdapter`, `ToolAdapter`,
`PaymentRailAdapter`. Only implemented protocols are claimed; partial ones are
labeled `experimental` / `partial` / `simulated`.

## Authority principle (unchanged from v1, restated)

Lower layers can never override higher layers. Hard limits, authorization, and
policy configuration are authoritative; agent proposals and merchant data are
not.
