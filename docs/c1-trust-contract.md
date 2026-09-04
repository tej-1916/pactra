# C1 trust contract and Decision Trace freeze

**PACTRA — Deterministic Transaction Verification for Agentic Commerce**

Status: frozen at C1. Changes to the schemas, enum values, stage mappings,
ordering, or endpoint documented here are contract-breaking and require
explicit approval.

PACTRA remains an `ADMIT -> BIND -> EXECUTE` system. The model may select; the
model may not mint authority. The AI is never the security boundary. **LLM
output is never authorization; merchant content is never system authority.**

There are exactly three stages, and audit/verification/replay is **not** a
fourth. Audit and replay are downstream *evidence*: they record and reconstruct
what the three stages did, grant no authority, and repair no state. The `stage`
enum below is closed at `ADMIT | BIND | EXECUTE` for that reason.

The consolidated verification record for the release — including the real
Razorpay TEST-mode evidence and the audit/replay results measured over it — is
in [`evidence.md`](evidence.md).

## Trusted computing base

PACTRA's guarantees assume the integrity and correct operation of this trusted
computing base (TCB):

- the PACTRA verification, deterministic policy, capability, binding,
  authorization, outbox, executor, audit-verification, and trace-projection
  code;
- the database's durable state, constraints, transactions, and locks;
- the server clock at authorization issuance, activation, and atomic
  consumption;
- the configured demo approver public key and key ID;
- the server-owned merchant adapter registration, merchant registry,
  capability registry, and provider registry;
- `PaymentExecutor`, its durable PaymentIntent/outbox state, and the worker;
- the payment-provider adapter boundary, its configured credentials, and its
  faithful validation/translation of provider responses.

Explicitly untrusted are LLM/model output, buyer-agent proposals, protocol
payloads, browser text, merchant payloads and descriptive content, merchant
self-asserted identity, provider responses until validated, webhooks until
their raw-body signature verifies, and the advisory risk result.

PACTRA does **not** claim protection against compromise of the entire PACTRA
TCB. Database, clock, verifier, executor, registry, or provider-adapter
compromise can invalidate assumptions on which these guarantees depend.

## Named non-goal: semantic intent infidelity

**PACTRA does not prove that the AI perfectly understood the user's semantic
intent.** PACTRA guarantees bounded authority and integrity properties, not
semantic fidelity between natural language and structured intent.

Current mitigations are hard policy limits, typed candidate intent, human
approval when deterministic policy requires it, exact transaction binding,
trusted presentation of authoritative transaction fields, and invalidation or
refusal when security-relevant transaction data changes.

## Taint and declassification

The current flow and classifications are:

1. Merchant description and payload: untrusted and tainted. Free-form
   `description` is dropped at ingress. Structured merchant product, price,
   currency, rating, stock, and offer time remain tainted.
2. Agent/model: no LLM exists in C1. The current deterministic ranker selects a
   valid offer. The frozen selector boundary is `OfferCandidate`, which accepts
   only `offer_id` and forbids extra fields.
3. Selected offer: the server captures the selected offer ID and the
   server-computed selection-time `offer_version`.
4. BIND declassification: the server reloads the selected `offers` row by
   mission and ID under a row lock, recomputes the content fingerprint, and
   requires both the stored version and bind-time version to match the
   selection-time version.
5. Bound transaction: merchant identity, product ID, unit amount, currency, and
   version come from the reloaded structured row; quantity and policy result
   come from trusted mission/policy state; the policy-adjudicated total must
   equal unit amount times quantity. The kernel generates expiry and nonce.

No path accepts `LLM output.amount`, `LLM output.currency`, a caller-selected
merchant/payee, policy limit, approval scheme, key, algorithm, capability, or
payment destination as transaction authority.

Structured offer records are not cryptographically authenticated by merchants.
Their merchant-derived content remains an explicit trust assumption: PACTRA
trusts its adapter registration, ingress classification, database integrity,
and deterministic policy/declassification checks. C1 does not fake merchant
authentication.

### Offer drift invariant

`SELECTED OFFER VERSION MUST MATCH BIND-TIME AUTHORITATIVE OFFER VERSION.`

The stable refusal is `BIND_REFUSED_OFFER_CHANGED`. It is ONE reason code over
several dotted invariant IDs, because every way the authoritative row can stop
being the row the selector chose is the same fact to a caller — no authorization
exists:

| Invariant ID | Refused when |
| --- | --- |
| `binding.selected_offer_version_matches_authoritative_record` | the record is absent, its content drifted, or its stored version is stale |
| `binding.offer_is_valid` | ranking rejected the record between selection and bind |

