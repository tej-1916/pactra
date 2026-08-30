"use client";

import { motion } from "framer-motion";
import { useMemo, useState } from "react";
import { ListFilter } from "lucide-react";

import { DecisionTraceEntryRow } from "./DecisionTraceEntryRow";
import { NextActionChip, StageMarker } from "./TraceBadges";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/States";
import { cn } from "@/lib/format";
import { currentNextAction, groupByStage, STAGE_PRESENTATION, summarizeStage } from "@/lib/trace";
import type { DecisionTraceEntry } from "@/lib/types/pactra";

interface TraceFilter {
  id: string;
  label: string;
  match: (entry: DecisionTraceEntry) => boolean;
}

const ALL_ENTRIES: TraceFilter = { id: "all", label: "All entries", match: () => true };

const FILTERS: readonly TraceFilter[] = [
  ALL_ENTRIES,
  {
    id: "decisive",
    label: "Security results only",
    match: (entry) =>
      entry.verdict === "REFUSED" || entry.verdict === "FAILED" || entry.verdict === "SUCCEEDED",
  },
  { id: "advisory", label: "Advisory", match: (entry) => entry.advisory },
];

/**
 * The Decision Trace.
 *
 * Structured as ADMIT → BIND → EXECUTE because that is the system, and all
 * three stages are always drawn — including the ones a mission never reached.
 * An empty EXECUTE under a refused BIND is the answer; hiding the stage would
 * quietly imply the pipeline has only two.
 *
 * Motion here is doing one job: showing that a stage was REACHED and that an
 * entry EXPANDED. There is no ambient movement, because a security record is
 * read rather than watched.
 */
export function DecisionTrace({
  entries,
  className,
  /** Rendered when the trace is empty, so the caller can say WHY it is empty. */
  emptyDetail,
}: {
  entries: readonly DecisionTraceEntry[];
  className?: string;
  emptyDetail?: React.ReactNode;
}) {
  const [filterId, setFilterId] = useState("all");
  const filter = FILTERS.find((option) => option.id === filterId) ?? ALL_ENTRIES;

  const groups = useMemo(() => groupByStage(entries), [entries]);
  const next = useMemo(() => currentNextAction(entries), [entries]);

  if (entries.length === 0) {
    return (
      <EmptyState
        title="No decision trace"
        detail={
          emptyDetail ?? (
            <>
              The trace is returned only after the hash chain verifies and every enforcement event
              can be interpreted. An empty array is the honest answer when either is not true — it
              is not a mission with no history.
            </>
          )
        }
        className={className}
      />
    );
  }

  return (
    <div className={cn("space-y-4", className)}>
      {/* ------------------------------------------------ the stage rail -- */}
      <div className="grid gap-2 sm:grid-cols-3">
        {groups.map((group, index) => {
          const summary = summarizeStage(group);
          return (
            <motion.div
              key={group.stage}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, delay: index * 0.05, ease: "easeOut" }}
              className={cn(
                "rounded-md border px-3 py-2.5",
                summary.reached
                  ? "border-[color:var(--color-line-strong)] bg-[color:var(--color-surface)]"
                  : "border-dashed border-[color:var(--color-line)] bg-transparent",
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <StageMarker stage={group.stage} active={summary.reached} />
                <span className="num text-[10.5px] text-[color:var(--color-ink-4)]">
                  {summary.total} {summary.total === 1 ? "entry" : "entries"}
                </span>
              </div>
              <p className="mt-1.5 text-[11.5px] leading-snug text-[color:var(--color-ink-3)]">
                {STAGE_PRESENTATION[group.stage].question}
              </p>
              {summary.reached ? (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {summary.refused > 0 ? (
                    <Badge tone="secure" variant="outline">
                      {summary.refused} REFUSED
                    </Badge>
                  ) : null}
                  {summary.failed > 0 ? (
                    <Badge tone="critical" variant="outline">
                      {summary.failed} FAILED
                    </Badge>
                  ) : null}
                  {summary.pending > 0 ? (
                    <Badge tone="advisory" variant="outline">
                      {summary.pending} PENDING
                    </Badge>
                  ) : null}
                  {summary.advisory > 0 ? (
                    <Badge tone="advisory" variant="outline">
                      {summary.advisory} ADVISORY
                    </Badge>
                  ) : null}
                </div>
              ) : (
                <p className="mt-1.5 text-[11px] text-[color:var(--color-ink-4)]">
                  Not reached. This mission recorded no {group.stage} event.
                </p>
              )}
            </motion.div>
          );
        })}
      </div>

      {/* ------------------------------------------------- what's next --- */}
      {next ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2">
          <span className="label-xs text-[color:var(--color-ink-4)]">
            What can happen next, as of the last recorded decision
          </span>
          <NextActionChip action={next.action} />
          <span className="num text-[10.5px] text-[color:var(--color-ink-4)]">
            from #{next.from.evidence.sequence} {next.from.event_type}
          </span>
        </div>
      ) : null}

      {/* ------------------------------------------------------ filters -- */}
      <div
        role="group"
        aria-label="Filter decision trace"
        className="flex flex-wrap items-center gap-1.5"
      >
        <ListFilter aria-hidden className="size-3.5 text-[color:var(--color-ink-4)]" />
        {FILTERS.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={option.id === filterId}
            onClick={() => setFilterId(option.id)}
            className={cn(
              "rounded border px-2 py-[3px] text-[11px] font-medium transition-colors",
              option.id === filterId
                ? "border-[color:var(--color-accent)]/45 bg-[color:var(--color-accent)]/[0.10] text-[color:var(--color-accent)]"
                : "border-[color:var(--color-line)] text-[color:var(--color-ink-3)] hover:text-[color:var(--color-ink-2)]",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* ------------------------------------------------------ entries -- */}
      <div className="space-y-4">
        {groups.map((group) => {
          const visible = group.entries.filter(filter.match);
          return (
            <section key={group.stage} aria-label={`${group.stage} stage`}>
              <header className="mb-2 flex flex-wrap items-baseline gap-2">
                <StageMarker stage={group.stage} active={group.entries.length > 0} />
                <p className="max-w-[80ch] text-[11px] leading-snug text-[color:var(--color-ink-4)]">
                  {STAGE_PRESENTATION[group.stage].purpose}
                </p>
              </header>

              {group.entries.length === 0 ? (
                <p className="rounded-md border border-dashed border-[color:var(--color-line)] px-3 py-3 text-[11.5px] text-[color:var(--color-ink-4)]">
                  No {group.stage} entry was recorded for this mission.
                </p>
              ) : visible.length === 0 ? (
                <p className="rounded-md border border-dashed border-[color:var(--color-line)] px-3 py-3 text-[11.5px] text-[color:var(--color-ink-4)]">
                  {group.entries.length}{" "}
                  {group.entries.length === 1 ? "entry is" : "entries are"} recorded here, and none
                  match the current filter.
                </p>
              ) : (
                <ol className="space-y-1.5">
                  {visible.map((entry) => (
                    <DecisionTraceEntryRow key={entry.evidence.event_id} entry={entry} />
                  ))}
                </ol>
              )}
            </section>
          );
        })}
      </div>

      <p className="text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
        This is an action and security decision record projected from hash-chained audit events. It
        is not model reasoning, and it exposes no raw payload, signature, nonce, private key,
        approval-message bytes, provider secret or merchant description. Entries are ordered by{" "}
        <code className="num">(evidence.sequence, evidence.event_id)</code>, exactly as the frozen
        C1 contract specifies.
      </p>
    </div>
  );
}
