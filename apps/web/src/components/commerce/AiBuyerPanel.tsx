import { Brain, AlertCircle, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";

export function AiBuyerPanel({
  missionQuery,
  constraints,
  candidateId,
  rationale,
}: {
  missionQuery: string;
  constraints: { label: string; val: string }[];
  candidateId: string;
  rationale: string;
}) {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="size-4 text-[#9D9BE7]" />
          <span className="font-display text-[14px] font-bold text-[color:var(--pactra-ink)]">
            AI BUYER (PROPOSAL)
          </span>
        </div>
        <Badge tone="neutral" variant="outline" icon={<Sparkles className="size-3" />}>
          PROPOSAL DATA ONLY
        </Badge>
      </div>

      {/* Query */}
      <div className="rounded bg-[color:var(--pactra-surface-3)] p-2.5 space-y-1">
        <span className="font-mono text-[10px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
          AI MISSION QUERY
        </span>
        <p className="font-mono text-[12.5px] font-semibold text-white">
          &quot;{missionQuery}&quot;
        </p>
      </div>

      {/* Constraints Grid */}
      <div className="space-y-1">
        <span className="font-mono text-[10px] font-bold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider">
          EXTRACTED CONSTRAINTS
        </span>
        <KeyValueGrid columns={3}>
          {constraints.map((c) => (
            <KeyValue key={c.label} label={c.label}>
              <span className="font-mono text-[11.5px] text-[color:var(--pactra-ink-secondary)]">
                {c.val}
              </span>
            </KeyValue>
          ))}
        </KeyValueGrid>
      </div>

      {/* Selected Candidate */}
      <div className="pt-2 border-t border-[color:var(--pactra-line)] space-y-1">
        <div className="flex items-center justify-between text-[11px] font-mono">
          <span className="text-[color:var(--pactra-ink-muted)] uppercase font-semibold">
            SELECTED CANDIDATE ID
          </span>
          <span className="text-[color:var(--pactra-indigo)] font-bold">{candidateId}</span>
        </div>
        <p className="text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
          {rationale}
        </p>
      </div>

      {/* Product Truth Notice */}
      <div className="rounded border border-[#7C78E2]/30 bg-[#15183F]/40 p-2.5 text-[11px] leading-relaxed text-[#BBB9F5] flex items-start gap-2">
        <AlertCircle className="size-3.5 text-[#9D9BE7] shrink-0 mt-0.5" />
        <div>
          <span className="font-mono font-bold text-white uppercase">PRODUCT TRUTH:</span>{" "}
          AI output is proposal data, not transaction authority. The model selects a candidate ID; it cannot authorize funds or bind terms.
        </div>
      </div>
    </div>
  );
}
