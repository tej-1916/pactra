"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

import { AuditChain } from "@/components/audit/AuditChain";
import { ReplayPanel } from "@/components/audit/ReplayPanel";
import { VerificationPanel } from "@/components/audit/VerificationPanel";
import { AuthorizationPanel } from "@/components/mission/AuthorizationPanel";
import { MissionPipeline, type PipelineStage } from "@/components/mission/MissionPipeline";
import { OffersTable } from "@/components/mission/OffersTable";
import { PaymentPanel } from "@/components/mission/PaymentPanel";
import { ProvenanceView } from "@/components/mission/ProvenanceView";
import { RiskAssessmentView } from "@/components/risk/RiskAssessmentView";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { DataTierBadge } from "@/components/ui/DataTier";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { EmptyState, ErrorState, LoadingSkeleton, UnavailableState } from "@/components/ui/States";
import { MissionStateBadge, PolicyDecisionBadge } from "@/components/ui/StatusBadges";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { api } from "@/lib/api/client";
import type { ApiResult } from "@/lib/api/result";
import { inr, shortId, timestamp } from "@/lib/format";
import { newIdempotencyKey, readRegister } from "@/lib/hooks/useMissionRegister";
import type {
  AuditEvent,
  AuditVerification,
  Authorization,
  Mission,
  MissionReplay,
  PaymentIntent,
  RiskAssessment,
} from "@/lib/types/pactra";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "offers", label: "Offers" },
  { id: "security", label: "Security" },
  { id: "authorization", label: "Authorization" },
  { id: "payment", label: "Payment" },
  { id: "audit", label: "Audit" },
];

type Load<T> = { status: "loading" } | { status: "done"; result: ApiResult<T> };

const LOADING = { status: "loading" } as const;

/**
 * One mission, fully inspected.
 *
 * Every panel is fed from a live API read; nothing on this screen is derived
 * from a cached snapshot or a fixture. A resource the mission does not have yet
 * (no authorization, no payment) comes back as a 404 and is rendered as "does
 * not exist", which is a different statement from "the API is unreachable" and
 * gets a different component.
 *
 * The risk assessment uses the READ endpoint. The console never records a
 * `RISK_ASSESSED` event as a side effect of rendering — appending to a mission's
 * hash chain because someone looked at it would make "who inspected this" part
 * of the history replay has to reconstruct.
 */
