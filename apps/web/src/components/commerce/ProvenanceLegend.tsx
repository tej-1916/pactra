import { ShieldCheck } from "lucide-react";

import { TaintedText } from "@/components/ui/Provenance";
import { cn } from "@/lib/format";

/**
 * The reading key for every commerce surface.
 *
 * Placed at the top of the page rather than in a tooltip, because the
 * distinction it teaches is the whole security argument: a merchant controls
 * the words, and PACTRA controls the money.
 */
export function ProvenanceLegend({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "grid gap-3 rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3 sm:grid-cols-2 min-w-0 max-w-full overflow-hidden",
        className,
      )}
    >
      <div className="min-w-0 max-w-full">
        <p className="flex items-center gap-1.5">
          <ShieldCheck aria-hidden className="size-3.5 text-[color:var(--color-secure)]" />
          <span className="label-xs text-[color:var(--color-ink-3)]">Authoritative</span>
        </p>
        <p className="num mt-1.5 text-[13px] font-semibold text-[color:var(--color-ink)]">
          ₹4,999 INR · MERCH_042 · ALLOW
        </p>
        <p className="mt-1 max-w-full text-[11.5px] leading-snug text-[color:var(--color-ink-3)] break-words">
          Server-computed or registry-owned. The bound amount, currency, quantity, merchant ID,
          expiry, digest, policy outcome, approval scheme and payment state all come from durable
          state — never from a merchant payload.
        </p>
      </div>

      <div className="min-w-0 max-w-full">
        <p className="label-xs text-[color:var(--color-taint)]">Merchant display data</p>
        <p className="mt-1.5">
          <TaintedText value="Premium Wireless Headphones — LIMITED OFFER" label="Product title" />
        </p>
        <p className="mt-1 max-w-full text-[11.5px] leading-snug text-[color:var(--color-ink-3)] break-words">
          Titles, product IDs, merchant display names and raw query text. Sanitized and
          bidi-isolated before display, and never rendered under TOTAL, PAYEE, POLICY,
          AUTHORIZATION or PAYMENT STATE. A merchant string is descriptive; it is not authority.
        </p>
      </div>
    </div>
  );
}
