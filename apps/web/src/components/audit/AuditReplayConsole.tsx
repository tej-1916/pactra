"use client";

import { useState } from "react";
import { AUDIT_DEMO_SCENARIOS } from "./auditScenarios";
import { SourceSelector, type AuditSourceMode } from "./SourceSelector";
import { TraceTimeline } from "./TraceTimeline";
import { EventInspector, type ReplayedAuthEvidence } from "./EventInspector";
import { ReplayControls } from "./ReplayControls";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { ALL_ROUTES } from "@/components/shell/nav";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";
import { useReplay } from "@/lib/hooks/queries";
import type { DecisionTraceEntry } from "@/lib/types/pactra";

export function AuditReplayConsole() {
  const [mode, setMode] = useState<AuditSourceMode>("DEMO");
  const [selectedDemoScenarioId, setSelectedDemoScenarioId] = useState<string>("BENIGN_PURCHASE");
  const [selectedEventIndex, setSelectedEventIndex] = useState<number>(0);

  const { missions } = useMissionRegister();
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(
    missions[0]?.id ?? null
  );

  const replayQuery = useReplay(mode === "RUNTIME" ? selectedMissionId : null);

  const blurb = ALL_ROUTES.find((item) => item.href === "/audit")?.blurb;

  // Active scenario & entries calculation
  const demoScenario =
    AUDIT_DEMO_SCENARIOS[selectedDemoScenarioId] ||
    AUDIT_DEMO_SCENARIOS.BENIGN_PURCHASE || {
      id: "BENIGN_PURCHASE",
      name: "1. Benign Autonomous Purchase",
      category: "STANDARD" as const,
      description: "",
      provenance: {
        origin: "AI Buyer Assistant",
        trustClassification: "UNTRUSTED",
        authorityPath: "POLICY_AUTO",
      },
      decisionTrace: [],
    };

  let traceEntries: DecisionTraceEntry[] = [];
  let provenance = demoScenario.provenance;
  let runtimeStatus: "none" | "pending" | "unavailable" | "loaded" = "none";
  let runtimeVerification: {
    auditValid: boolean;
    trusted: boolean;
    reasonCode: string;
    eventsReplayed: number;
    unsupportedEvents?: unknown[];
  } | null = null;
  let replayedAuth: ReplayedAuthEvidence | null = null;

  if (mode === "DEMO") {
    traceEntries = demoScenario.decisionTrace;
    provenance = demoScenario.provenance;
  } else {
    if (!selectedMissionId) {
      runtimeStatus = "none";
    } else if (replayQuery.isPending) {
      runtimeStatus = "pending";
    } else if (replayQuery.data && replayQuery.data.kind === "ok") {
      runtimeStatus = "loaded";
      const replayData = replayQuery.data.data;
      traceEntries = replayData.decision_trace ?? [];
      provenance = {
        origin: `Mission ${selectedMissionId}`,
        trustClassification: "RUNTIME AUDIT LOG",
        authorityPath: "Runtime Decision Trace Projection",
      };
      runtimeVerification = {
        auditValid: replayData.audit_valid,
        trusted: replayData.trusted,
        reasonCode: replayData.reason_code,
        eventsReplayed: replayData.events_replayed,
        unsupportedEvents: replayData.unsupported_events,
      };
      if (replayData.state?.authorization) {
        replayedAuth = {
          authorizationId: replayData.state.authorization.authorization_id,
          transactionDigestPrefix: replayData.state.authorization.transaction_digest_prefix,
          bindingVersion: replayData.state.authorization.binding_version,
        };
      }
    } else {
      runtimeStatus = "unavailable";
    }
  }

  const activeEntry = traceEntries[selectedEventIndex] ?? traceEntries[0] ?? null;

  return (
    <PageContainer variant="wide">
      <div className="space-y-6">
        <PageHeader
          eyebrow="AUDIT & REPLAY"
          title="Inspect deterministic transaction evidence"
          description={
            blurb ??
            "Complete chronological audit evidence and replay inspection across ADMIT, BIND, and EXECUTE stages."
          }
          actions={
            mode === "DEMO" ? (
              <Badge tone="accent" variant="outline">
                DEMO HARNESS
              </Badge>
            ) : (
              <Badge tone="secure" variant="outline">
                RUNTIME REPLAY
              </Badge>
            )
          }
        />

        {/* Source & Mission Selector */}
        <SourceSelector
          mode={mode}
          onSelectMode={(m) => {
            setMode(m);
            setSelectedEventIndex(0);
          }}
          selectedDemoScenarioId={selectedDemoScenarioId}
          onSelectDemoScenario={(id) => {
            setSelectedDemoScenarioId(id);
            setSelectedEventIndex(0);
          }}
          missions={missions}
          selectedMissionId={selectedMissionId}
          onSelectMission={(id) => {
            setSelectedMissionId(id);
            setSelectedEventIndex(0);
          }}
          runtimeStatus={runtimeStatus}
        />

        {/* Main 2-Column Grid: Timeline on Left, Inspector on Right */}
        <div className="grid gap-6 lg:grid-cols-[1.1fr_1.3fr] items-start">
          <TraceTimeline
            entries={traceEntries}
            selectedIndex={selectedEventIndex}
            onSelectIndex={setSelectedEventIndex}
            isDemo={mode === "DEMO"}
          />

          <EventInspector
            entry={activeEntry}
            isDemo={mode === "DEMO"}
            replayedAuth={replayedAuth}
          />
        </div>

        {/* Replay Controls & Provenance Bar */}
        <ReplayControls
          currentIndex={selectedEventIndex}
          totalEvents={traceEntries.length}
          onPrev={() => setSelectedEventIndex((i) => Math.max(0, i - 1))}
          onNext={() => setSelectedEventIndex((i) => Math.min(traceEntries.length - 1, i + 1))}
          onReset={() => setSelectedEventIndex(0)}
          isDemo={mode === "DEMO"}
          runtimeVerification={runtimeVerification}
          provenance={provenance}
        />
      </div>
    </PageContainer>
  );
}
