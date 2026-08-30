"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ExternalLink, Info } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { HashDisplay } from "@/components/ui/HashDisplay";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { EmptyState, LoadingSkeleton, UnavailableState } from "@/components/ui/States";
import { AuthorizationStatusBadge, PaymentStateBadge } from "@/components/ui/StatusBadges";
import { api } from "@/lib/api/client";
import { count, inr, shortId, timestamp } from "@/lib/format";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";
import { idempotencyFingerprint } from "@/lib/redaction";
import type { Authorization, PaymentIntent } from "@/lib/types/pactra";

interface Row {
  missionId: string;
  payment: PaymentIntent | null;
  authorization: Authorization | null;
  unavailable: boolean;
}

/**
 * Payment observability across the missions this browser created.
 *
 * PACTRA has no payment-list endpoint. Rather than invent one, this reads each
 * registered mission's payment intent individually and says on the surface that
 * the scope is browser-local. A row with no payment is shown as having none,
 * which is a fact about the mission; a row that could not be read is shown as
 * unreadable, which is a fact about the connection.
 *
 * The idempotency key is fingerprinted, and `provider_payment_id` is shown as
 * returned — it is a provider-side reference, not a credential.
 */
export function TransactionsView() {
  const { missions, hydrated } = useMissionRegister();
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    void (async () => {
      const resolved = await Promise.all(
        missions.map(async (entry): Promise<Row> => {
          const [payment, authorization] = await Promise.all([
            api.getPayment(entry.id),
            api.getAuthorization(entry.id),
          ]);
          return {
            missionId: entry.id,
            payment: payment.kind === "ok" ? payment.data : null,
            authorization: authorization.kind === "ok" ? authorization.data : null,
            unavailable: payment.kind === "unavailable" || authorization.kind === "unavailable",
          };
        }),
      );
      if (!cancelled) setRows(resolved);
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrated, missions]);

  if (!hydrated || rows === null) return <LoadingSkeleton rows={4} />;

  if (missions.length === 0) {
    return (
      <EmptyState
        title="No missions in this browser's register"
        detail={
          <>
            Payment intents are read per mission, and this console has not created any. Run one from
            the{" "}
            <Link href="/missions" className="text-[color:var(--color-accent)] hover:underline">
              Mission Workbench
            </Link>{" "}
            to populate this view.
          </>
        }
      />
    );
  }

  if (rows.every((row) => row.unavailable)) {
    return (
      <UnavailableState
        title="PACTRA API unavailable"
        detail="These missions exist in this browser's register but their payment state cannot be read. Nothing here is being reported as zero."
      />
    );
  }

  const withPayments = rows.filter((row) => row.payment !== null);

  return (
    <Panel
      title={`Payment intents (${withPayments.length} of ${rows.length} missions)`}
      subtitle={
        <span className="flex items-start gap-1.5">
          <Info aria-hidden className="mt-[2px] size-3.5 shrink-0" />
          PACTRA exposes no payment-list endpoint, so this is scoped to missions this browser
          created. Each row is read live from the mission&apos;s own payment route.
        </span>
      }
      flush
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1080px] border-collapse text-left">
          <thead>
            <tr className="border-b border-[color:var(--color-line)]">
              <Th className="pl-4">PaymentIntent</Th>
              <Th>Mission</Th>
              <Th>Merchant</Th>
              <Th className="text-right">Amount</Th>
              <Th>State</Th>
              <Th>Provider</Th>
              <Th>Idem. key</Th>
              <Th>Authorization</Th>
              <Th className="text-right">Attempts</Th>
              <Th className="pr-4">Last reason</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.missionId} className="border-b border-[color:var(--color-line)]/60 align-top last:border-b-0">
                <td className="py-2.5 pr-3 pl-4">
                  {row.payment ? (
                    <HashDisplay value={row.payment.payment_intent_id} head={8} tail={4} />
                  ) : (
                    <span className="text-[11.5px] text-[color:var(--color-ink-4)]">
                      {row.unavailable ? "unreadable" : "none"}
                    </span>
                  )}
                  {row.payment ? (
                    <span className="num mt-0.5 block text-[10.5px] text-[color:var(--color-ink-4)]">
                      {timestamp(row.payment.created_at)}
                    </span>
                  ) : null}
                </td>
                <td className="py-2.5 pr-3">
                  <Link
                    href={`/missions/${row.missionId}`}
                    className="num inline-flex items-center gap-1 text-[11.5px] text-[color:var(--color-accent)] hover:underline"
                  >
                    {shortId(row.missionId, 8)}
                    <ExternalLink aria-hidden className="size-3" />
                  </Link>
                </td>
                <td className="num py-2.5 pr-3 text-[11.5px] text-[color:var(--color-ink-2)]">
                  {row.payment?.merchant_id ?? "—"}
                </td>
                <td className="num py-2.5 pr-3 text-right text-[12px] text-[color:var(--color-ink)]">
                  {row.payment ? `${inr(row.payment.amount_inr)} ${row.payment.currency}` : "—"}
                </td>
                <td className="py-2.5 pr-3">
                  {row.payment ? <PaymentStateBadge state={row.payment.state} /> : <span className="text-[color:var(--color-ink-4)]">—</span>}
                </td>
                <td className="py-2.5 pr-3">
                  {row.payment ? (
                    <div className="flex flex-col items-start gap-1">
                      <span className="num text-[11.5px] text-[color:var(--color-ink-2)]">
                        {row.payment.provider}
                      </span>
                      <Badge tone="secure" variant="outline">TEST MODE</Badge>
                      {row.payment.provider_payment_id ? (
                        <span className="num text-[10.5px] text-[color:var(--color-ink-4)]">
                          {row.payment.provider_payment_id}
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <span className="text-[color:var(--color-ink-4)]">—</span>
                  )}
                </td>
                <td className="num py-2.5 pr-3 text-[11px] text-[color:var(--color-ink-3)]">
                  {row.payment ? idempotencyFingerprint(row.payment.idempotency_key) : "—"}
                </td>
                <td className="py-2.5 pr-3">
                  {row.authorization ? (
                    <AuthorizationStatusBadge status={row.authorization.status} />
                  ) : (
                    <span className="text-[11.5px] text-[color:var(--color-ink-4)]">none</span>
                  )}
                </td>
                <td className="num py-2.5 pr-3 text-right text-[12px] text-[color:var(--color-ink-2)]">
                  {row.payment ? count(row.payment.attempts) : "—"}
                </td>
                <td className="py-2.5 pr-4">
                  {row.payment?.last_reason_code ? (
                    <ReasonCode code={row.payment.last_reason_code} />
                  ) : (
                    <span className="text-[color:var(--color-ink-4)]">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-[color:var(--color-line)] px-4 py-2.5 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
        Not shown, because the API does not project them: the request fingerprint (what an
        idempotency-conflict check compares against — handing it out would let a caller probe for a
        colliding request) and the authorization nonce. Reconciliation state is not a separate field
        on the read model; it is observable through the state machine and the audit events.
      </p>
    </Panel>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th
      scope="col"
      className={["label-xs py-2 pr-3 text-[color:var(--color-ink-4)]", className].filter(Boolean).join(" ")}
    >
      {children}
    </th>
  );
}
