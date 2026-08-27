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

## Payment reliability (transactional outbox)

Side effects are made reliable without unnecessary distributed complexity:

```text
DB TRANSACTION { PaymentIntent, AuditEvent, OutboxEvent } → COMMIT
      → Worker → Payment Provider
```

Combined with an idempotency key (`payment_intents.idempotency_key UNIQUE`) and
`provider_payment_id UNIQUE`, retries and crashes yield at most one logical
payment. Webhooks are signature-verified; duplicate and delayed webhooks are
handled idempotently; reconciliation closes the loop.

## Event history + replay

Important transitions are stored as append-only events, enabling deterministic
`REPLAY MISSION` — reconstructing mission state purely from history.

## Tamper-evident audit ledger

```text
event_id, mission_id, sequence, event_type, actor, payload,
previous_hash, event_hash, created_at
```

`event_hash = SHA256(canonical_event_body + previous_hash)`. A verification
endpoint recomputes the chain and returns `{ "valid": true, "events_checked": N }`;
any modification yields `AUDIT_INTEGRITY_FAILURE`. Tamper-evident, not a
blockchain.

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