Callers branch on `reason_code`; `invariant_id` names the precise rule for
operators and audit without widening that contract. Amount, product/version,
and authenticated-merchant changes are covered.

`offered_at` is normalized to UTC at ingress, before the fingerprint is computed
and before the row is written. The same instant expressed at a different UTC
offset is therefore one offer version, not two, and an unchanged offer is never
refused as drift for a timezone reason alone. A naive timestamp is deliberately
NOT normalized: it names no instant, so it stays naive and the canonical encoder
fails it closed rather than inventing an offset for it.

#### Refusal is durable and is an answer, not a crash

`POST /api/v1/missions` answers a bind refusal with **HTTP 409** and the body:

```json
{"detail": {"reason_code": "BIND_REFUSED_OFFER_CHANGED", "invariant_id": "..."}}
```

The mission and its bind-refused `SECURITY_VIOLATION` are COMMITTED before that
409 is raised. Evidence of a refusal must outlive the error response; rolling it
back would erase the only record that the refusal happened and leave replay
showing a mission that stopped for no stated reason. Committing is safe because
the refusal is fail-closed: the request performed no privileged mutation, so
what becomes durable is the mission up to `POLICY_CHECKED` plus its audit trail
— no authorization, no payment intent, no outbox row.

## Transaction and routing binding

Binding version remains `pactra-txn-bind-v1`; canonicalization is unchanged.
The digest covers exactly:

```text
merchant_id, product_id, quantity, amount_inr, currency,
policy_version, offer_version, expires_at, nonce
```

Routing verdict: **ALREADY_SATISFIED for current demo scope**.

- `merchant_id` is the only transaction-level recipient semantic and is in the
  digest. It comes from server-side adapter registration, not the merchant's
  claimed identity.
- The Razorpay test adapter creates an order on the account fixed by configured
  server credentials. `PaymentRequest` has no payee, connected-account,
  settlement-account, transfer-account, or destination field.
- The provider name selects a server-registered rail, not a transaction-level
  payee. Production exposes exactly one provider name; the name is also covered
  by the idempotent payment-request fingerprint. It is not a variable
  settlement destination in the current contract.

Adding any mutable destination/account/payee field, or making provider choice
select a different settlement recipient, is a binding migration: stop with
`P0_BINDING_GAP`, define a new binding version, analyze compatibility, and do
not silently change v1.

## Key custody

The production/API process has only the configured pre-enrolled Ed25519 public
key and key ID. The approval request can supply that key ID and a signature,
but cannot supply a public key, algorithm, message, transaction, or trust-root
mutation. The verifier compares the ID to server configuration and always uses
Ed25519 over server-reconstructed canonical bytes.

The demo private key is generated/stored by `scripts/pactra_demo_signer.py` at
a caller-selected `0600` path outside the repository. It is not stored in the
database, API configuration, public models, browser bundle, audit payloads, or
Decision Trace. Tests and the authored Attack Lab generate ephemeral private
keys in their isolated harness processes; those are not backend runtime keys
and are never reported.

There is no production enrollment, rotation, recovery, revocation registry,
WebAuthn, or passkey implementation.

## Authorization validity moment

Authorization validity is required when `ACTIVE` is atomically consumed into a
durable PaymentIntent and transactional outbox. The same database unit checks
status, digest, and `expires_at > consumption_time`; creates the intent; marks
the authorization `CONSUMED`; and queues provider work. The
authorization-consumption transaction does not span provider I/O: it commits
before asynchronous provider handling. The worker uses a separate claim/work
split: the claim transaction commits before provider handling, while the worker
handler transaction spans provider I/O and holds the PaymentIntent row lock for
that handler transaction.

After successful consumption, the PaymentIntent is the durable authorized work.
A later worker does not retroactively invalidate it merely because the original
approval expiry elapsed in the queue. Before provider I/O the worker still
reloads the consumed authorization, reconstructs the bound transaction,
checks binding version/digest/policy origin, re-verifies durable USER_ED25519
proof where applicable, and compares the authorization, intent, and outbox
linkage. Corruption still fails closed.

## Approval-display trust contract

The future approval UI must render machine-authoritative values separately from
merchant-supplied strings.

Authoritative for the exact proposed payment:

- `AuthorizationOut.bound_merchant_id` / challenge `transaction.merchant`:
  server-registered merchant ID (subject to the non-cryptographic merchant
  authentication limitation);
- bound/challenge amount, currency, quantity, expiry, policy/offer/binding
  versions, approval scheme, signing key ID, and transaction digest;
