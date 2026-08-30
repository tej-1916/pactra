import { Landmark } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { NotProvided } from "@/components/ui/States";
import { PaymentStateBadge } from "@/components/ui/StatusBadges";
import { inr, timestamp } from "@/lib/format";
import { idempotencyFingerprint } from "@/lib/redaction";
import { describeReasonCode } from "@/lib/reason-codes";
import { PAYMENT_STATE_MEANING } from "@/lib/semantics";
import type { PaymentIntent } from "@/lib/types/pactra";

/**
 * The READ model for a PaymentIntent. C5a is read-only by construction.
 *
 * This component has no submit, no retry and no provider handoff, and it takes
 * no callback that could grow one — the C2 mutations are not implemented yet
 * and a slot that merely looked ready for them would be the fastest route to a
 * demo that appears to move money.
 *
 * SLOTS FOR FIELDS THAT DO NOT EXIST YET. `PaymentIntentOut` at the C1 baseline
 * carries no provider order ID, no reconciliation state and no updated-at
 * timestamp. Those rows are rendered as NOT YET PROVIDED rather than omitted,
 * because the shape of the eventual record is worth showing while a plausible
 * value for it is worth nothing. Nothing here is inferred and nothing is
 * filled in.
 */
export function PaymentReadModel({ intent }: { intent: PaymentIntent }) {
  const meaning = PAYMENT_STATE_MEANING[intent.state];

  return (
    <div data-testid="payment-read-model" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <PaymentStateBadge state={intent.state} />
        <Badge tone="neutral" variant="outline" icon={<Landmark aria-hidden className="size-3.5" />}>
          READ-ONLY
        </Badge>
        {meaning ? (
          <p className="text-[11.5px] leading-snug text-[color:var(--color-ink-3)]">{meaning}</p>
        ) : null}
      </div>

      <KeyValueGrid columns={3}>
        <KeyValue
          label="PACTRA PaymentIntent ID"
          hint="PACTRA's own durable identifier. Not a provider identifier."
        >
          <span className="num">{intent.payment_intent_id}</span>
        </KeyValue>

        <KeyValue label="State" hint="From the durable PaymentIntent row.">
          <span className="num">{intent.state}</span>
        </KeyValue>

        <KeyValue label="Provider" hint="A server-registered rail, not a transaction-level payee.">
          <span className="num">{intent.provider}</span>
        </KeyValue>

        <KeyValue
          label="Provider order ID"
          hint="Not part of the C1 read contract. The C2 provider path will populate it."
        >
          <NotProvided what="provider_order_id" since="C2" />
        </KeyValue>

        <KeyValue
          label="Provider payment ID"
          hint="Null until the provider has positively reported one."
        >
          {intent.provider_payment_id ? (
            <span className="num">{intent.provider_payment_id}</span>
          ) : (
            <span className="text-[color:var(--color-ink-4)]">
              null — no provider payment has been reported for this intent
            </span>
          )}
        </KeyValue>

        <KeyValue
          label="Reconciliation state"
          hint="Not exposed as a field at the C1 baseline. Reconciliation events appear in the audit history and in replay."
        >
          <NotProvided what="reconciliation_state" since="C2" />
        </KeyValue>

        <KeyValue label="Amount" hint="Machine value from the durable intent row.">
          <span className="num">
            {inr(intent.amount_inr)} <span className="text-[color:var(--color-ink-3)]">{intent.currency}</span>
          </span>
        </KeyValue>

        <KeyValue
          label="Merchant ID"
          hint="Server-registered merchant identity. Not a merchant display name."
        >
          <span className="num">{intent.merchant_id}</span>
        </KeyValue>

        <KeyValue label="Attempts" hint="Provider attempts made under this intent.">
          <span className="num">{intent.attempts}</span>
        </KeyValue>

        <KeyValue label="Created at">
          <span className="num">{timestamp(intent.created_at)}</span>
        </KeyValue>

        <KeyValue
          label="Updated at"
          hint="The read model exposes creation only. Transitions are visible as audit events."
        >
          <NotProvided what="updated_at" since="C2" />
        </KeyValue>

        <KeyValue
          label="Idempotency key"
          hint="Shown as a stable prefix. Enough to correlate two views of one payment; not enough to lift from a screenshot and reuse."
        >
          <span className="num">{idempotencyFingerprint(intent.idempotency_key)}</span>
        </KeyValue>
      </KeyValueGrid>

      <div>
        <span className="label-xs text-[color:var(--color-ink-4)]">Last reason code</span>
        {intent.last_reason_code ? (
          <p className="mt-1 text-[12px] leading-snug">
            <code className="num font-semibold text-[color:var(--color-ink)]">
              {intent.last_reason_code}
            </code>
            {describeReasonCode(intent.last_reason_code) ? (
              <span className="text-[color:var(--color-ink-3)]">
                {" "}
                — {describeReasonCode(intent.last_reason_code)}
              </span>
            ) : null}
          </p>
        ) : (
          <p className="mt-1 text-[12px] text-[color:var(--color-ink-4)]">
            null — the last transition carried no reason, or cleared the one before it. A cleared
            reason and an absent one are different facts, and replay reads the difference.
          </p>
        )}
      </div>
    </div>
  );
}
