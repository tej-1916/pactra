import { Store, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { TaintedText, TaintFindings } from "@/components/ui/Provenance";
import { inr } from "@/lib/format";

export function MerchantOfferPanel({
  merchantName,
  productId,
  productTitle,
  quotedAmountInr,
  currency,
  offerVersion,
  isDemo = true,
}: {
  merchantName: string;
  productId: string;
  productTitle: string;
  quotedAmountInr: number;
  currency: string;
  offerVersion: string;
  isDemo?: boolean;
}) {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Store className="size-4 text-[color:var(--pactra-warning)]" />
          <span className="font-display text-[14px] font-bold text-[color:var(--pactra-ink)]">
            MERCHANT OFFER
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {isDemo && (
            <span className="font-mono text-[9.5px] font-semibold text-[color:var(--pactra-ink-muted)] bg-[color:var(--pactra-surface-3)] px-1.5 py-0.5 rounded">
              SYNTHETIC DEMO DATA
            </span>
          )}
          <Badge tone="advisory" variant="outline" icon={<ShieldAlert className="size-3" />}>
            UNTRUSTED INPUT
          </Badge>
        </div>
      </div>

      {/* Quoted Product */}
      <div className="rounded bg-[color:var(--pactra-surface-3)] p-2.5 space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
            QUOTED PRODUCT TITLE
          </span>
          <span className="font-mono text-[12px] font-bold text-[color:var(--pactra-warning)]">
            {inr(quotedAmountInr)} {currency}
          </span>
        </div>
        <TaintedText value={productTitle} label="Product title" className="text-[12.5px] font-semibold text-white" />
        <TaintFindings value={productTitle} />
      </div>

      <KeyValueGrid columns={2}>
        <KeyValue label="Merchant Display Name" hint="Unverified display string from merchant payload.">
          <TaintedText value={merchantName} label="Display name" className="text-[11.5px]" />
        </KeyValue>

        <KeyValue label="Product ID" hint="Merchant catalog item reference.">
          <TaintedText value={productId} label="Product ID" className="text-[11.5px]" />
        </KeyValue>

        <KeyValue label="Offer Version" hint="Merchant payload version signature.">
          <span className="font-mono text-[11px] text-[color:var(--pactra-ink-muted)]">
            {offerVersion} {isDemo && "(DEMO OFFER)"}
          </span>
        </KeyValue>
      </KeyValueGrid>

      {/* Untrusted Input Marker */}
      <div className="rounded border border-[color:var(--pactra-warning)]/30 bg-[color:var(--pactra-warning)]/10 p-2.5 text-[11px] leading-relaxed text-[color:var(--pactra-ink-secondary)] flex items-start gap-2">
        <ShieldAlert className="size-3.5 text-[color:var(--pactra-warning)] shrink-0 mt-0.5" />
        <div>
          <span className="font-mono font-bold text-[color:var(--pactra-warning)] uppercase">UNTRUSTED INPUT MARKER:</span>{" "}
          Merchant-controlled strings are untrusted input by default. Untrusted does not mean malicious — it means unverified. Registered payee identity is resolved separately by PACTRA authority.
        </div>
      </div>
    </div>
  );
}
