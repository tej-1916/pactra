"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowUpRight, ShieldCheck } from "lucide-react";

import { MissionPicker } from "./MissionPicker";
import { ProvenanceLegend } from "./ProvenanceLegend";
import { AuthorizationSchemeCard } from "@/components/authorization/AuthorizationScheme";
import { PaymentReadModel } from "@/components/payment/PaymentReadModel";
import { DecisionTrace } from "@/components/trace/DecisionTrace";
import { Badge } from "@/components/ui/Badge";
import { DataTierBadge } from "@/components/ui/DataTier";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { Authoritative, AuthoritativeField, TaintedText, TaintFindings } from "@/components/ui/Provenance";
import { ResultBoundary } from "@/components/ui/ResultBoundary";
import { EmptyState, PartialDataState, RefusalState } from "@/components/ui/States";
import {
  AuthorizationStatusBadge,
  MissionStateBadge,
  PolicyDecisionBadge,
} from "@/components/ui/StatusBadges";
import { cn, inr, timestamp } from "@/lib/format";
import { useAuthorization, useMission, usePayment, useReplay } from "@/lib/hooks/queries";
import { describeReasonCode } from "@/lib/reason-codes";
import type { Mission, Offer } from "@/lib/types/pactra";

/**
 * Live Commerce — READ ONLY.
 *
 * This screen reads one mission end to end and renders nothing it cannot read.
 * There is no checkout here, no payment button, and no simulated provider
 * handoff: the C2 mutations are not implemented, and a control that merely
 * looked ready for them would be the single most misleading thing this console
 * could show a judge. Mission creation and the payment request live on the
 * mission workbench, which is linked rather than duplicated.
 *
 * Every panel is fed by React Query through the `ApiResult` transport, so
 * "still asking", "nothing exists yet", "PACTRA is unreachable" and "a control
 * refused" stay four different screens rather than one grey box.
 */