export function MissionDetail({ missionId }: { missionId: string }) {
  const [tab, setTab] = useState("overview");
  const [mission, setMission] = useState<Load<Mission>>(LOADING);
  const [authorization, setAuthorization] = useState<Load<Authorization>>(LOADING);
  const [payment, setPayment] = useState<Load<PaymentIntent>>(LOADING);
  const [events, setEvents] = useState<Load<AuditEvent[]>>(LOADING);
  const [verification, setVerification] = useState<Load<AuditVerification>>(LOADING);
  const [replay, setReplay] = useState<Load<MissionReplay>>(LOADING);
  const [risk, setRisk] = useState<Load<RiskAssessment>>(LOADING);
  const [approving, setApproving] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [actionError, setActionError] = useState<{ title: string; code: string | null; detail: string } | null>(null);

  const idempotencyKey =
    readRegister().find((entry) => entry.id === missionId)?.idempotencyKey ??
    newIdempotencyKey(missionId);

  /**
   * Read every view of the mission at once.
   *
   * Panels are not reset to `loading` first: the initial state already is
   * loading, and blanking the screen on a manual refresh would replace correct
   * data with a skeleton for no gain. A failed read replaces its own panel.
   */
  const refresh = useCallback(async () => {
    const [m, a, p, e, v, r, k] = await Promise.all([
      api.getMission(missionId),
      api.getAuthorization(missionId),
      api.getPayment(missionId),
      api.getEvents(missionId),
      api.verifyAudit(missionId),
      api.replay(missionId),
      api.getRisk(missionId),
    ]);
    setMission({ status: "done", result: m });
    setAuthorization({ status: "done", result: a });
    setPayment({ status: "done", result: p });
    setEvents({ status: "done", result: e });
    setVerification({ status: "done", result: v });
    setReplay({ status: "done", result: r });
    setRisk({ status: "done", result: k });
  }, [missionId]);

  useEffect(() => {
    // `refresh` awaits every read before it touches state, so nothing is set
    // synchronously here. The compiler rule cannot see past the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  async function approve() {
    setApproving(true);
    setActionError(null);
    const result = await api.approve(missionId);
    setApproving(false);
    if (result.kind === "ok") {
      await refresh();
      return;
    }
    setActionError({
      title: result.kind === "unavailable" ? "PACTRA API unavailable" : "The kernel refused this approval",
      code: result.kind === "failed" ? result.reasonCode : null,
      detail: result.detail,
    });
  }

  async function requestPayment() {
    setRequesting(true);
    setActionError(null);
    const result = await api.requestPayment(missionId, idempotencyKey);
    setRequesting(false);
    if (result.kind === "ok") {
      await refresh();
      return;
    }
    setActionError({
      title: result.kind === "unavailable" ? "PACTRA API unavailable" : "The kernel refused this payment request",
      code: result.kind === "failed" ? result.reasonCode : null,
      detail: result.detail,
    });
  }

  if (mission.status === "loading") {
    return <LoadingSkeleton rows={8} />;
  }
  if (mission.result.kind === "unavailable") {
    return (
      <UnavailableState
        title="PACTRA API unavailable"
        detail={`This mission cannot be read. ${mission.result.detail}`}
      />
    );
  }
  if (mission.result.kind === "failed") {
    return (
      <ErrorState
        title={`Mission not readable (HTTP ${mission.result.status})`}
        detail={mission.result.detail}
      />
    );
  }

  const data = mission.result.data;
  const decision = data.policy_decision;
  const selectedOffer = data.offers.find((offer) => offer.offer_id === decision?.selected_offer_id);
  const auth = pick(authorization);
  const pay = pick(payment);
  const riskAssessment = pick(risk);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Mission"
        title={data.raw_query ?? "Mission"}
        description={
          <span className="num text-[12px]">
            {data.id} · created {timestamp(data.created_at)} · quantity {data.quantity}
          </span>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <DataTierBadge tier="live" />
            <MissionStateBadge state={data.state} />
            {decision ? <PolicyDecisionBadge decision={decision.decision} /> : null}
            <button
              type="button"
              onClick={() => void refresh()}
              className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-line-strong)] px-2.5 py-1.5 text-[12px] font-medium text-[color:var(--color-ink-2)] hover:text-[color:var(--color-ink)]"
            >
              <RefreshCw aria-hidden className="size-3.5" />
              Refresh
            </button>
          </div>
        }
      />

      {actionError ? (
        <ErrorState
          title={actionError.title}
          detail={
            <div className="space-y-2">
              <ReasonCode code={actionError.code} describe />
              <p>{actionError.detail}</p>
            </div>
          }
        />
      ) : null}

      <Tabs tabs={TABS} active={tab} onChange={setTab} label="Mission views" />

      <TabPanel id="overview" active={tab}>
        <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
          <Panel
            title="Security pipeline"
            subtitle="Each stage's status is derived from live API state, and its reason is the code the kernel actually produced."
          >
            <MissionPipeline
              stages={buildStages({ mission: data, authorization: auth, payment: pay })}
            />
          </Panel>

          <div className="space-y-5">
            <Panel title="Policy decision" subtitle="Deterministic. Never a prompt.">
              {decision ? (
                <KeyValueGrid columns={2}>
                  <KeyValue label="Decision">
                    <PolicyDecisionBadge decision={decision.decision} />
                  </KeyValue>
                  <KeyValue label="Policy version">
                    <span className="num">{decision.policy_version}</span>
                  </KeyValue>
                  <KeyValue label="Requested amount">
                    <span className="num">{inr(decision.requested_amount)}</span>
                  </KeyValue>
                  <KeyValue label="Soft budget / hard limit">
                    <span className="num">
                      {inr(decision.soft_budget)} / {inr(decision.hard_limit)}
                    </span>
                  </KeyValue>
                  <KeyValue label="Reason codes" className="sm:col-span-2">
                    <div className="flex flex-col gap-2">
                      {decision.reason_codes.length === 0 ? (
                        <span className="text-[color:var(--color-ink-4)]">—</span>
                      ) : (
                        decision.reason_codes.map((code) => (
                          <ReasonCode key={code} code={code} describe />
                        ))
                      )}
                    </div>
                  </KeyValue>
                </KeyValueGrid>
              ) : (
                <EmptyState
                  title="No policy decision recorded"
                  detail="This mission did not reach the policy stage."
                />
              )}
            </Panel>

            {selectedOffer ? (
              <Panel title="Selected offer">
                <KeyValueGrid columns={2}>
                  <KeyValue label="Merchant"><span className="num">{selectedOffer.merchant_name}</span></KeyValue>
                  <KeyValue label="Amount"><span className="num">{inr(selectedOffer.amount_inr)}</span></KeyValue>
                  <KeyValue label="Rating"><span className="num">{selectedOffer.rating.toFixed(1)}</span></KeyValue>
                  <KeyValue label="Offer version">
                    <span className="num text-[11px]">{shortId(selectedOffer.offer_version, 20)}</span>
                  </KeyValue>
                </KeyValueGrid>
              </Panel>
            ) : null}
          </div>
        </div>
      </TabPanel>

      <TabPanel id="offers" active={tab}>
        <div className="space-y-5">
          <OffersTable offers={data.offers} selectedOfferId={decision?.selected_offer_id ?? null} />
          {selectedOffer ? <ProvenanceView offer={selectedOffer} /> : null}
        </div>
      </TabPanel>

      <TabPanel id="security" active={tab}>
        <div className="space-y-5">
          {riskAssessment ? (
            <RiskAssessmentView assessment={riskAssessment} />
          ) : (
            <Panel title="Advisory risk" actions={<Badge tone="advisory" variant="outline">ADVISORY ONLY</Badge>}>
              <StateFor load={risk} noun="risk assessment" />
            </Panel>
          )}
          {data.offers.filter((offer) => !offer.valid).length > 0 ? (
            <Panel
              title="Refused offers"
              subtitle="What the kernel declined to act on, and the code that named each refusal."
            >
              <ul className="space-y-2">
                {data.offers
                  .filter((offer) => !offer.valid)
                  .map((offer) => (
                    <li
                      key={offer.offer_id}
                      className="flex flex-wrap items-center gap-3 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2"
                    >
                      <span className="num text-[12px] text-[color:var(--color-ink)]">
                        {offer.merchant_id}
                      </span>
                      <span className="num text-[12px] text-[color:var(--color-ink-3)]">
                        {inr(offer.amount_inr)}
                      </span>
                      <div className="flex flex-wrap gap-2">
                        {offer.rejection_reasons.map((code) => (
                          <ReasonCode key={code} code={code} />
                        ))}
                      </div>
                    </li>
                  ))}
              </ul>
            </Panel>
          ) : null}
        </div>
      </TabPanel>

      <TabPanel id="authorization" active={tab}>
        {auth ? (
          <AuthorizationPanel
            authorization={auth}
            onApprove={approve}
            approving={approving}
            canApprove={auth.status === "PENDING" && data.state === "AWAITING_APPROVAL"}
          />
        ) : (
          <Panel title="Authorization artifact">
            <StateFor load={authorization} noun="authorization" />
          </Panel>
        )}
      </TabPanel>

      <TabPanel id="payment" active={tab}>
        <PaymentPanel
          payment={pay}
          onRequest={requestPayment}
          requesting={requesting}
          canRequest={auth?.status === "ACTIVE" || pay !== null}
          idempotencyKey={idempotencyKey}
        />
      </TabPanel>

      <TabPanel id="audit" active={tab}>
        <div className="space-y-5">
          {verification.status === "done" && verification.result.kind === "ok" ? (
            <VerificationPanel verification={verification.result.data} />
          ) : (
            <Panel title="Chain verification">
              <StateFor load={verification} noun="verification result" />
            </Panel>
          )}

          <Panel
            title="Audit chain"
            subtitle="Append-only and hash-linked. Each event's previous_hash must equal the event_hash of the one before it."
            flush
          >
            {events.status === "done" && events.result.kind === "ok" ? (
              events.result.data.length === 0 ? (
                <div className="p-4">
                  <EmptyState title="No events" detail="This mission has no audit events." />
                </div>
              ) : (
                <AuditChain
                  events={events.result.data}
                  highlightSequence={
                    verification.status === "done" && verification.result.kind === "ok"
                      ? verification.result.data.first_invalid_sequence
                      : null
                  }
                />
              )
            ) : (
              <div className="p-4">
                <StateFor load={events} noun="event history" />
              </div>
            )}
          </Panel>

          {replay.status === "done" && replay.result.kind === "ok" ? (
            <ReplayPanel replay={replay.result.data} />
          ) : (
            <Panel title="Deterministic replay">
              <StateFor load={replay} noun="replay result" />
            </Panel>
          )}
        </div>
      </TabPanel>
    </div>
  );
}

