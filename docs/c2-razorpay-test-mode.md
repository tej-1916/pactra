# C2 Razorpay test-mode payment path

PACTRA uses Razorpay **test mode only**. A key whose id does not begin with
`rzp_test_` is refused before a provider object can be constructed. Placeholder
or missing key, API secret, and webhook secret values also fail closed.

## Honest execution boundary

The automated backend step is:

1. consume an already-issued PACTRA authorization atomically with a durable
   PaymentIntent and outbox row;
2. create a Razorpay Order using the Orders API;
3. persist the real `order_...` id, provider receipt, status, and attempts;
4. reconcile the Order and process verified webhooks;
5. persist the real `pay_...` id before recording provider success.

The customer step is separate: the public test key id and Order id are inputs
to legitimate Razorpay Checkout, where the customer chooses and operates a
payment instrument. PACTRA does not collect card details server-side and does
not equate Checkout interaction with PACTRA authorization.

## Provider state mapping

| Razorpay evidence | PACTRA state |
|---|---|
| Order `created` | `PROVIDER_PENDING` |
| Order `attempted` | `PROVIDER_PENDING` |
| `payment.authorized` webhook | `PROVIDER_PENDING` |
| `payment.failed` webhook | `PROVIDER_PENDING` with `PROVIDER_PAYMENT_ATTEMPT_FAILED`; the same Order may be retried in Checkout |
| Order `paid` plus exactly one matching captured Payment | `SUCCEEDED` |
| `payment.captured` or `order.paid` with signed, internally consistent captured-payment evidence | `SUCCEEDED` |
| definitive create 4xx | `FAILED_TERMINAL` |
| create 429 after the fence is durable | `PROVIDER_PENDING`; search/reconcile only |
| create transport timeout, malformed 2xx, duplicate-receipt ambiguity, or 5xx | `PROVIDER_PENDING` and reconciliation |

PACTRA never derives success from local Order creation. A successful state
requires captured provider evidence.

## Lost responses and idempotency

PACTRA idempotency keys can be 200 characters, while Razorpay receipts are at
most 40. The provider sends a deterministic receipt consisting of `pactra_`
and 132 bits of the key's SHA-256 digest. The original idempotency key is not
sent to Razorpay. Before every create, and after any ambiguous create result,
PACTRA searches Orders by this receipt. An existing Order is adopted; a second
logical PaymentIntent is never created. A lookup failure is not treated as
not-found. Once any provider Order id has been durably linked, even a later
not-found response cannot license a replacement Order; the intent remains
uncertain until reconciliation succeeds or is dead-lettered for review.

Real Razorpay TEST API evidence accepted two consecutive Order creates with the
same amount, currency, receipt, and notes. PACTRA therefore does not claim that
Razorpay enforces receipt uniqueness and does not depend on a dashboard setting.

The guarantee is enforced locally in two layers:

- `UNIQUE(payment_intents.idempotency_key)` permits one logical PACTRA payment;
- `payment_intents.provider_create_fenced_at` permanently consumes permission
  to make the initial Razorpay create before the POST can occur.

The fence is deliberately conservative. It proves only that PACTRA consumed
create permission. It does **not** prove that a POST was dispatched or reached
Razorpay. The safe dispatch sequence is:

1. re-verify the stored USER_ED25519 proof and full transaction binding;
2. atomically acquire `provider_create_fenced_at` while the intent remains
   `QUEUED`, then commit it;
3. only the fence winner re-verifies and searches every relevant Razorpay
   Orders page for the exact deterministic receipt;
4. adopt one exact match, persist/refuse multiple matches, or continue only for zero;
5. for zero matches, re-verify once more immediately before the sole permitted
   Razorpay Order create.

After the fence exists, every automatic path is search/reconciliation-only. An
empty search remains `PROVIDER_PENDING`, never clears the fence, and never
authorizes another POST. This covers both indistinguishable crash outcomes:
the worker may have died before POST, or Razorpay may hold an Order that is not
currently visible in receipt search. The first case may require operator
recovery; PACTRA does not trade duplicate-payment safety for availability.

`provider_ambiguity_observed_at` separately records the first durable observation
of multiple exact Orders. It is monotonic: later empty or single-result searches
and individual webhooks cannot erase it or automatically claim a clean payment.
Operator review is required because weaker later evidence cannot prove the
previously observed additional Order is harmless.

## Exact timeout semantics

Every Razorpay HTTP request has the following defaults, configurable only via
environment/settings:

| Phase | Default bound |
|---|---:|
| connect | 3 seconds |
| read | 7 seconds |
| write | 5 seconds |
| connection-pool acquisition | 2 seconds |
| overall wall clock | 10 seconds |

The overall bound wraps injected clients too, so a stalled dependency cannot
hold the current PaymentIntent transaction indefinitely. A create timeout is
ambiguous: the intent becomes `PROVIDER_PENDING`, reason
`PAYMENT_PROVIDER_TIMEOUT`, and a reconciliation outbox event is committed.
Lookup timeouts leave the payment uncertain and reschedule reconciliation. An
empty post-fence lookup is handled the same way: it cannot authorize a new Order.

## Webhooks

The route verifies `X-Razorpay-Signature` as HMAC-SHA256 over the exact raw
body. It uses `X-Razorpay-Event-Id` as Razorpay's delivery deduplication key and
persists the accepted event under a database uniqueness constraint. Supported
events are `payment.authorized`, `payment.captured`, `payment.failed`, and
`order.paid`. Signed but malformed or unsupported events are rejected. Logs
contain only provider name and stable rejection reason: never the body,
signature, event id, API secret, or webhook secret.

## Configuration

Required values are `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and
`RAZORPAY_WEBHOOK_SECRET`. There is no receipt-uniqueness acknowledgement flag.
Secrets use redacted settings types and are never returned by APIs or written to
audit payloads. The test key id is public and is returned only for Razorpay test
PaymentIntents because Checkout legitimately requires it.