- policy outcome and reason codes from deterministic policy state/audit events;
- authorization and PaymentIntent state from durable rows or a trusted replay.

Tainted or merchant-supplied display data:

- offer `title`, `product_id`, product descriptions, merchant payload price and
  currency before BIND, raw query, and all browser/merchant free text;
- `merchant_name` is server-registry display data, not cryptographic merchant
  identity; it must not replace the authoritative merchant ID;
- the bound `product_id` is integrity-protected as the exact selected value but
  remains merchant-originated descriptive identity.

Presentation requirements for the frontend owner:

- render bound machine amount and currency as TOTAL; never derive them from a
  title, description, or merchant string;
- render authoritative merchant ID/payee semantics separately from display
  name and product text;
- never allow merchant text to masquerade as total, payee, policy result,
  approval status, digest, or expiry;
- label merchant-originated strings as display data and apply bidi/control and
  confusable handling in the frontend phase;
- `POLICY_AUTO` means deterministic policy activation, never human approval;
  `USER_ED25519` means a verified local cryptographic approval proof.

## Decision Trace API freeze

No new endpoint exists. The trace is the `decision_trace` array on the existing
read-only, audit-verified endpoint:

```text
GET /api/v1/missions/{mission_id}/replay
```

If audit verification or replay fails, `trusted` is false, `state` is null, and
`decision_trace` is `[]`. A trace is returned only after the hash chain verifies
and every enforcement event can be interpreted. The projection never writes or
repairs state.

### Exact entry schema

Every entry has all fields below. Nullable fields are present as JSON `null`;
they are not omitted.

| Field | Type | Null semantics | Source |
|---|---|---|---|
| `stage` | enum | never null | exhaustive event-to-stage map |
| `event_type` | existing `EventType` enum | never null | audit row |
| `verdict` | enum | never null | deterministic event/outcome map |
| `reason_codes` | array of strings | never null; `[]` means none recorded | allow-listed `reason_code`/`reason_codes` payload fields |
| `invariant_id` | string or null | null when the source event recorded none; never inferred | allow-listed payload field |
| `approval_scheme` | `POLICY_AUTO`, `USER_ED25519`, `LEGACY_SERVER`, or null | null for non-authorization events | allow-listed payload field |
| `policy_outcome` | `ALLOW`, `REQUIRE_APPROVAL`, `DENY`, or null | null except policy decisions | policy event payload |
| `payment_state` | existing `PaymentIntentState` enum or null | null when source event records no state | allow-listed payload field |
| `advisory` | boolean | never null; true only for `RISK_ASSESSED` | event type |
| `next_action` | enum | never null | deterministic event/state map |
| `evidence` | object | never null | verified audit row reference |
| `recorded_at` | UTC date-time | never null | audit row `created_at` |

`evidence` has exactly `event_id` (UUID), `sequence` (integer >= 0), and
`actor` (string).

Enum values are frozen:

```text
stage:
  ADMIT | BIND | EXECUTE

verdict:
  ACCEPTED | REFUSED | PENDING | SUCCEEDED | FAILED | IGNORED | ADVISORY

next_action:
  CONTINUE_ADMIT | CONTINUE_BIND | AWAIT_USER_SIGNATURE |
  CREATE_PAYMENT_INTENT | DISPATCH_PAYMENT | AWAIT_PROVIDER |
  RECONCILE_PAYMENT | RETRY_PAYMENT | NONE

approval_scheme:
  POLICY_AUTO | USER_ED25519 | LEGACY_SERVER

policy_outcome:
  ALLOW | REQUIRE_APPROVAL | DENY

payment_state:
  CREATED | QUEUED | PROCESSING | PROVIDER_PENDING | SUCCEEDED |
  FAILED_RETRYABLE | FAILED_TERMINAL | CANCELLED

event_type:
  MISSION_CREATED | INTENT_PARSED | DISCOVERY_STARTED | OFFERS_RECEIVED |
  OFFERS_NORMALIZED | OFFERS_RANKED | POLICY_DECISION |
  APPROVAL_REQUESTED | MISSION_DENIED | SECURITY_VIOLATION |
  AUTHORIZATION_CREATED | AUTHORIZATION_ACTIVATED |
  AUTHORIZATION_CONSUMED | AUTHORIZATION_EXPIRED |
  AUTHORIZATION_REVOKED | AUTHORIZATION_REPLAY_DETECTED |
  TRANSACTION_BINDING_FAILURE | PAYMENT_INTENT_CREATED | PAYMENT_QUEUED |
  PAYMENT_ATTEMPTED | PAYMENT_PROVIDER_TIMEOUT |
  PAYMENT_PROVIDER_UNCERTAIN | PAYMENT_RETRY_SCHEDULED |
  PAYMENT_RECONCILED | PAYMENT_SUCCEEDED | PAYMENT_FAILED |
  PAYMENT_INTENT_REUSED | IDEMPOTENCY_CONFLICT |
  OUTBOX_EVENT_DEAD_LETTERED | WEBHOOK_VERIFIED | WEBHOOK_REJECTED |
  DUPLICATE_WEBHOOK_IGNORED | WEBHOOK_OUT_OF_ORDER_IGNORED | RISK_ASSESSED
```

