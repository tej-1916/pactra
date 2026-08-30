"use client";

import { CreditCard, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { HashDisplay } from "@/components/ui/HashDisplay";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { PaymentStateBadge } from "@/components/ui/StatusBadges";
import { PaymentStateMachineView } from "@/components/viz/PaymentStateMachine";
import { count, inr, timestamp } from "@/lib/format";
import { idempotencyFingerprint } from "@/lib/redaction";
import type { PaymentIntent } from "@/lib/types/pactra";

/**
 * The mission's one logical payment.
 *
 * The request button carries no amount, no merchant, no product and no currency,
 * because the API accepts none of them — the intent is derived entirely from the
 * authorization the kernel holds, so a mutated amount cannot be offered, only
 * refused-that-was-never-asked.
 *
 * The idempotency key is shown as a fingerprint. It is a client handle rather
 * than a secret, but it is replay-relevant, and a full value on screen is a full
 * value in a screenshot.
 */
export function PaymentPanel({
  payment,
  onRequest,
  requesting,
  canRequest,
  idempotencyKey,
}: {
  payment: PaymentIntent | null;
  onRequest?: () => void;
  requesting?: boolean;
  canRequest?: boolean;
  idempotencyKey: string;
}) {
  return (
    <Panel
      title="Payment intent"
      subtitle="Requesting a payment writes a durable intent and an outbox row inside one transaction, then returns. No provider is contacted from an HTTP request — the outbox worker reaches the rail out of band."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="secure" variant="outline">RAZORPAY TEST MODE</Badge>
          {payment ? <PaymentStateBadge state={payment.state} /> : null}
          {canRequest && onRequest ? (
            <button
              type="button"
              onClick={onRequest}
              disabled={requesting}
              className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-accent)]/45 bg-[color:var(--color-accent)]/12 px-3 py-1.5 text-[12px] font-semibold text-[color:var(--color-accent)] transition-colors hover:bg-[color:var(--color-accent)]/20 disabled:opacity-50"
            >
              {requesting ? (
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
              ) : (
                <CreditCard aria-hidden className="size-3.5" />
              )}
              {payment ? "Request again (same key)" : "Request payment"}
            </button>
          ) : null}
        </div>
      }
    >
      <div className="space-y-4">
        {payment ? (
          <KeyValueGrid columns={3}>
            <KeyValue label="PaymentIntent id">
              <HashDisplay value={payment.payment_intent_id} head={8} tail={6} />
            </KeyValue>
            <KeyValue label="Amount"><span className="num">{inr(payment.amount_inr)} {payment.currency}</span></KeyValue>
            <KeyValue label="Merchant"><span className="num">{payment.merchant_id}</span></KeyValue>
            <KeyValue label="Provider"><span className="num">{payment.provider}</span></KeyValue>
            <KeyValue label="Provider payment id">
              <span className="num">{payment.provider_payment_id ?? "—"}</span>
            </KeyValue>
            <KeyValue
              label="Idempotency key"
              hint="Shown as a fingerprint. The same key is presented on every retry — a fresh key per attempt would make each retry a new logical payment."
            >
              <span className="num">{idempotencyFingerprint(payment.idempotency_key)}</span>
            </KeyValue>
            <KeyValue label="Attempts"><span className="num">{count(payment.attempts)}</span></KeyValue>
            <KeyValue label="Authorization">
              <HashDisplay value={payment.authorization_id} head={8} tail={6} />
            </KeyValue>
            <KeyValue label="Created"><span className="num">{timestamp(payment.created_at)}</span></KeyValue>
            {payment.last_reason_code ? (
              <KeyValue label="Last reason" className="sm:col-span-2 xl:col-span-3">
                <ReasonCode code={payment.last_reason_code} describe />
              </KeyValue>
            ) : null}
          </KeyValueGrid>
        ) : (
          <p className="text-[12px] leading-relaxed text-[color:var(--color-ink-3)]">
            No payment intent exists for this mission yet. A payment requires an ACTIVE
            authorization — <span className="num">NO VALID AUTHORIZATION → NO PAYMENT</span> is
            enforced at the route and again inside the service.
            <span className="num mt-1.5 block text-[11px] text-[color:var(--color-ink-4)]">
              This console would present idempotency key {idempotencyFingerprint(idempotencyKey)},
              and would present the same value on every retry.
            </span>
          </p>
        )}

        <div className="border-t border-[color:var(--color-line)] pt-4">
          <p className="label-xs mb-3 text-[color:var(--color-ink-4)]">Payment state machine</p>
          <PaymentStateMachineView current={payment?.state ?? null} />
        </div>
      </div>
    </Panel>
  );
}
