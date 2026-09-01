import Link from "next/link";
import { ArrowUpRight, FileClock, ShieldCheck } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";

export function DecisionTracePreviewSection() {
  const frozenFields = [
    { field: "stage", val: '"EXECUTE"', type: "ADMIT | BIND | EXECUTE" },
    { field: "event_type", val: '"PAYMENT_SETTLED"', type: "Machine Event Identifier" },
    { field: "verdict", val: '"SUCCEEDED"', type: "ACCEPTED | REFUSED | SUCCEEDED..." },
    { field: "reason_codes", val: '["POLICY_SATISFIED", "PAYMENT_CONFIRMED"]', type: "Array of C1 reason strings" },
    { field: "invariant_id", val: '"INV_01_AUTH_REQUIRED"', type: "Contract Invariant ID" },
    { field: "approval_scheme", val: '"POLICY_AUTO"', type: "POLICY_AUTO | USER_ED25519" },
    { field: "policy_outcome", val: '"ALLOW"', type: "ALLOW | REQUIRE_APPROVAL | DENY" },
    { field: "payment_state", val: '"SUCCEEDED"', type: "CREATED | PROVIDER_PENDING | SUCCEEDED..." },
    { field: "advisory", val: '{ risk_index: 0.12, flags: [] }', type: "Advisory Risk Payload (No Authority)" },
    { field: "next_action", val: '"NONE"', type: "Recommended next step" },
    { field: "evidence", val: '{ provider_reference: "pay_test_98a" }', type: "Cryptographic & Provider Evidence" },
    { field: "recorded_at", val: '"2026-09-01T14:30:00.000Z"', type: "ISO-8601 Timestamp" },
  ];

  return (
    <Panel
      title="REPLAYABLE DECISION TRACE EVIDENCE"
      subtitle="Every mission step produces a contract-frozen DecisionTraceEntry. No chain-of-thought, no invented state_hash or prev_hash fields."
      actions={
        <Badge tone="accent" variant="outline" icon={<FileClock className="size-3.5" />}>
          SCHEMA PREVIEW
        </Badge>
      }
    >
      <div className="space-y-4">
        {/* Code / Schema Display Panel */}
        <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[#07080D] p-4 overflow-x-auto">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-white/10">
            <span className="font-mono text-[11px] font-bold text-[#9D9BE7] tracking-wider uppercase">
              FROZEN C1 DECISION TRACE SCHEMA (JSON)
            </span>
            <span className="font-mono text-[10px] text-white/50">
              Contract truth · Replayable Audit Record
            </span>
          </div>

          <pre className="font-mono text-[12px] leading-relaxed text-white/90">
            <code>{`DecisionTraceEntry {`}</code>
            {frozenFields.map((f) => (
              <div key={f.field} className="pl-4 flex flex-wrap items-baseline gap-2 py-0.5 hover:bg-white/[0.03]">
                <span className="text-[#9D9BE7] font-semibold">{f.field}:</span>
                <span className="text-[#BBB9F5]">{f.val},</span>
                <span className="text-[10px] text-white/40 italic">{`// ${f.type}`}</span>
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
