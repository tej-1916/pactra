"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, Info } from "lucide-react";

import { Panel } from "@/components/ui/Panel";
import { EmptyState, LoadingSkeleton, UnavailableState } from "@/components/ui/States";
import { MissionStateBadge, PolicyDecisionBadge } from "@/components/ui/StatusBadges";
import { api } from "@/lib/api/client";
import { inr, relativeTime, shortId } from "@/lib/format";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";
import type { Mission } from "@/lib/types/pactra";

type Row =
  | { id: string; kind: "loading" }
  | { id: string; kind: "ok"; mission: Mission }
  | { id: string; kind: "gone"; detail: string }
  | { id: string; kind: "unavailable"; detail: string };

/**
 * Missions created from THIS browser.
 *
 * PACTRA has no mission-list endpoint — every mission route is
 * `/{mission_id}`-scoped — so there is no honest way to enumerate what the
 * system holds, and no endpoint was invented to provide one. What the console
 * can honestly show is what it created itself, re-read live from the API. The
 * heading says exactly that, because a browser-local list presented as a system
 * inventory would be a fabricated one.
 */
export function RecentMissions({ limit = 6 }: { limit?: number }) {
  const { missions, hydrated } = useMissionRegister();
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    if (!hydrated) return;
    const wanted = missions.slice(0, limit);
    if (wanted.length === 0) return;

    let cancelled = false;
    void (async () => {
      const resolved = await Promise.all(
        wanted.map(async (entry): Promise<Row> => {
          const result = await api.getMission(entry.id);
          if (result.kind === "ok") return { id: entry.id, kind: "ok", mission: result.data };
          if (result.kind === "unavailable")
            return { id: entry.id, kind: "unavailable", detail: result.detail };
          return { id: entry.id, kind: "gone", detail: result.detail };
        }),
      );
      if (!cancelled) setRows(resolved);
    })();

    return () => {
      cancelled = true;
    };
  }, [hydrated, missions, limit]);

  // Rows the register knows about but that have not resolved yet render as
  // loading. Derived rather than written into state on every key change, so no
  // synchronous reset is needed and a stale response cannot land under the
  // wrong heading.
  const resolvedById = new Map(rows.map((row) => [row.id, row]));
  const displayRows: Row[] = missions
    .slice(0, limit)
    .map((entry) => resolvedById.get(entry.id) ?? { id: entry.id, kind: "loading" as const });

  const anyUnavailable = displayRows.some((row) => row.kind === "unavailable");

  return (
    <Panel
      title="Missions from this browser"
      subtitle={
        <span className="flex items-start gap-1.5">
          <Info aria-hidden className="mt-[2px] size-3.5 shrink-0" />
          PACTRA exposes no mission-list endpoint, so this is a browser-local record of missions
          this console created — not a system inventory. Each row is re-read live from the API.
        </span>
      }
      actions={
        <Link
          href="/missions"
          className="inline-flex items-center gap-1 rounded border border-[color:var(--color-line-strong)] px-2 py-1 text-[11.5px] font-medium text-[color:var(--color-ink-2)] hover:text-[color:var(--color-ink)]"
        >
          Mission Workbench
          <ArrowUpRight aria-hidden className="size-3" />
        </Link>
      }
      flush
    >
      {!hydrated ? (
        <div className="p-4">
          <LoadingSkeleton rows={2} />
        </div>
      ) : missions.length === 0 ? (
        <div className="p-4">
          <EmptyState
            title="No missions yet"
            detail={
              <>
                Run one from the Mission Workbench. It executes the real kernel path — discovery,
                normalization, provenance, policy, binding — and every stage becomes inspectable.
              </>
            }
            action={
              <Link
                href="/missions"
                className="mt-1 inline-flex items-center gap-1 rounded border border-[color:var(--color-accent)]/40 bg-[color:var(--color-accent)]/10 px-2.5 py-1 text-[11.5px] font-semibold text-[color:var(--color-accent)]"
              >
                Open the workbench
                <ArrowUpRight aria-hidden className="size-3" />
              </Link>
            }
          />
        </div>
      ) : anyUnavailable ? (
        <div className="p-4">
          <UnavailableState
            title="PACTRA API unavailable"
            detail="These missions exist in this browser's register, but their current state cannot be read. This is not the same as there being no missions — nothing is being shown as zero."
          />
        </div>
      ) : (
        <ul className="divide-y divide-[color:var(--color-line)]/60">
          {displayRows.map((row) => (
            <li key={row.id}>
              <MissionRow row={row} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function MissionRow({ row }: { row: Row }) {
  if (row.kind === "loading") {
    return (
      <div className="px-4 py-3">
        <LoadingSkeleton rows={1} />
      </div>
    );
  }
  if (row.kind === "gone" || row.kind === "unavailable") {
    return (
      <div className="flex items-center gap-3 px-4 py-3">
        <code className="num text-[11.5px] text-[color:var(--color-ink-4)]">{shortId(row.id, 12)}</code>
        <span className="text-[11.5px] text-[color:var(--color-ink-4)]">{row.detail}</span>
      </div>
    );
  }

  const mission = row.mission;
  const selected = mission.offers.find((offer) => offer.offer_id === mission.policy_decision?.selected_offer_id);

  return (
    <Link
      href={`/missions/${mission.id}`}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 transition-colors hover:bg-[color:var(--color-surface-2)]"
    >
      <div className="min-w-[220px] flex-1">
        <p className="truncate text-[12.5px] text-[color:var(--color-ink)]">
          {mission.raw_query ?? <span className="text-[color:var(--color-ink-4)]">(no raw query)</span>}
        </p>
        <p className="num mt-0.5 text-[11px] text-[color:var(--color-ink-4)]">
          {shortId(mission.id, 8)} · {relativeTime(mission.created_at)} · {mission.offers.length} offers
        </p>
      </div>
      {selected ? (
        <span className="num text-[12px] text-[color:var(--color-ink-2)]">{inr(selected.amount_inr)}</span>
      ) : null}
      {mission.policy_decision ? (
        <PolicyDecisionBadge decision={mission.policy_decision.decision} />
      ) : null}
      <MissionStateBadge state={mission.state} />
    </Link>
  );
}
