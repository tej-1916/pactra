"use client";

import { CheckCircle2, KeyRound, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { HashDisplay } from "@/components/ui/HashDisplay";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { AuthorizationStatusBadge } from "@/components/ui/StatusBadges";
import { inr, timestamp } from "@/lib/format";
import type { Authorization } from "@/lib/types/pactra";

/**
 * The authorization artifact.
 *
 * The bound fields are shown together and labelled as the binding, because that
 * is the security claim: an approval commits to ONE exact transaction, and a
 * merchant that edits its offer after approval cannot keep the authorization
 * valid — the digest covers the offer version.
 *
 * The nonce is not shown and there is no field for it: the API never sends it.
 * The artifact is also described as SERVER-ISSUED rather than signed, because
 * PACTRA implements no signing (KL-04) and no label here claims one.
 */
export function AuthorizationPanel({
  authorization,
  onApprove,
  approving,
  canApprove,
}: {
  authorization: Authorization;
  onApprove?: () => void;
  approving?: boolean;
  canApprove?: boolean;
}) {
  return (
    <Panel
      title="Authorization artifact"
      subtitle="One-time, expiring, and bound to exactly one transaction. Activation is an atomic conditional update, so a second approval of the same authorization cannot succeed."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <AuthorizationStatusBadge status={authorization.status} />
          {canApprove && onApprove ? (
            <button
              type="button"
              onClick={onApprove}
              disabled={approving}
              className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-secure)]/45 bg-[color:var(--color-secure)]/12 px-3 py-1.5 text-[12px] font-semibold text-[color:var(--color-secure)] transition-colors hover:bg-[color:var(--color-secure)]/20 disabled:opacity-50"
            >
              {approving ? (
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
              ) : (
                <CheckCircle2 aria-hidden className="size-3.5" />
              )}
              Approve as human
            </button>
          ) : null}
        </div>
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg border border-[color:var(--color-accent)]/25 bg-[color:var(--color-accent)]/[0.05] p-3.5">
          <p className="label-xs mb-2.5 flex items-center gap-1.5 text-[color:var(--color-accent)]">
            <KeyRound aria-hidden className="size-3.5" />
            Bound transaction — the approval commits to this and nothing else
          </p>
          <KeyValueGrid columns={3}>
            <KeyValue label="Merchant"><span className="num">{authorization.bound_merchant_id}</span></KeyValue>
            <KeyValue label="Product"><span className="num">{authorization.bound_product_id}</span></KeyValue>
            <KeyValue label="Quantity"><span className="num">{authorization.bound_quantity}</span></KeyValue>
            <KeyValue label="Amount"><span className="num">{inr(authorization.bound_amount_inr)}</span></KeyValue>
            <KeyValue label="Currency"><span className="num">{authorization.bound_currency}</span></KeyValue>
            <KeyValue label="Transaction digest">
              <HashDisplay value={authorization.transaction_digest} head={12} tail={8} />
            </KeyValue>
          </KeyValueGrid>
        </div>

        <KeyValueGrid columns={3}>
          <KeyValue label="Authorization id">
            <HashDisplay value={authorization.authorization_id} head={8} tail={6} />
          </KeyValue>
          <KeyValue label="Issued at"><span className="num">{timestamp(authorization.issued_at)}</span></KeyValue>
          <KeyValue
            label="Expires at"
            hint="Short by design: an approval is a commitment to one transaction at one moment, and a long window is a long replay window."
          >
            <span className="num">{timestamp(authorization.expires_at)}</span>
          </KeyValue>
          <KeyValue label="Consumed at">
            <span className="num">{timestamp(authorization.consumed_at)}</span>
          </KeyValue>
          <KeyValue
            label="Versions bound in"
            className="sm:col-span-2"
            hint="Bound into the digest so an approval cannot be carried across a policy change or an edited offer."
          >
            <span className="num text-[11.5px]">
              binding {authorization.binding_version} · policy {authorization.policy_version} · offer{" "}
              {authorization.offer_version}
            </span>
          </KeyValue>
        </KeyValueGrid>

        <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--color-line)] pt-3">
          <Badge tone="neutral" variant="outline">SERVER-ISSUED</Badge>
          <Badge tone="neutral" variant="outline">NOT CRYPTOGRAPHICALLY SIGNED</Badge>
          <p className="text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
            KL-04: there is no user signature and no signature verification anywhere. This artifact
            is authoritative because it is minted, held and consumed entirely inside the trusted
            server boundary. The nonce is server-held entropy and is never returned by the API — so
            it is absent here rather than hidden.
          </p>
        </div>
      </div>
    </Panel>
  );
}
