"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { FileCheck2, Loader2 } from "lucide-react";

import { RiskAssessmentView } from "@/components/risk/RiskAssessmentView";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { EmptyState, ErrorState, LoadingSkeleton, UnavailableState } from "@/components/ui/States";
import { api } from "@/lib/api/client";
import type { ApiResult } from "@/lib/api/result";
import { cn, relativeTime, shortId } from "@/lib/format";
import { useKeyedLoad } from "@/lib/hooks/useKeyedLoad";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";
import type { RiskAssessment } from "@/lib/types/pactra";

/**
 * Live advisory scoring for a mission.
 *
 * The default action is the READ endpoint, which writes nothing. Recording a
 * `RISK_ASSESSED` event is offered as a separate, explicit button because it is
 * a separate act: it appends to the mission's hash chain, and a console that did
 * that on every render would make "how many times was this mission looked at"
 * part of the history replay has to reconstruct.
 *
 * Recording is also deliberately not idempotent on the backend — two assessments
 * at two moments are two facts — so the button says it creates an event.
 */
export function RiskExplorer() {
  const { missions, hydrated } = useMissionRegister();
  const [chosen, setChosen] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [override, setOverride] = useState<{ id: string; result: ApiResult<RiskAssessment>; recorded: string } | null>(
    null,
  );

  // The default selection is DERIVED rather than written into state by an
  // effect: "the first mission, unless the operator picked another" is a
  // computation, and storing it would mean a render whose only purpose is to
  // correct the previous one.
  const selected = chosen ?? missions[0]?.id ?? null;

  const load = useCallback((missionId: string) => api.getRisk(missionId), []);
  const { loading, value } = useKeyedLoad(selected, load);

  // A recorded assessment replaces the read for the mission it belongs to, so
  // the panel shows what was actually written rather than a pre-write snapshot.
  const state = override && override.id === selected ? override.result : value;
  const recorded = override && override.id === selected ? override.recorded : null;

  async function record() {
    if (selected === null) return;
    setRecording(true);
    const result = await api.recordRisk(selected);
    setRecording(false);
    if (result.kind === "ok") {
      setOverride({ id: selected, result, recorded: result.data.assessment_id });
    }
  }

  if (!hydrated) return <LoadingSkeleton rows={4} />;

  if (missions.length === 0) {
    return (
      <EmptyState
        title="No mission to assess"
        detail={
          <>
            The risk engine is mission-scoped and is not in the automatic mission path (RL-05) — it
            is invoked deliberately. Run a mission from the{" "}
            <Link href="/missions" className="text-[color:var(--color-accent)] hover:underline">
              Mission Workbench
            </Link>{" "}
            first.
          </>
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      <Panel
        title="Select a mission"
        subtitle="Scoring is read-only. Nothing is written unless you record the assessment explicitly."
        actions={
          selected ? (
            <button
              type="button"
              onClick={record}
              disabled={recording}
              className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-advisory)]/45 bg-[color:var(--color-advisory)]/12 px-3 py-1.5 text-[12px] font-semibold text-[color:var(--color-advisory)] transition-colors hover:bg-[color:var(--color-advisory)]/20 disabled:opacity-50"
              title="Appends one RISK_ASSESSED event to this mission's audit chain. Deliberately not idempotent — two assessments at two moments are two facts."
            >
              {recording ? (
                <Loader2 aria-hidden className="size-3.5 animate-spin" />
              ) : (
                <FileCheck2 aria-hidden className="size-3.5" />
              )}
              Record assessment to the ledger
            </button>
          ) : null
        }
        flush
      >
        <ul className="max-h-[200px] divide-y divide-[color:var(--color-line)]/60 overflow-y-auto">
          {missions.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                onClick={() => setChosen(entry.id)}
                aria-current={selected === entry.id ? "true" : undefined}
                className={cn(
                  "w-full px-4 py-2.5 text-left transition-colors",
                  selected === entry.id
                    ? "bg-[color:var(--color-accent)]/[0.07]"
                    : "hover:bg-[color:var(--color-surface-2)]",
                )}
              >
                <span className="block truncate text-[12px] text-[color:var(--color-ink)]">
                  {entry.rawQuery ?? "(no raw query)"}
                </span>
                <span className="num block text-[10.5px] text-[color:var(--color-ink-4)]">
                  {shortId(entry.id, 10)} · {relativeTime(entry.createdAt)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      {recorded ? (
        <p className="rounded border border-[color:var(--color-secure)]/30 bg-[color:var(--color-secure)]/[0.06] px-3.5 py-2.5 text-[11.5px] text-[color:var(--color-ink-2)]">
          A <code className="num">RISK_ASSESSED</code> event was appended (assessment{" "}
          <code className="num">{shortId(recorded, 8)}</code>). It grants nothing and is inert in
          replay — the mission reconstructs identically with or without it.
        </p>
      ) : null}

      {loading || state === null ? (
        <LoadingSkeleton rows={5} />
      ) : state.kind === "unavailable" ? (
        <UnavailableState title="PACTRA API unavailable" detail={state.detail} />
      ) : state.kind === "failed" ? (
        <ErrorState
          title={`Could not score this mission (HTTP ${state.status})`}
          detail={
            <div className="space-y-2">
              <ReasonCode code={state.reasonCode} describe />
              <p>{state.detail}</p>
            </div>
          }
        />
      ) : (
        <RiskAssessmentView assessment={state.data} />
      )}
    </div>
  );
}
