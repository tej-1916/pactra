"use client";

import { useState } from "react";
import { ShieldCheck } from "lucide-react";

import { MissionPicker } from "./MissionPicker";
import { ProvenanceLegend } from "./ProvenanceLegend";
import { ScenarioSelector, type RuntimeEvidenceStatus } from "./ScenarioSelector";
import { DEMO_SCENARIOS, type ScenarioId } from "./demoScenarios";
import { AiBuyerPanel } from "./AiBuyerPanel";
import { MerchantOfferPanel } from "./MerchantOfferPanel";
import { TransactionJourney } from "./TransactionJourney";
import { AuthoritativeEvidencePanel } from "./AuthoritativeEvidencePanel";
import { CommerceTraceTimeline } from "./CommerceTraceTimeline";

import { AuthorizationSchemeCard } from "@/components/authorization/AuthorizationScheme";
import { PaymentReadModel } from "@/components/payment/PaymentReadModel";
import { DecisionTrace } from "@/components/trace/DecisionTrace";
import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { Authoritative, AuthoritativeField, TaintedText, TaintFindings } from "@/components/ui/Provenance";
import { ResultBoundary } from "@/components/ui/ResultBoundary";
import { EmptyState, PartialDataState } from "@/components/ui/States";
import {
  AuthorizationStatusBadge,
  MissionStateBadge,
  PolicyDecisionBadge,
} from "@/components/ui/StatusBadges";
import { cn, inr, timestamp } from "@/lib/format";
import { useAuthorization, useMission, usePayment, useReplay } from "@/lib/hooks/queries";
import type { Mission, Offer } from "@/lib/types/pactra";

