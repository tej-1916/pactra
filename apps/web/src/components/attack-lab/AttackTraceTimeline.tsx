import { FileText } from "lucide-react";
import type { DecisionTraceEntry } from "@/lib/types/pactra";
import { Badge } from "@/components/ui/Badge";

export function AttackTraceTimeline({ entries }: { entries: DecisionTraceEntry[] }) {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--pactra-line)] pb-3">
        <div>
          <h3 className="font-display text-[15px] font-bold text-white flex items-center gap-2">
            <FileText className="size-4 text-[#7C78E2]" />
            DECISION TRACE EVIDENCE
          </h3>
          <p className="text-[12px] text-[color:var(--pactra-ink-secondary)]">
            ADMIT → BIND → EXECUTE enforcement events projected from authored regression evidence.
          </p>
        </div>
        <Badge tone="accent" variant="outline">
          DEMO TRACE
        </Badge>
      </div>

      <div className="space-y-3">
        {entries.map((entry) => (
          <div
            key={entry.evidence.event_id}
            className="rounded border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-3.5 space-y-2 font-mono text-[11px]"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--pactra-line)] pb-2 text-[10.5px]">
              <div className="flex items-center gap-2">
                <span className="font-bold text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/15 px-2 py-0.5 rounded">
                  STAGE: {entry.stage}
                </span>
                <span className="text-white font-bold">{entry.event_type}</span>
              </div>
              <div className="text-[color:var(--pactra-ink-muted)]">
                {entry.recorded_at} (SYNTHETIC DEMO TRACE)
              </div>
            </div>

            <div className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-4 text-[11px]">
              <div>
                verdict:{" "}
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

              <div>
                policy_outcome:{" "}
                <span className="text-white font-semibold">{entry.policy_outcome ?? "NONE"}</span>
              </div>

              <div>
                next_action:{" "}
                <span className="text-[color:var(--pactra-indigo)] font-bold">{entry.next_action}</span>
              </div>

              <div>
                actor: <span className="text-[color:var(--pactra-ink-secondary)]">{entry.evidence.actor}</span>
              </div>
            </div>

            {entry.reason_codes.length > 0 && (
              <div className="flex items-center gap-1.5 pt-1 text-[10px]">
                <span className="text-[color:var(--pactra-ink-muted)]">reason_codes:</span>
                {entry.reason_codes.map((code) => (
                  <span
                    key={code}
                    className="font-bold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-1.5 py-0.5 rounded"
                  >
                    {code}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