export function CommerceConsole() {
  const [missionId, setMissionId] = useState<string | null>(null);

  const mission = useMission(missionId);
  const authorization = useAuthorization(missionId);
  const payment = usePayment(missionId);
  const replay = useReplay(missionId);

  return (
    <div className="space-y-5">
      <Panel
        title="Read a mission"
        subtitle="Everything below is read from the PACTRA API for the mission selected here. No panel on this page can change state."
        actions={<Badge tone="neutral" variant="outline">READ-ONLY FOUNDATION</Badge>}
      >
        <MissionPicker selected={missionId} onSelect={setMissionId} />
      </Panel>

      <ProvenanceLegend />

      {missionId === null ? (
        <EmptyState
          title="No mission selected"
          detail={
            <>
              Pick a mission above, or{" "}
              <Link href="/missions" className="text-[color:var(--color-accent)] underline underline-offset-2">
                run one on the mission workbench
              </Link>{" "}
              first. This page reads; it does not create.
            </>
          }
        />
      ) : (
        <>
          {/* ------------------------------------------- intent & policy -- */}
          <Panel
            title="Mission, intent and deterministic policy"
            subtitle="What was asked for, and what the policy engine decided about it. The decision is deterministic and it is the authority."
            actions={<DataTierBadge tier="live" />}
          >
            <ResultBoundary result={mission.data} isLoading={mission.isPending} what="mission">
              {(data) => <MissionSummary mission={data} />}
            </ResultBoundary>
          </Panel>

          {/* -------------------------------------------------- offers --- */}
          <Panel
            title="Offers and the selected candidate"
            subtitle="The ranker selects an offer ID and nothing else. Amount, currency and merchant identity are reloaded from the authoritative row at BIND — never taken from what the merchant said."
            actions={<DataTierBadge tier="live" />}
          >
            <ResultBoundary result={mission.data} isLoading={mission.isPending} what="offers">
              {(data) => <OfferList mission={data} />}
            </ResultBoundary>
          </Panel>

          {/* ------------------------------------------- authorization --- */}
          <Panel
            title="Authorization"
            subtitle="What exactly is authorized, and by what. POLICY_AUTO is deterministic policy activation; it is not a person approving anything."
            actions={<DataTierBadge tier="live" />}
          >
            <ResultBoundary
              result={authorization.data}
              isLoading={authorization.isPending}
              what="authorization"
              notFound={
                <EmptyState
                  title="No authorization"
                  detail="This mission holds no authorization artifact. Nothing is authorized to spend, and no PaymentIntent can exist."
                />
              }
            >
              {(data) => (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <AuthorizationStatusBadge status={data.status} />
                    <span className="num text-[11px] text-[color:var(--color-ink-4)]">
                      {data.authorization_id}
                    </span>
                  </div>

                  <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
                    <AuthoritativeField
                      heading="TOTAL"
                      value={`${inr(data.bound_amount_inr)} ${data.bound_currency}`}
                      source="Bound machine amount and currency from the reloaded authoritative offer row, times the trusted quantity."
                    />
                    <AuthoritativeField
                      heading="PAYEE"
                      value={data.bound_merchant_id}
                      source="Server-registered merchant ID from adapter registration — not the merchant's claimed identity, and not its display name."
                    />
                    <AuthoritativeField
                      heading="AUTHORIZATION"
                      value={data.approval_scheme}
                      source="How this authorization became active, from the durable authorization row."
                    />
                    <AuthoritativeField
                      heading="POLICY"
                      value={data.policy_version}
                      source="The policy version covered by the transaction digest."
                    />
                  </div>

                  <AuthorizationSchemeCard
                    scheme={data.approval_scheme}
                    signingKeyId={data.signing_key_id}
                  />

                  <KeyValueGrid columns={3}>
                    <KeyValue label="Bound quantity" hint="Trusted mission state, not merchant input.">
                      <Authoritative>{data.bound_quantity}</Authoritative>
                    </KeyValue>
                    <KeyValue
                      label="Bound product"
                      hint="Integrity-protected as the exact selected value, and still merchant-originated descriptive identity."
                    >
                      <TaintedText value={data.bound_product_id} label="Product ID" />
                    </KeyValue>
                    <KeyValue label="Binding version">
                      <Authoritative>{data.binding_version}</Authoritative>
                    </KeyValue>
                    <KeyValue label="Offer version">
                      <Authoritative>{data.offer_version}</Authoritative>
                    </KeyValue>
                    <KeyValue label="Issued at">
                      <Authoritative>{timestamp(data.issued_at)}</Authoritative>
                    </KeyValue>
                    <KeyValue label="Expires at" hint="Checked against the server clock at consumption.">
                      <Authoritative>{timestamp(data.expires_at)}</Authoritative>
                    </KeyValue>
                    <KeyValue label="Consumed at">
                      <Authoritative>{timestamp(data.consumed_at)}</Authoritative>
                    </KeyValue>
                    <KeyValue
                      label="Transaction digest"
                      className="sm:col-span-2 xl:col-span-2"
                      hint="Covers merchant, product, quantity, amount, currency, policy version, offer version, expiry and the server-held nonce."
                    >
                      <Authoritative className="break-all text-[11px]">
                        {data.transaction_digest}
                      </Authoritative>
                    </KeyValue>
                  </KeyValueGrid>

                  <p className="text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
                    The authorization nonce and any approval signature are absent from this screen
                    because the API never sends them. There is no field here that could hold key
                    material.
                  </p>
                </div>
              )}
            </ResultBoundary>
          </Panel>

          {/* ------------------------------------------------- payment ---- */}
          <Panel
            title="Payment state"
            subtitle="The durable PaymentIntent as PACTRA holds it. Read-only: the C2 provider path is not implemented here, and nothing on this page can request a payment."
            actions={<DataTierBadge tier="live" />}
          >
            <ResultBoundary
              result={payment.data}
              isLoading={payment.isPending}
              what="payment intent"
              notFound={
                <EmptyState
                  title="No PaymentIntent"
                  detail="No durable PaymentIntent exists for this mission. An intent is created only when an ACTIVE authorization is atomically consumed."
                />
              }
            >
              {(data) => <PaymentReadModel intent={data} />}
            </ResultBoundary>
          </Panel>

          {/* -------------------------------------------- decision trace -- */}
          <Panel
            title="Decision Trace"
            subtitle="ADMIT → BIND → EXECUTE, projected from the verified hash chain. What happened, why, and what can happen next."
            actions={<DataTierBadge tier="live" />}
          >
            <ResultBoundary result={replay.data} isLoading={replay.isPending} what="decision trace">
              {(data) =>
                data.trusted ? (
                  <DecisionTrace entries={data.decision_trace} />
                ) : (
                  <PartialDataState
                    title="No trusted trace for this mission"
                    detail={
                      <>
                        Replay returned <code className="num">trusted: false</code> with reason code{" "}
                        <code className="num">{data.reason_code}</code>
                        {describeReasonCode(data.reason_code)
                          ? ` — ${describeReasonCode(data.reason_code)}`
                          : ""}
                        . The Decision Trace is produced only after the hash chain verifies and
                        every enforcement event can be interpreted, so it is empty here rather than
                        partially reconstructed. A projection from history that did not verify
                        would be a confident-looking lie.
                        {data.detail ? (
                          <span className="mt-1.5 block text-[color:var(--color-ink-3)]">
                            {data.detail}
                          </span>
                        ) : null}
                      </>
                    }
                  />
                )
              }
            </ResultBoundary>
          </Panel>

          <p className="text-[11.5px] leading-relaxed text-[color:var(--color-ink-4)]">
            Interactive checkout, provider handoff and the live payment path arrive with C2 and C5b.
            Nothing on this page simulates them.{" "}
            <Link
              href="/missions"
              className="inline-flex items-center gap-1 text-[color:var(--color-accent)] hover:underline"
            >
              The mission workbench
              <ArrowUpRight aria-hidden className="size-3" />
            </Link>{" "}
            is where a mission is run today.
          </p>
        </>
      )}
    </div>
  );
}

