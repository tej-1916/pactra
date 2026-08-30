"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Link2 } from "lucide-react";

import { HashDisplay } from "@/components/ui/HashDisplay";
import { cn, timestamp } from "@/lib/format";
import { redact } from "@/lib/redaction";
import type { AuditEvent } from "@/lib/types/pactra";

/**
 * The hash chain, drawn as a chain.
 *
 * Each row shows `previous_hash` above `event_hash`, and the link between
 * consecutive rows is the whole security property: event N's `previous_hash`
 * must equal event N−1's `event_hash`. Rendering them as two separate columns
 * would hide the one relationship a reader needs to check by eye.
 *
 * `linkOk` is computed here for DISPLAY ONLY. The authoritative verdict comes
 * from `GET /missions/{id}/audit/verify`, which recomputes every hash server
 * side; a green link icon in a browser proves nothing on its own and is never
 * presented as verification.
 */
export function AuditChain({
  events,
  highlightSequence,
}: {
  events: AuditEvent[];
  /** The sequence a verification failure named, if any. */
  highlightSequence?: number | null;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  function toggle(sequence: number) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(sequence)) next.delete(sequence);
      else next.add(sequence);
      return next;
    });
  }

  return (
    <ul className="divide-y divide-[color:var(--color-line)]/60">
      {events.map((event, index) => {
        const previous = index > 0 ? events[index - 1] : null;
        const linkOk = previous ? previous.event_hash === event.previous_hash : true;
        const flagged = highlightSequence != null && event.sequence === highlightSequence;
        const open = expanded.has(event.sequence);

        return (
          <li
            key={event.event_id}
            className={cn(
              "px-3 py-2.5 sm:px-4",
              flagged && "bg-[color:var(--color-critical)]/[0.07]",
            )}
          >
            <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
              <button
                type="button"
                onClick={() => toggle(event.sequence)}
                aria-expanded={open}
                className="flex min-w-0 flex-1 items-start gap-2 text-left"
              >
                {open ? (
                  <ChevronDown aria-hidden className="mt-[3px] size-3.5 shrink-0 text-[color:var(--color-ink-4)]" />
                ) : (
                  <ChevronRight aria-hidden className="mt-[3px] size-3.5 shrink-0 text-[color:var(--color-ink-4)]" />
                )}
                <span className="num w-8 shrink-0 text-[11.5px] text-[color:var(--color-ink-4)]">
                  #{event.sequence}
                </span>
                <span className="min-w-0">
                  <span className="num block truncate text-[12px] font-medium text-[color:var(--color-ink)]">
                    {event.event_type}
                  </span>
                  <span className="block text-[11px] text-[color:var(--color-ink-4)]">
                    {event.actor} · {timestamp(event.created_at)}
                  </span>
                </span>
              </button>

              <div className="flex shrink-0 flex-col items-start gap-1">
                <span className="flex items-center gap-1.5">
                  <Link2
                    aria-hidden
                    className={cn(
                      "size-3",
                      linkOk
                        ? "text-[color:var(--color-secure)]/70"
                        : "text-[color:var(--color-critical)]",
                    )}
                  />
                  <HashDisplay
                    label="prev"
                    value={event.previous_hash}
                    tone={linkOk ? "neutral" : "critical"}
                  />
                </span>
                <span className="pl-[18px]">
                  <HashDisplay label="hash" value={event.event_hash} />
                </span>
              </div>
            </div>

            {open ? (
              <pre className="num mt-2 max-h-72 overflow-auto rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3 text-[11px] leading-relaxed whitespace-pre-wrap text-[color:var(--color-ink-2)]">
                {JSON.stringify(redact(event.payload), null, 2)}
              </pre>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
