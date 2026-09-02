import { useState } from "react";
import { ListFilter, Clock } from "lucide-react";
import type { DecisionTraceEntry } from "@/lib/types/pactra";

export interface TraceTimelineProps {
  entries: DecisionTraceEntry[];
  selectedIndex: number;
  onSelectIndex: (index: number) => void;
  isDemo: boolean;
}

export function TraceTimeline({
  entries,
  selectedIndex,
  onSelectIndex,
  isDemo,
}: TraceTimelineProps) {
  const [filterStage, setFilterStage] = useState<string>("ALL");

  const filtered = entries.filter((e) => {
    if (filterStage === "ALL") return true;
    return e.stage === filterStage;
  });

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-4 min-w-0 max-w-full">
      {/* Header & Filters */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--pactra-line)] pb-3">
        <div className="flex items-center gap-2">
          <Clock className="size-4 text-[color:var(--pactra-indigo)]" />
          <h3 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            DECISION TRACE TIMELINE
          </h3>
          <span className="font-mono text-[11px] text-[color:var(--pactra-ink-muted)]">
            ({entries.length} events)
          </span>
        </div>

        {/* Filter Chips */}
        <div className="flex items-center gap-1 font-mono text-[10.5px]">
          <ListFilter className="size-3 text-[color:var(--pactra-ink-muted)] mr-1" />
          {["ALL", "ADMIT", "BIND", "EXECUTE"].map((stg) => (
            <button
              key={stg}
              type="button"
              onClick={() => setFilterStage(stg)}
              className={`rounded px-2 py-0.5 transition-colors cursor-pointer ${
                filterStage === stg
                  ? "bg-[color:var(--pactra-indigo)]/15 text-[color:var(--pactra-indigo)] font-bold border border-[color:var(--pactra-indigo)]/40"
                  : "bg-transparent text-[color:var(--pactra-ink-muted)] hover:text-[color:var(--pactra-ink)]"
              }`}
            >
              {stg}
            </button>
          ))}
        </div>
      </div>

      {/* Events List */}
      <div className="space-y-2 max-h-[520px] overflow-y-auto pr-1">
        {filtered.length === 0 ? (
          <div className="p-4 text-center font-mono text-[12px] text-[color:var(--pactra-ink-muted)]">
            No trace events match the selected stage filter.
          </div>
        ) : (
          filtered.map((entry) => {
            const rawIndex = entries.findIndex(
              (e) => e.evidence.event_id === entry.evidence.event_id
            );
            const isSelected = rawIndex === selectedIndex;

            return (
              <button
                key={entry.evidence.event_id}
                type="button"
                onClick={() => onSelectIndex(rawIndex)}
                className={`w-full text-left rounded-md border p-3 font-mono transition-all cursor-pointer ${
                  isSelected
                    ? "border-[color:var(--pactra-indigo)] bg-[color:var(--pactra-surface-3)] shadow-sm"
                    : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] hover:border-[color:var(--pactra-line-strong)]"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-1 text-[11px] pb-1.5 border-b border-[color:var(--pactra-line)]">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/15 px-1.5 py-0.5 rounded text-[10px]">
                      SEQ {entry.evidence.sequence}
                    </span>
                    <span className="font-bold text-[color:var(--pactra-indigo)]">
                      {entry.stage}
                    </span>
                    <span className="text-[color:var(--pactra-ink)] font-semibold">
                      {entry.event_type}
                    </span>
                  </div>
                  <div className="text-[10px] text-[color:var(--pactra-ink-muted)]">
                    {entry.recorded_at} {isDemo ? "(SYNTHETIC DEMO TRACE)" : ""}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between pt-1.5 text-[10.5px] gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[color:var(--pactra-ink-muted)]">verdict:</span>
                    <span
                      className={
                        entry.verdict === "ACCEPTED" || entry.verdict === "SUCCEEDED"
                          ? "text-[color:var(--pactra-success)] font-bold"
                          : entry.verdict === "REFUSED" || entry.verdict === "FAILED"
                          ? "text-[color:var(--pactra-critical)] font-bold"
                          : "text-[color:var(--pactra-warning)] font-bold"
                      }
                    >
                      {entry.verdict}
                    </span>
                  </div>

                  {entry.policy_outcome && (
                    <div className="text-[color:var(--pactra-ink-secondary)]">
                      policy_outcome:{" "}
                      <span className="text-[color:var(--pactra-indigo)] font-bold">{entry.policy_outcome}</span>
                    </div>
                  )}

                  <div className="text-[color:var(--pactra-ink-muted)]">
                    next_action: <span className="text-[color:var(--pactra-indigo)] font-semibold">{entry.next_action}</span>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