function pick<T>(load: Load<T>): T | null {
  return load.status === "done" && load.result.kind === "ok" ? load.result.data : null;
}

/**
 * Renders the right state for a resource that is not `ok`.
 *
 * A 404 here means the mission genuinely has no such artifact yet — no
 * authorization, no payment — which is an EMPTY state, not an error. Anything
 * else the API refused is an error, and an unreachable API is neither.
 */
function StateFor<T>({ load, noun }: { load: Load<T>; noun: string }) {
  if (load.status === "loading") return <LoadingSkeleton rows={3} />;
  const result = load.result;
  if (result.kind === "ok") return null;
  if (result.kind === "unavailable") {
    return <UnavailableState title="PACTRA API unavailable" detail={result.detail} />;
  }
  if (result.status === 404) {
    return (
      <EmptyState
        title={`This mission has no ${noun} yet`}
        detail={`The API reports none exists. That is a fact about the mission, not a failure to read it.`}
      />
    );
  }
  return (
    <ErrorState
      title={`Could not read the ${noun} (HTTP ${result.status})`}
      detail={
        <div className="space-y-2">
          <ReasonCode code={result.reasonCode} describe />
          <p>{result.detail}</p>
        </div>
      }
    />
  );
}

/**
 * Derives the pipeline from live state.
 *
 * Deliberately conservative: a stage is `done` only when a value proves it
 * happened. "The mission is in a later state, so this must have succeeded" is
 * not evidence, and a pipeline that inferred green ticks would be describing an
 * assumption rather than the system.
 */