function MissionSummary({ mission }: { mission: Mission }) {
  const policy = mission.policy_decision;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <MissionStateBadge state={mission.state} />
        {policy ? <PolicyDecisionBadge decision={policy.decision} /> : null}
        <span className="num text-[11px] text-[color:var(--color-ink-4)]">{mission.id}</span>
      </div>

      <KeyValueGrid columns={3}>
        <KeyValue
          label="Raw query"
          className="sm:col-span-2"
          hint="User-supplied free text. Untrusted, and displayed as merchant-class display data."
        >
          <TaintedText value={mission.raw_query} label="Raw query" />
          <TaintFindings value={mission.raw_query} />
        </KeyValue>
        <KeyValue label="Quantity" hint="Trusted mission state.">
          <Authoritative>{mission.quantity}</Authoritative>
        </KeyValue>
        <KeyValue label="Created at">
          <Authoritative>{timestamp(mission.created_at)}</Authoritative>
        </KeyValue>
      </KeyValueGrid>

      {policy ? (
        <div className="rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <ShieldCheck aria-hidden className="size-3.5 text-[color:var(--color-secure)]" />
            <span className="label-xs text-[color:var(--color-ink-3)]">
              Deterministic policy decision
            </span>
            <code className="num text-[12px] font-semibold text-[color:var(--color-ink)]">
              {policy.decision}
            </code>
            <span className="num text-[10.5px] text-[color:var(--color-ink-4)]">
              {policy.policy_version}
            </span>
          </div>

          <KeyValueGrid columns={3} className="mt-2.5">
            <KeyValue label="Requested amount">
              <Authoritative>{inr(policy.requested_amount)}</Authoritative>
            </KeyValue>
            <KeyValue label="Soft budget" hint="Above this, a human approval is required.">
              <Authoritative>{inr(policy.soft_budget)}</Authoritative>
            </KeyValue>
            <KeyValue label="Hard limit" hint="An absolute ceiling. No approval can raise it.">
              <Authoritative>{inr(policy.hard_limit)}</Authoritative>
            </KeyValue>
          </KeyValueGrid>

          {policy.reason_codes.length > 0 ? (
            <ul className="mt-2.5 space-y-1">
              {policy.reason_codes.map((code) => (
                <li key={code} className="text-[11.5px] leading-snug">
                  <code className="num font-semibold text-[color:var(--color-ink)]">{code}</code>
                  {describeReasonCode(code) ? (
                    <span className="text-[color:var(--color-ink-3)]"> — {describeReasonCode(code)}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : (
        <RefusalState
          title="No policy decision recorded"
          detail="This mission has not reached a deterministic policy decision. Nothing downstream of policy can exist without one."
        />
      )}
    </div>
  );
}

function OfferList({ mission }: { mission: Mission }) {
  const selectedId = mission.policy_decision?.selected_offer_id ?? null;

  if (mission.offers.length === 0) {
    return (
      <EmptyState
        title="No offers"
        detail="Discovery returned nothing for this mission, so there was nothing to rank or decide about."
      />
    );
  }

  return (
    <ul className="space-y-2">
      {mission.offers.map((offer) => (
        <OfferRow key={offer.offer_id} offer={offer} selected={offer.offer_id === selectedId} />
      ))}
    </ul>
  );
}

function OfferRow({ offer, selected }: { offer: Offer; selected: boolean }) {
  return (
    <li
      data-testid="offer-row"
      data-selected={selected ? "true" : "false"}
      className={cn(
        "rounded-md border p-3",
        selected
          ? // The selected offer is one of the four places gradient is spent.
            "border-[color:var(--color-accent)]/50 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--color-accent)_10%,transparent),color-mix(in_srgb,var(--color-accent-2)_8%,transparent))]"
          : "border-[color:var(--color-line)] bg-[color:var(--color-surface)]",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {selected ? <Badge tone="accent">SELECTED</Badge> : null}
          {offer.valid ? null : (
            <Badge tone="critical" variant="outline">
              INVALID
            </Badge>
          )}
          <TaintedText value={offer.title} label="Product title" />
        </div>
        <Authoritative className="text-[14px] font-semibold whitespace-nowrap">
          {inr(offer.amount_inr)} {offer.currency}
        </Authoritative>
      </div>

      <TaintFindings value={offer.title} />

      <KeyValueGrid columns={3} className="mt-2.5">
        <KeyValue label="Merchant ID" hint="Server-registered. This is the authoritative payee semantic.">
          <Authoritative>{offer.merchant_id}</Authoritative>
        </KeyValue>
        <KeyValue
          label="Merchant display name"
          hint="Registry display data. It is not cryptographic merchant identity and must never replace the merchant ID."
        >
          <TaintedText value={offer.merchant_name} label="Display name" />
        </KeyValue>
        <KeyValue label="Offer version" hint="Server-computed content fingerprint at selection time.">
          <Authoritative className="truncate text-[11px]">{offer.offer_version}</Authoritative>
        </KeyValue>
        <KeyValue label="Product ID">
          <TaintedText value={offer.product_id} label="Product ID" />
        </KeyValue>
        <KeyValue label="Merchant trust" hint="From the server-owned registry. An adapter assigns none.">
          <Authoritative>{offer.merchant_trust}</Authoritative>
        </KeyValue>
        <KeyValue label="Rank">
          <Authoritative>{offer.rank ?? "—"}</Authoritative>
        </KeyValue>
      </KeyValueGrid>

      {offer.rejection_reasons.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {offer.rejection_reasons.map((code) => (
            <li key={code} className="text-[11.5px] leading-snug">
              <code className="num font-semibold text-[color:var(--color-ink)]">{code}</code>
              {describeReasonCode(code) ? (
                <span className="text-[color:var(--color-ink-3)]"> — {describeReasonCode(code)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
