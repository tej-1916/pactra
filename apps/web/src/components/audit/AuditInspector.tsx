"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { AuditChain } from "@/components/audit/AuditChain";
import { ReplayPanel } from "@/components/audit/ReplayPanel";
import { VerificationPanel } from "@/components/audit/VerificationPanel";
import { DataTierBadge } from "@/components/ui/DataTier";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, LoadingSkeleton, UnavailableState } from "@/components/ui/States";
import { MissionStateBadge, VerificationBadge } from "@/components/ui/StatusBadges";
import { api } from "@/lib/api/client";
import { cn, count, relativeTime, shortId } from "@/lib/format";
import { useKeyedLoad } from "@/lib/hooks/useKeyedLoad";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";
import type { AuditEvent, AuditVerification, Mission, MissionReplay } from "@/lib/types/pactra";

interface Loaded {
  mission: Mission | null;
  events: AuditEvent[] | null;
  verification: AuditVerification | null;
  replay: MissionReplay | null;
  unavailable: boolean;
}

/**
 * Chain inspection for any mission this browser knows about.
 *
 * Verification and replay are both read-only server-side, so opening a mission
 * here changes nothing about it — no event is appended and no row is touched.
 * That property is what makes an audit console safe to leave open.
 */
export function AuditInspector() {
  const { missions, hydrated } = useMissionRegister();
  const [chosen, setChosen] = useState<string | null>(null);

  // Derived, not written into state by an effect: "the first mission, unless
  // the operator picked another" is a computation.
  const selected = chosen ?? missions[0]?.id ?? null;

  const load = useCallback(async (missionId: string): Promise<Loaded> => {
    const [mission, events, verification, replay] = await Promise.all([
      api.getMission(missionId),
      api.getEvents(missionId),
      api.verifyAudit(missionId),
      api.replay(missionId),
    ]);
    return {
      mission: mission.kind === "ok" ? mission.data : null,
      events: events.kind === "ok" ? events.data : null,
      verification: verification.kind === "ok" ? verification.data : null,
      replay: replay.kind === "ok" ? replay.data : null,
      unavailable: [mission, events, verification, replay].some((r) => r.kind === "unavailable"),
    };
  }, []);

  const { loading, value: data } = useKeyedLoad(selected, load);

  if (!hydrated) return <LoadingSkeleton rows={4} />;

  if (missions.length === 0) {
    return (
      <EmptyState
        title="No mission to inspect"
        detail={
          <>
            The audit ledger is mission-scoped: there is no cross-mission chain and no global event
            feed, which is also why tail truncation is undetectable (KL-01). Run a mission from the{" "}
            <Link href="/missions" className="text-[color:var(--color-accent)] hover:underline">
              Mission Workbench
            </Link>{" "}
            to inspect one.
          </>
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      <Panel title="Select a mission" actions={<DataTierBadge tier="live" />} flush>
        <ul className="max-h-[220px] divide-y divide-[color:var(--color-line)]/60 overflow-y-auto">
          {missions.map((entry) => (
            <li key={entry.id}>
              <button
                type="button"
                onClick={() => setChosen(entry.id)}
                aria-current={selected === entry.id ? "true" : undefined}
                className={cn(
                  "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors",
                  selected === entry.id
                    ? "bg-[color:var(--color-accent)]/[0.07]"
                    : "hover:bg-[color:var(--color-surface-2)]",
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate text-[12px] text-[color:var(--color-ink)]">
                    {entry.rawQuery ?? "(no raw query)"}
                  </span>
                  <span className="num block text-[10.5px] text-[color:var(--color-ink-4)]">
                    {shortId(entry.id, 10)} · {relativeTime(entry.createdAt)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Panel>

      {selected === null ? null : loading || data === null ? (
        <LoadingSkeleton rows={6} />
      ) : data.unavailable ? (
        <UnavailableState
          title="PACTRA API unavailable"
          detail="The chain for this mission cannot be read. That is a connection fact, not a verification result — an unreadable chain is never reported as a valid one."
        />
      ) : (
        <>
          {data.mission ? (
            <Panel
              title="Mission"
              actions={
                <div className="flex items-center gap-2">
                  <MissionStateBadge state={data.mission.state} />
                  {data.verification ? (
                    <VerificationBadge valid={data.verification.valid} />
                  ) : null}
                </div>
              }
            >
              <p className="text-[12.5px] text-[color:var(--color-ink-2)]">
                {data.mission.raw_query ?? "(no raw query)"}
              </p>
              <p className="num mt-1 text-[11px] text-[color:var(--color-ink-4)]">
                {data.mission.id} · {count(data.events?.length ?? 0)} events
              </p>
            </Panel>
          ) : null}

          {data.verification ? <VerificationPanel verification={data.verification} /> : null}

          <Panel
            title="Hash chain"
            subtitle="Append-only. Each event's previous_hash must equal the event_hash of the one before it; expand a row to read the payload the hash covers."
            flush
          >
            {data.events && data.events.length > 0 ? (
              <AuditChain
                events={data.events}
                highlightSequence={data.verification?.first_invalid_sequence ?? null}
              />
            ) : (
              <div className="p-4">
                <EmptyState title="No events" detail="This mission has no audit events." />
              </div>
            )}
          </Panel>

          {data.replay ? <ReplayPanel replay={data.replay} /> : null}
        </>
      )}
    </div>
  );
}