export function CommerceConsole() {
  const [selectedScenario, setSelectedScenario] = useState<ScenarioId>("BENIGN_PURCHASE");
  const [missionId, setMissionId] = useState<string | null>(null);

  const isLiveRuntime = selectedScenario === "LIVE_RUNTIME";

  const mission = useMission(isLiveRuntime ? missionId : null);
  const authorization = useAuthorization(isLiveRuntime ? missionId : null);
  const payment = usePayment(isLiveRuntime ? missionId : null);
  const replay = useReplay(isLiveRuntime ? missionId : null);

  const activeDemo = !isLiveRuntime ? DEMO_SCENARIOS[selectedScenario] : null;

  // Determine runtime evidence status
  let runtimeStatus: RuntimeEvidenceStatus = "none";
  if (isLiveRuntime) {
    if (mission.isPending) {
      runtimeStatus = "pending";
    } else if (mission.data?.kind === "unavailable" || mission.data?.kind === "failed") {
      runtimeStatus = "unavailable";
    } else if (mission.data?.kind === "ok") {
      runtimeStatus = "loaded";
    } else if (missionId === null) {
      runtimeStatus = "none";
    }
  }

  return (
    <div className="space-y-6">
      {/* Top Scenario Selector */}
      <ScenarioSelector
        selectedScenario={selectedScenario}
        onSelectScenario={setSelectedScenario}
        runtimeStatus={runtimeStatus}
      />

      <ProvenanceLegend />

      {/* ----------------- DEMO WORKBENCH VIEW ----------------- */}
      {activeDemo && (
        <div className="space-y-6">
          {/* 3-Column Responsive Workbench Layout */}
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3 items-start">
            {/* Left Column: Source & Proposal */}
            <div className="space-y-4">
              <AiBuyerPanel
                missionQuery={activeDemo.aiBuyer.missionQuery}
                constraints={activeDemo.aiBuyer.constraints}
                candidateId={activeDemo.aiBuyer.candidateId}
                rationale={activeDemo.aiBuyer.rationale}
              />
              <MerchantOfferPanel
                merchantName={activeDemo.merchantOffer.merchantName}
                productId={activeDemo.merchantOffer.productId}
                productTitle={activeDemo.merchantOffer.productTitle}
                quotedAmountInr={activeDemo.merchantOffer.quotedAmountInr}
                currency={activeDemo.merchantOffer.currency}
                offerVersion={activeDemo.merchantOffer.offerVersion}
                isDemo={true}
              />
            </div>

            {/* Center Column: Transaction Journey (ADMIT -> BIND -> EXECUTE) */}
            <div className="space-y-4">
              <TransactionJourney scenario={activeDemo} />
            </div>

            {/* Right Column: Authoritative Transaction & Evidence */}
            <div className="space-y-4 md:col-span-2 xl:col-span-1">
              <AuthoritativeEvidencePanel scenario={activeDemo} />
            </div>
          </div>

          {/* Bottom Section: Decision Trace Timeline */}
          <CommerceTraceTimeline
            entries={activeDemo.decisionTrace}
            isDemo={true}
          />
        </div>
      )}

      {/* ----------------- LIVE RUNTIME API VIEW ----------------- */}
      {isLiveRuntime && (
        <div className="space-y-5">
          <Panel
            title="Read a live API mission"
            subtitle="Select an active mission ID from the PACTRA API. Every panel reads live runtime evidence."
            actions={
              runtimeStatus === "loaded" ? (
                <Badge tone="secure" variant="outline">
                  RUNTIME EVIDENCE
                </Badge>
              ) : runtimeStatus === "pending" ? (
                <Badge tone="advisory" variant="outline">
                  AWAITING RUNTIME EVIDENCE
                </Badge>
              ) : runtimeStatus === "unavailable" ? (
                <Badge tone="critical" variant="outline">
                  RUNTIME EVIDENCE UNAVAILABLE
                </Badge>
              ) : (
                <Badge tone="neutral" variant="outline">
                  SELECT MISSION
                </Badge>
              )
            }
          >
            <MissionPicker selected={missionId} onSelect={setMissionId} />
          </Panel>

          {missionId === null ? (
            <EmptyState
              title="No mission selected"
              detail={
                <>
                  Pick a live mission above, or select an interactive scenario from the scenario bar.
                </>
              }
            />
          ) : (
            <>
              {/* Mission Summary */}
              <Panel
                title="Mission, intent and deterministic policy"
                subtitle="What was asked for, and what the policy engine decided about it."
                actions={
                  runtimeStatus === "loaded" ? (
                    <Badge tone="secure" variant="outline">
                      RUNTIME EVIDENCE
                    </Badge>
                  ) : null
                }
              >
                <ResultBoundary result={mission.data} isLoading={mission.isPending} what="mission">
                  {(data) => <MissionSummary mission={data} />}
                </ResultBoundary>
              </Panel>

              {/* Offers */}
              <Panel
                title="Offers and the selected candidate"
                subtitle="The ranker selects an offer ID. Amount and payee are reloaded from the authoritative row at BIND."
                actions={
                  runtimeStatus === "loaded" ? (
                    <Badge tone="secure" variant="outline">
                      RUNTIME EVIDENCE
                    </Badge>
                  ) : null
                }
              >
                <ResultBoundary result={mission.data} isLoading={mission.isPending} what="offers">
                  {(data) => <OfferList mission={data} />}
                </ResultBoundary>
              </Panel>

              {/* Authorization */}
              <Panel
                title="Authorization"
                subtitle="POLICY_AUTO is deterministic policy activation; USER_ED25519 is cryptographic user approval."
                actions={
                  runtimeStatus === "loaded" ? (
                    <Badge tone="secure" variant="outline">
                      RUNTIME EVIDENCE
                    </Badge>
                  ) : null
                }
              >
                <ResultBoundary
                  result={authorization.data}
                  isLoading={authorization.isPending}
                  what="authorization"
                  notFound={
                    <EmptyState
                      title="No authorization"
                      detail="This mission holds no authorization artifact. Nothing is authorized to spend."
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
                          heading="REGISTERED PAYEE (AUTHORITATIVE LOOKUP)"
                          value={data.bound_merchant_id}
                          source="Server-registered merchant ID from adapter registration."
                        />
                        <AuthoritativeField
                          heading="BOUND TOTAL"
                          value={`${inr(data.bound_amount_inr)} ${data.bound_currency}`}
                          source="Bound machine amount and currency from the reloaded authoritative offer row."
                        />
                        <AuthoritativeField
                          heading="AUTHORIZATION"
                          value={data.approval_scheme}
                          source="Approval scheme activation mode."
                        />
                        <AuthoritativeField
                          heading="POLICY"
                          value={data.policy_version}
                          source="Policy version covered by canonical transaction digest."
                        />
                      </div>

                      <AuthorizationSchemeCard
                        scheme={data.approval_scheme}
                        signingKeyId={data.signing_key_id}
                      />

                      <KeyValueGrid columns={3}>
                        <KeyValue label="Bound quantity">
                          <Authoritative>{data.bound_quantity}</Authoritative>
                        </KeyValue>
                        <KeyValue label="Bound product">
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
                        <KeyValue label="Expires at">
                          <Authoritative>{timestamp(data.expires_at)}</Authoritative>
                        </KeyValue>
                        <KeyValue label="Transaction digest" className="sm:col-span-2 xl:col-span-2">
                          <Authoritative className="break-all text-[11px]">
                            {data.transaction_digest}
                          </Authoritative>
                        </KeyValue>
                      </KeyValueGrid>
                    </div>
                  )}
                </ResultBoundary>
              </Panel>

              {/* Payment State */}
              <Panel
                title="Payment state"
                subtitle="The durable PaymentIntent as PACTRA holds it."
                actions={
                  runtimeStatus === "loaded" ? (
                    <Badge tone="secure" variant="outline">
                      RUNTIME EVIDENCE
                    </Badge>
                  ) : null
                }
              >
                <ResultBoundary
                  result={payment.data}
                  isLoading={payment.isPending}
                  what="payment intent"
                  notFound={
                    <EmptyState
                      title="No PaymentIntent"
                      detail="No durable PaymentIntent exists for this mission. An intent is created only when an ACTIVE authorization is consumed."
                    />
                  }
                >
                  {(data) => <PaymentReadModel intent={data} />}
                </ResultBoundary>
              </Panel>

              {/* Decision Trace */}
              <Panel
                title="Decision Trace"
                subtitle="ADMIT → BIND → EXECUTE, projected from the verified hash chain."
                actions={
                  runtimeStatus === "loaded" ? (
                    <Badge tone="secure" variant="outline">
                      RUNTIME EVIDENCE
                    </Badge>
                  ) : null
                }
              >
                <ResultBoundary result={replay.data} isLoading={replay.isPending} what="decision trace">
                  {(data) =>
                    data.trusted ? (
                      <DecisionTrace entries={data.decision_trace} />
                    ) : (
                      <PartialDataState
                        title="No trusted trace for this mission"
                        detail={`Replay returned trusted: false with reason code ${data.reason_code}.`}
                      />
                    )
                  }
                </ResultBoundary>
              </Panel>
            </>
          )}
        </div>
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
        <KeyValue label="Raw query" className="sm:col-span-2">
          <TaintedText value={mission.raw_query} label="Raw query" />
          <TaintFindings value={mission.raw_query} />
        </KeyValue>
        <KeyValue label="Quantity">
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
            <KeyValue label="Soft budget">
              <Authoritative>{inr(policy.soft_budget)}</Authoritative>
            </KeyValue>
            <KeyValue label="Hard limit">
              <Authoritative>{inr(policy.hard_limit)}</Authoritative>
            </KeyValue>
          </KeyValueGrid>
        </div>
      ) : null}
    </div>
  );
}

