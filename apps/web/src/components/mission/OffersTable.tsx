import { Check, X } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { cn, inr } from "@/lib/format";
import type { Offer } from "@/lib/types/pactra";

/**
 * Every offer the merchants returned, valid and rejected alike.
 *
 * Rejected offers are shown rather than filtered out, with the reason codes that
 * rejected them. A table of only the survivors would hide the work: the point of
 * the offer stage is what was refused and why.
 */
export function OffersTable({
  offers,
  selectedOfferId,
}: {
  offers: Offer[];
  selectedOfferId?: string | null;
}) {
  return (
    <Panel
      title={`Merchant offers (${offers.length})`}
      subtitle="Untrusted payloads, structurally validated and then adjudicated. Passing schema validation does not make merchant data trusted — it only means the shape is well-formed."
      flush
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-left">
          <thead>
            <tr className="border-b border-[color:var(--color-line)]">
              <Th className="pl-4">Rank</Th>
              <Th>Merchant</Th>
              <Th>Product</Th>
              <Th className="text-right">Amount</Th>
              <Th className="text-right">Rating</Th>
              <Th className="text-right">Trust</Th>
              <Th>Stock</Th>
              <Th className="pr-4">Verdict</Th>
            </tr>
          </thead>
          <tbody>
            {offers.map((offer) => {
              const selected = offer.offer_id === selectedOfferId;
              return (
                <tr
                  key={offer.offer_id}
                  className={cn(
                    "border-b border-[color:var(--color-line)]/60 align-top last:border-b-0",
                    selected && "bg-[color:var(--color-secure)]/[0.05]",
                  )}
                >
                  <td className="num py-2.5 pr-3 pl-4 text-[12px] text-[color:var(--color-ink-3)]">
                    {offer.rank ?? "—"}
                  </td>
                  <td className="py-2.5 pr-3">
                    <p className="text-[12px] text-[color:var(--color-ink)]">{offer.merchant_name}</p>
                    <code className="num text-[10.5px] text-[color:var(--color-ink-4)]">
                      {offer.merchant_id}
                    </code>
                  </td>
                  <td className="max-w-[240px] py-2.5 pr-3">
                    <p className="truncate text-[12px] text-[color:var(--color-ink-2)]" title={offer.title}>
                      {offer.title}
                    </p>
                    <code className="num text-[10.5px] text-[color:var(--color-ink-4)]">
                      {offer.product_id}
                    </code>
                  </td>
                  <td className="num py-2.5 pr-3 text-right text-[12px] text-[color:var(--color-ink)]">
                    {inr(offer.amount_inr)}
                  </td>
                  <td className="num py-2.5 pr-3 text-right text-[12px] text-[color:var(--color-ink-2)]">
                    {offer.rating.toFixed(1)}
                  </td>
                  <td className="num py-2.5 pr-3 text-right text-[12px] text-[color:var(--color-ink-2)]">
                    {offer.merchant_trust.toFixed(2)}
                  </td>
                  <td className="py-2.5 pr-3">
                    {offer.in_stock ? (
                      <Check aria-hidden className="size-3.5 text-[color:var(--color-secure)]" />
                    ) : (
                      <X aria-hidden className="size-3.5 text-[color:var(--color-ink-4)]" />
                    )}
                  </td>
                  <td className="py-2.5 pr-4">
                    <div className="flex flex-col items-start gap-1.5">
                      {offer.valid ? (
                        <Badge tone="secure">VALID</Badge>
                      ) : (
                        <Badge tone="critical" variant="outline">REJECTED</Badge>
                      )}
                      {selected ? <Badge tone="secure" variant="outline">SELECTED</Badge> : null}
                      {offer.rejection_reasons.map((reason) => (
                        <ReasonCode key={reason} code={reason} />
                      ))}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-[color:var(--color-line)] px-4 py-2.5 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
        Free-form merchant text is absent by construction. <code className="num">description</code>{" "}
        is dropped entirely at normalization and never reaches ranking or policy, so a prompt
        injected into a product description has nothing to influence.
      </p>
    </Panel>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th scope="col" className={cn("label-xs py-2 pr-3 text-[color:var(--color-ink-4)]", className)}>
      {children}
    </th>
  );
}