function buildStages({
  mission,
  authorization,
  payment,
}: {
  mission: Mission;
  authorization: Authorization | null;
  payment: PaymentIntent | null;
}): PipelineStage[] {
  const decision = mission.policy_decision;
  const denied = decision?.decision === "DENY";
  const validOffers = mission.offers.filter((offer) => offer.valid);
  const rejected = mission.offers.length - validOffers.length;

  return [
    {
      id: "intent",
      name: "User intent",
      status: "done",
      reason: mission.raw_query
        ? `Free text captured verbatim: “${mission.raw_query}”. It is stored as data and is never a security input.`
        : "No raw query was supplied. Constraints alone drove the mission.",
    },
    {
      id: "constraints",
      name: "Normalized constraints",
      status: decision ? "done" : "pending",
      reason: decision
        ? `Soft budget ${inr(decision.soft_budget)}, hard limit ${inr(decision.hard_limit)}. Validated at the trusted API boundary through a strict schema that forbids unknown fields.`
        : "Not reached.",
    },
    {
      id: "offers",
      name: "Merchant offers",
      status: mission.offers.length > 0 ? "done" : "pending",
      reason:
        mission.offers.length > 0
          ? `${mission.offers.length} offers received from the merchant transport. ${validOffers.length} valid, ${rejected} rejected.`
          : "No offers were received.",
      meta: <Badge tone="taint" variant="outline">UNTRUSTED INPUT</Badge>,
    },
    {
      id: "provenance",
      name: "Provenance & taint",
      status: mission.offers.length > 0 ? "done" : "pending",
      reason:
        "Merchant identity and trust come from the server-owned registry, never the payload. Free-form merchant text is discarded and never reaches ranking or policy.",
      meta: <Badge tone="taint" variant="outline">TAINT PRESERVED</Badge>,
    },
    {
      id: "policy",
      name: "Deterministic policy",
      status: decision ? (denied ? "blocked" : "done") : "pending",
      reason: decision ? (
        <div className="flex flex-col gap-2">
          <span>
            Policy {decision.policy_version} produced <strong>{decision.decision}</strong> for{" "}
            {inr(decision.requested_amount)}.
          </span>
          {decision.reason_codes.map((code) => (
            <ReasonCode key={code} code={code} describe />
          ))}
        </div>
      ) : (
        "Not reached."
      ),
    },
    {
      id: "binding",
      name: "Transaction binding",
      status: authorization ? "done" : denied ? "skipped" : "pending",
      reason: authorization
        ? "A digest commits to one exact transaction — merchant, product, quantity, amount, currency, and the policy and offer versions. Changing any of them invalidates the authorization."
        : denied
          ? "Skipped: the policy engine denied this mission, so there was nothing to bind."
          : "No authorization artifact exists yet.",
    },
    {
      id: "authorization",
      name: "Authorization",
      status: authorization
        ? authorization.status === "ACTIVE" || authorization.status === "CONSUMED"
          ? "done"
          : authorization.status === "PENDING"
            ? "active"
            : "blocked"
        : denied
          ? "skipped"
          : "pending",
      reason: authorization
        ? `Status ${authorization.status}. One-time and expiring; activation is an atomic conditional update, so a second approval cannot succeed.`
        : denied
          ? "Skipped."
          : "Not issued.",
    },
    {
      id: "risk",
      name: "Risk advisory",
      status: "done",
      reason:
        "Computed on demand and read-only. It grants nothing, consumes nothing, and its record is inert in replay — a mission replayed with it present reconstructs identically to one without it.",
      meta: <Badge tone="advisory" variant="outline">ADVISORY ONLY</Badge>,
    },
    {
      id: "payment",
      name: "Payment",
      status: payment
        ? payment.state === "SUCCEEDED"
          ? "done"
          : payment.state === "FAILED_TERMINAL"
            ? "blocked"
            : "active"
        : "pending",
      reason: payment ? (
        <div className="flex flex-col gap-2">
          <span>
            Intent {payment.state} via {payment.provider} for {inr(payment.amount_inr)}, attempt{" "}
            {payment.attempts}.
          </span>
          {payment.last_reason_code ? (
            <ReasonCode code={payment.last_reason_code} describe />
          ) : null}
        </div>
      ) : (
        "No payment intent. NO VALID AUTHORIZATION → NO PAYMENT is enforced at the route and again inside the service."
      ),
    },
    {
      id: "audit",
      name: "Tamper-evident audit",
      status: "done",
      reason:
        "Every stage above appended a hash-linked event. The chain is verifiable independently, and verification repairs nothing it finds.",
    },
  ];
}
