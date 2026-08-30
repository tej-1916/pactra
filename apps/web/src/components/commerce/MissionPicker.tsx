"use client";

import Link from "next/link";
import { useState } from "react";
import { Search } from "lucide-react";

import { TaintedText } from "@/components/ui/Provenance";
import { cn, relativeTime, shortId } from "@/lib/format";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";

/**
 * Choosing which mission to read.
 *
 * PACTRA exposes no mission-list endpoint — every mission route is
 * `/{mission_id}`-scoped — so there is no honest way to enumerate what the
 * system holds. The picker therefore offers exactly two truthful sources: the
 * browser's own record of missions IT created, labelled as such, and a mission
 * ID typed in by hand. It never presents either as a system inventory.
 */
export function MissionPicker({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (missionId: string) => void;
}) {
  const { missions, hydrated } = useMissionRegister();
  const [typed, setTyped] = useState("");

  return (
    <div className="space-y-3">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const value = typed.trim();
          if (value.length > 0) onSelect(value);
        }}
        className="flex flex-wrap items-center gap-2"
      >
        <label htmlFor="mission-id" className="label-xs text-[color:var(--color-ink-4)]">
          Mission ID
        </label>
        <input
          id="mission-id"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder="00000000-0000-0000-0000-000000000000"
          spellCheck={false}
          className="num min-w-0 flex-1 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-2.5 py-1.5 text-[12px] text-[color:var(--color-ink)] placeholder:text-[color:var(--color-ink-4)]"
        />
        <button
          type="submit"
          className="gradient-authority inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-[12px] font-semibold text-[color:var(--color-surface)]"
        >
          <Search aria-hidden className="size-3.5" />
          Read
        </button>
      </form>

      <div>
        <p className="label-xs text-[color:var(--color-ink-4)]">
          Missions created from this browser
        </p>
        {!hydrated ? (
          <p className="mt-1.5 text-[11.5px] text-[color:var(--color-ink-4)]">Reading local record…</p>
        ) : missions.length === 0 ? (
          <p className="mt-1.5 max-w-[80ch] text-[11.5px] leading-relaxed text-[color:var(--color-ink-4)]">
            None yet. This list is a browser-local record of what THIS browser created — not an
            inventory of what PACTRA holds, because no endpoint exposes one. Run a mission from the{" "}
            <Link
              href="/missions"
              className="text-[color:var(--color-accent)] underline underline-offset-2"
            >
              mission workbench
            </Link>
            , or paste a mission ID above.
          </p>
        ) : (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {missions.slice(0, 8).map((mission) => (
              <li key={mission.id}>
                <button
                  type="button"
                  onClick={() => onSelect(mission.id)}
                  aria-pressed={selected === mission.id}
                  className={cn(
                    "flex max-w-[280px] items-center gap-2 rounded border px-2.5 py-1.5 text-left transition-colors",
                    selected === mission.id
                      ? "border-[color:var(--color-accent)]/50 bg-[color:var(--color-accent)]/[0.10]"
                      : "border-[color:var(--color-line)] hover:bg-[color:var(--color-surface-2)]",
                  )}
                >
                  <span className="num shrink-0 text-[11px] text-[color:var(--color-ink)]">
                    {shortId(mission.id)}
                  </span>
                  <TaintedText value={mission.rawQuery} label="Query" showMarker={false} />
                  <span className="num shrink-0 text-[10px] text-[color:var(--color-ink-4)]">
                    {relativeTime(mission.createdAt)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
