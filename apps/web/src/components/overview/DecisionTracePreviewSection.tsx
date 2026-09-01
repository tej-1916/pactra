import Link from "next/link";
import { ArrowUpRight, FileClock, ShieldCheck } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";

export function DecisionTracePreviewSection() {
  const contractFields = [
    { field: "stage", type: '"ADMIT" | "BIND" | "EXECUTE"' },
    { field: "event_type", type: "EventType" },
    { field: "verdict", type: '"ACCEPTED" | "REFUSED" | "PENDING" | "SUCCEEDED" | "FAILED" | "IGNORED" | "ADVISORY"' },
    { field: "reason_codes", type: "ReasonCode[]" },
    { field: "invariant_id", type: "string | null" },
    { field: "approval_scheme", type: '"POLICY_AUTO" | "USER_ED25519" | "LEGACY_SERVER" | null' },
    { field: "policy_outcome", type: '"ALLOW" | "REQUIRE_APPROVAL" | "DENY" | null' },
    { field: "payment_state", type: '"CREATED" | "QUEUED" | "PROCESSING" | "PROVIDER_PENDING" | "SUCCEEDED" | "FAILED_RETRYABLE" | "FAILED_TERMINAL" | "CANCELLED" | null' },
    { field: "advisory", type: "boolean" },
    { field: "next_action", type: "DecisionNextAction" },
    { field: "evidence", type: "{ event_id: UUID, sequence: number, actor: string }" },
    { field: "recorded_at", type: "string (ISO-8601 UTC)" },
  ];

  return (
    <Panel
      title="REPLAYABLE DECISION TRACE EVIDENCE"
      subtitle="Every mission step produces a contract-frozen DecisionTraceEntry. No chain-of-thought, no secrets, no fabricated fields."
      actions={
        <Badge tone="accent" variant="outline" icon={<FileClock className="size-3.5" />}>
          SCHEMA CONTRACT
        </Badge>
      }
    >
      <div className="space-y-4">
        {/* Code / Schema Display Panel */}
        <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface-2)] p-4 overflow-x-auto">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-[color:var(--pactra-line)]">
            <span className="font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)] tracking-wider uppercase">
              FROZEN C1 DECISION TRACE SCHEMA (JSON)
            </span>
            <span className="font-mono text-[10px] text-[color:var(--pactra-ink-muted)]">
              Contract truth · Replayable Audit Record
            </span>
          </div>

          <pre className="font-mono text-[12px] leading-relaxed text-[color:var(--pactra-ink)]">
            <code>{`interface DecisionTraceEntry {`}</code>
            {contractFields.map((f) => (
              <div key={f.field} className="pl-4 flex flex-wrap items-baseline gap-2 py-0.5 hover:bg-black/5 dark:hover:bg-white/5">
                <span className="text-[color:var(--pactra-indigo)] font-semibold">{f.field}:</span>
                <span className="text-[color:var(--pactra-ink-secondary)]">{f.type};</span>
              </div>
            ))}
            <code>{`}`}</code>
          </pre>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <div className="flex items-center gap-2 text-[12px] text-[color:var(--pactra-ink-secondary)]">
            <ShieldCheck className="size-4 text-[color:var(--pactra-success)]" />
            <span>Deterministic audit entries allow exact historical replay of accepted and refused transactions.</span>
          </div>

          <Link
            href="/audit"
            className="inline-flex items-center gap-1.5 font-mono text-[12.5px] font-bold text-[color:var(--pactra-indigo)] hover:underline"
          >
            <span>Explore Audit Trail</span>
            <ArrowUpRight className="size-4" />
          </Link>
        </div>
      </div>
    </Panel>
  );
}
