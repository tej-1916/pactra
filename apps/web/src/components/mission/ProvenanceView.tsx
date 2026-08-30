import { Panel } from "@/components/ui/Panel";
import { AuthorityBadge, TaintBadge, TrustBadge } from "@/components/ui/StatusBadges";
import { inr } from "@/lib/format";
import type { Offer } from "@/lib/types/pactra";

/**
 * Where each security-relevant value on an offer actually came from.
 *
 * This is the differentiator, so it is stated exactly rather than impressively.
 * The API's `OfferOut` does not carry a per-field provenance map — normalization
 * writes one, but the read model does not project it — so this view does NOT
 * fabricate one. It presents what is genuinely known and provable from the
 * contract PACTRA publishes:
 *
 *   * `amount_inr`, `rating`, `in_stock`, `title` are merchant PAYLOAD values.
 *     `RawMerchantOffer` is the schema they arrive through, so their source is
 *     merchant data at MERCHANT_DATA authority, UNTRUSTED, and tainted.
 *   * `merchant_id` / `merchant_name` / `merchant_trust` are NOT payload values.
 *     `RawMerchantOffer` has no field capable of carrying trust or display name
 *     at all — a merchant sending `{"merchant_trust": 1.0}` has that key
 *     dropped — so they come from the server-owned registry at
 *     TRUSTED_INTERNAL_SERVICE authority, untainted.
 *
 * The authority levels are the real values from `packages/schemas/provenance.py`.
 */

interface Row {
  field: string;
  value: string;
  source: string;
  authority: number;
  trust: string;
  tainted: boolean;
  note: string;
}

export function ProvenanceView({ offer }: { offer: Offer }) {
  const rows: Row[] = [
    {
      field: "amount_inr",
      value: inr(offer.amount_inr),
      source: "merchant payload",
      authority: 10,
      trust: "untrusted",
      tainted: true,
      note: "A price the merchant asserted. It is bound into the transaction digest, so it cannot be changed after approval without invalidating the authorization.",
    },
    {
      field: "rating",
      value: offer.rating.toFixed(1),
      source: "merchant payload",
      authority: 10,
      trust: "untrusted",
      tainted: true,
      note: "Merchant-asserted and policy-relevant, which is exactly why it is adjudicated rather than believed.",
    },
    {
      field: "in_stock",
      value: String(offer.in_stock),
      source: "merchant payload",
      authority: 10,
      trust: "untrusted",
      tainted: true,
      note: "Merchant-asserted availability.",
    },
    {
      field: "title",
      value: offer.title,
      source: "merchant payload",
      authority: 10,
      trust: "untrusted",
      tainted: true,
      note: "Retained as opaque content. Free-form merchant text — including `description` — is discarded at normalization and never reaches ranking or policy.",
    },
    {
      field: "merchant_id",
      value: offer.merchant_id,
      source: "authenticated transport identity",
      authority: 30,
      trust: "trusted",
      tainted: false,
      note: "The identity the transport authenticated, not the one the payload claimed. A mismatch between the two rejects the offer with MERCHANT_IDENTITY_MISMATCH.",
    },
    {
      field: "merchant_name",
      value: offer.merchant_name,
      source: "server-owned merchant registry",
      authority: 30,
      trust: "trusted",
      tainted: false,
      note: "`RawMerchantOffer` has no display-name field, so a merchant cannot supply this at all.",
    },
    {
      field: "merchant_trust",
      value: offer.merchant_trust.toFixed(2),
      source: "server-owned merchant registry",
      authority: 30,
      trust: "trusted",
      tainted: false,
      note: "Trust is a security control, so the platform owns it. A merchant sending `merchant_trust` has the key dropped by the schema — self-assigning a score is structurally impossible, not merely disallowed.",
    },
  ];

  return (
    <Panel
      title="Provenance — where each value came from"
      subtitle="Untrusted data retains provenance and taint through every transformation. Taint is sticky: a transformed untrusted value stays untrusted."
      flush
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse text-left">
          <thead>
            <tr className="border-b border-[color:var(--color-line)]">
              <th scope="col" className="label-xs py-2 pr-3 pl-4 text-[color:var(--color-ink-4)]">Field</th>
              <th scope="col" className="label-xs py-2 pr-3 text-[color:var(--color-ink-4)]">Value</th>
              <th scope="col" className="label-xs py-2 pr-3 text-[color:var(--color-ink-4)]">Source</th>
              <th scope="col" className="label-xs py-2 pr-3 text-[color:var(--color-ink-4)]">Authority</th>
              <th scope="col" className="label-xs py-2 pr-3 text-[color:var(--color-ink-4)]">Trust</th>
              <th scope="col" className="label-xs py-2 pr-4 text-[color:var(--color-ink-4)]">Tainted</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.field} className="border-b border-[color:var(--color-line)]/60 last:border-b-0 align-top">
                <th scope="row" className="num py-2.5 pr-3 pl-4 text-[11.5px] font-normal text-[color:var(--color-ink-2)]">
                  {row.field}
                </th>
                <td className="num max-w-[220px] truncate py-2.5 pr-3 text-[12px] text-[color:var(--color-ink)]" title={row.value}>
                  {row.value}
                </td>
                <td className="py-2.5 pr-3">
                  <p className="text-[11.5px] text-[color:var(--color-ink-2)]">{row.source}</p>
                  <p className="mt-0.5 max-w-[46ch] text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
                    {row.note}
                  </p>
                </td>
                <td className="py-2.5 pr-3"><AuthorityBadge level={row.authority} /></td>
                <td className="py-2.5 pr-3"><TrustBadge trust={row.trust} /></td>
                <td className="py-2.5 pr-4"><TaintBadge tainted={row.tainted} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-[color:var(--color-line)] px-4 py-2.5 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
        Source and authority above are derived from the published schema contract, not from a
        per-field provenance map on the wire: `OfferOut` does not project one. See
        FRONTEND_BACKEND_GAP — a provenance projection on the offer read model would let this table
        be rendered from measured data rather than from the contract.
      </p>
    </Panel>
  );
}