Entries are ordered ascending by `(evidence.sequence, evidence.event_id)`.
Sequence is unique per mission in storage, so the event ID is only a total-order
tie-break for diagnostic inputs. Repeated reads of unchanged history return the
same trace.

The trace is an allow-listed action/security record, not model chain-of-thought.
It exposes no raw event payload, hidden reasoning, signature, nonce, private
key, approval-message bytes, provider secret, merchant description, or
sensitive raw provider payload.

An exact payload captured from the real FastAPI + SQLite runtime after creating
an ALLOW mission and its durable queued PaymentIntent is frozen in
[`c1-decision-trace-example.json`](c1-decision-trace-example.json). It is runtime
output, not hand-authored mock data.

### Event stages

ADMIT covers mission/intent parsing, discovery, ingress/normalization, ranking,
policy, admission security refusals, and advisory risk evidence. BIND covers
approval requests and authorization issuance, activation, consumption,
expiry/revocation/replay/binding refusals. EXECUTE covers durable PaymentIntent,
outbox/provider dispatch, reconciliation, result, and webhook events. A
bind-refused `SECURITY_VIOLATION` carries `bind_refused: true` and is classified
as BIND; other security violations remain ADMIT.

### Payment `reason_code`: presence, not truthiness

A payment transition event states the reason as of that transition, and the key
is written even when the reason is null. Replay therefore reads PRESENCE:

| Payload | Replay does | Because |
| --- | --- | --- |
| `"reason_code": "PROVIDER_TRANSIENT_FAILURE"` | sets that reason | the transition recorded one |
| `"reason_code": null` | CLEARS the reason | the transition cleared it on the intent row |
| key absent | keeps the previous value | the event says nothing about the reason |

Without the explicit null, "no reason any more" would be indistinguishable from
"this event is silent about the reason", and a payment that failed retryably and
then succeeded would replay as still carrying the failure while the live intent
row showed none — a projection disagreeing with the state it reconstructs.

Pre-C1 payloads omitted the key rather than recording a clear. They keep
replaying under the absent-key rule, so historical missions are unaffected.

## Risk decision: Option A

Risk remains advisory only. It never grants authority, changes policy, issues
or consumes authorization, executes payment, or represents fraud probability.
Its numeric value remains a normalized deterministic heuristic index, not ML.
C1 adds no risk-engine feature work or primary navigation. A real
`RISK_ASSESSED` audit event may appear in Decision Trace with
`verdict=ADVISORY`, `advisory=true`, and `next_action=NONE`.

## Unsupported threat classes and limitations

- semantic intent infidelity;
- compromise of the full PACTRA TCB or its trusted registries/configuration;
- cryptographic merchant authentication and authenticated structured offers;
- deletion of the whole audit chain or an unanchored tail by a database
  attacker: the ledger is a per-mission hash chain and is **tamper-evident, not
  immutable**. There is no immutable storage, no blockchain, no Merkle tree, and
  no independent external anchor;
- production user identity, identity proofing, and account recovery;
- production signing-key enrollment, rotation, recovery, and revocation;
- WebAuthn/passkeys;
- independent red-team validation: the Attack Lab is an **authored adversarial
  regression harness**, not certification. It proves its own scenarios are
  refused, reproducibly, and says nothing about attacks nobody wrote;
- deployed production multi-node or multi-region guarantees beyond the tested
  PostgreSQL locking/outbox primitives;
- provider availability, settlement correctness, account security,
  idempotency, reconciliation truth, disputes, refunds, and other guarantees
  outside PACTRA's provider-adapter boundary;
- real-money Razorpay execution: the current adapter is test-mode-only and
  partial. A real Razorpay TEST Order was created; **paid, captured, settled,
  customer Checkout completion, and provider webhook delivery were not**;
- protocol coverage beyond what the machine-readable support matrix declares:
  MCP is `PARTIAL` (request-shape translation only, no server or transport), and
  AP2, x402 and ACP are `PLANNED` with no code and no compatibility claim.
