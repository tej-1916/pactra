/**
 * Plain-language descriptions that sit BESIDE a reason code, never instead of it.
 *
 * The code is the fact. `AUTHORIZATION_REPLAY_DETECTED` is what the kernel
 * produced, what the audit ledger records, and what an engineer greps for; a
 * component that rendered "Something went wrong" in its place would have
 * destroyed the only durable handle on the event. So every surface prints the
 * code verbatim and may add one of these sentences after it.
 *
 * A code with no entry here renders as itself. That is the correct fallback: an
 * unexplained real code is strictly better than an invented explanation, and it
 * makes a missing description visible instead of papering over it.
 */

export const REASON_CODE_DESCRIPTIONS: Readonly<Record<string, string>> = {
  // ---- policy ------------------------------------------------------------ //
  NO_VALID_OFFERS: "No offer survived validation, so there was nothing to decide about.",
  HARD_LIMIT_EXCEEDED: "The amount exceeded the absolute ceiling. No approval can raise it.",
  BLOCKED_MERCHANT: "The merchant is on the user's block list.",
  MERCHANT_NOT_ALLOWED: "The merchant is not on the user's allow list.",
  RATING_BELOW_MIN: "The offer's rating is below the minimum the user set.",
  CURRENCY_NOT_ALLOWED: "The offer is priced in a currency the user's policy does not permit.",
  OUT_OF_STOCK: "The merchant reported the item as unavailable.",
  MERCHANT_TRUST_TOO_LOW: "Registry-held merchant trust is below the user's threshold.",
  MERCHANT_IDENTITY_MISMATCH:
    "The payload claimed one merchant identity while the transport authenticated another.",
  SOFT_BUDGET_EXCEEDED: "Above the approval threshold but within the ceiling: a human must approve.",
  WITHIN_LIMITS: "The request satisfied every deterministic policy rule.",

  // ---- kernel ------------------------------------------------------------ //
  AUTHORITY_ESCALATION:
    "Lower-authority data attempted to modify state only higher authority may write.",
  CAPABILITY_DENIED: "The calling principal does not hold the capability this operation requires.",
  INVARIANT_VIOLATION: "A kernel invariant that must hold unconditionally did not hold.",

  // ---- binding / authorization ------------------------------------------- //
  TRANSACTION_BINDING_FAILURE:
    "The presented transaction does not match the one the authorization was bound to.",
  AUTHORIZATION_REPLAY_DETECTED:
    "The authorization was already consumed and cannot authorize another payment.",
  AUTHORIZATION_EXPIRED: "The approval window closed before the authorization was used.",
  AUTHORIZATION_NOT_ACTIVE: "The authorization is not in the one state from which it can be spent.",
  AUTHORIZATION_NOT_FOUND: "No authorization artifact exists for this transaction.",
  NO_AUTHORIZATION: "This mission holds no authorization to spend.",
  MISSION_NOT_AUTHORIZED: "The mission has not reached an authorized state.",
  MISSION_NOT_AWAITING_APPROVAL: "The mission is not at the point where approval applies.",

  // ---- payment ----------------------------------------------------------- //
  IDEMPOTENCY_CONFLICT:
    "The same idempotency key was presented for a materially different transaction.",
  IDEMPOTENCY_KEY_INVALID: "The idempotency key was missing or longer than the accepted bound.",
  PAYMENT_PROVIDER_TIMEOUT:
    "The provider call timed out. Whether a payment was created is unknown until reconciliation.",
  PROVIDER_TRANSIENT_FAILURE: "The provider failed in a way that may succeed on retry.",
  PROVIDER_TERMINAL_FAILURE: "The provider failed in a way that will not succeed on retry.",
  PROVIDER_RESPONSE_MISMATCH:
    "The provider's answer described a different transaction than the one requested.",
  PROVIDER_PAYMENT_NOT_FOUND: "The provider reports holding no payment for this idempotency key.",
  ILLEGAL_PAYMENT_TRANSITION: "The payment state machine does not permit that state change.",
  PAYMENT_INTENT_NOT_FOUND: "No payment intent exists for this mission.",
  UNKNOWN_PAYMENT_PROVIDER: "No provider is registered under that name.",
  PAYMENT_PROVIDER_UNAVAILABLE: "The named provider is not available in this environment.",

  // ---- webhooks ---------------------------------------------------------- //
  WEBHOOK_SIGNATURE_INVALID:
    "The MAC over the raw body did not verify, so the payload was never read as state.",
  WEBHOOK_DUPLICATE: "A delivery already seen. Accepted so the provider stops retrying; applied to nothing.",
  WEBHOOK_UNKNOWN_PAYMENT: "The webhook named a payment this system does not hold.",
  WEBHOOK_BODY_TOO_LARGE: "The body exceeded the cap and was refused before the MAC was computed.",

  // ---- audit / replay ---------------------------------------------------- //
  AUDIT_VALID: "Every event hashes to its stored hash and links to the one before it.",
  AUDIT_SEQUENCE_GAP: "Sequences are not the contiguous run they must be: an event was removed, injected or renumbered.",
  AUDIT_PREVIOUS_HASH_MISMATCH: "An event does not link to the hash of the event before it.",
  AUDIT_EVENT_HASH_MISMATCH: "An event's contents no longer hash to its stored hash — the signature of an edited payload.",
  AUDIT_GENESIS_INVALID: "The first event does not carry the genesis previous-hash.",
  AUDIT_EVENT_MALFORMED: "A row is not shaped like an audit event at all, so hashing it would prove nothing.",
  REPLAY_OK: "State was reconstructed from the event history alone.",
  REPLAY_AUDIT_INVALID:
    "The chain did not verify, so replay was refused before reducing. A projection from tampered history is a confident-looking lie.",
  REPLAY_UNSUPPORTED_EVENT_TYPE: "An event type this build does not know. Replay fails closed rather than skipping it.",
  REPLAY_MALFORMED_EVENT: "A known event type whose payload cannot be interpreted.",

  // ---- adapters ---------------------------------------------------------- //
  CLAIMED_IDENTITY_NOT_AUTHENTICATED:
    "No protocol channel is authenticated, so the caller's identity is a claim and is capped at proposal authority.",
  EXTERNAL_AUTHORIZATION_REFERENCE_NOT_VERIFIED:
    "An external authorization reference is carried as an opaque string. PACTRA holds no verifier for one.",
  UNKNOWN_FIELDS_KEPT_AS_UNTRUSTED_METADATA:
    "Unrecognized fields were retained as untrusted metadata rather than silently dropped or trusted.",
  MERCHANT_TRUST_NOT_ASSIGNED_BY_ADAPTER:
    "An adapter assigns no trust. Merchant trust comes only from the server-owned registry.",
};

export function describeReasonCode(code: string | null | undefined): string | null {
  if (!code) return null;
  return REASON_CODE_DESCRIPTIONS[code] ?? null;
}