function OfferList({ mission }: { mission: Mission }) {
  const selectedId = mission.policy_decision?.selected_offer_id ?? null;

  if (mission.offers.length === 0) {
    return <EmptyState title="No offers" detail="Discovery returned nothing for this mission." />;
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
          ? "border-[color:var(--color-accent)]/50 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--color-accent)_10%,transparent),color-mix(in_srgb,var(--color-accent-2)_8%,transparent))]"
          : "border-[color:var(--color-line)] bg-[color:var(--color-surface)]",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {selected ? <Badge tone="accent">SELECTED</Badge> : null}
          <TaintedText value={offer.title} label="Product title" />
        </div>
        <Authoritative className="text-[14px] font-semibold whitespace-nowrap">
          {inr(offer.amount_inr)} {offer.currency}
        </Authoritative>
      </div>

      <KeyValueGrid columns={3} className="mt-2.5">
        <KeyValue label="Registered Payee (Authoritative)">
          <Authoritative>{offer.merchant_id}</Authoritative>
        </KeyValue>
        <KeyValue label="Merchant display name">
          <TaintedText value={offer.merchant_name} label="Display name" />
        </KeyValue>
        <KeyValue label="Offer version">
          <Authoritative className="truncate text-[11px]">{offer.offer_version}</Authoritative>
        </KeyValue>
      </KeyValueGrid>
    </li>
  );
}
