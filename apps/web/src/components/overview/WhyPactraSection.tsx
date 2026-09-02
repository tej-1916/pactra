import { Shield, Brain, CreditCard } from "lucide-react";
import { Panel } from "@/components/ui/Panel";

export function WhyPactraSection() {
  return (
    <Panel
      title="THE REASONING LAYER IS NOT THE SECURITY BOUNDARY"
      subtitle="AI is probabilistic. Money requires deterministic guarantees. PACTRA is the security boundary between them."
    >
      <div className="grid gap-4 md:grid-cols-3">
        {/* Column 1: Untrusted AI Input */}
        <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[color:var(--pactra-ink-muted)]">
              <Brain className="size-4 shrink-0" />
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                UNTRUSTED INPUT
              </span>
            </div>
            <h3 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)]">
              AI Buyer & Merchant Data
            </h3>
            <p className="text-[12.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
              Prompts, catalog items, tool calls, and LLM reasoning outputs are untrusted by default.
              <span className="block mt-1 text-[11.5px] font-mono text-[color:var(--pactra-ink-muted)]">
                Untrusted does not mean malicious — it means unverified.
              </span>
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-[color:var(--pactra-line)]">
            <span className="font-mono text-[10px] font-semibold text-[color:var(--pactra-ink-muted)] uppercase">
              Role: PROPOSAL & SELECTION
            </span>
          </div>
        </div>

        {/* Column 2: Deterministic PACTRA Authority */}
        <div className="rounded-lg border border-[color:var(--pactra-indigo)]/40 bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between relative overflow-hidden">
          <div className="space-y-2 relative z-10">
            <div className="flex items-center gap-2 text-[color:var(--pactra-indigo)]">
              <Shield className="size-4 shrink-0" />
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                DETERMINISTIC AUTHORITY
              </span>
            </div>
            <h3 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)]">
              PACTRA Control Plane
            </h3>
            <p className="text-[12.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
              Enforces immutable admission policy, canonical transaction binding, user cryptographic approvals, and zero-trust invariant checks.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-[color:var(--pactra-line)] relative z-10">
            <span className="font-mono text-[10px] font-semibold text-[color:var(--pactra-indigo)] uppercase">
              Role: ENFORCEMENT & DECISION
            </span>
          </div>
        </div>

        {/* Column 3: Payment Provider Execution */}
        <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[color:var(--pactra-success)]">
              <CreditCard className="size-4 shrink-0" />
              <span className="font-mono text-[11px] font-bold uppercase tracking-wider">
                EXECUTION & EVIDENCE
              </span>
            </div>
            <h3 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)]">
              Payment Infrastructure
            </h3>
            <p className="text-[12.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
              Dispatches authorized PaymentIntents idempotently, handles lost responses via reconciliation, and returns provider evidence.
            </p>
          </div>
          <div className="mt-4 pt-3 border-t border-[color:var(--pactra-line)]">
            <span className="font-mono text-[10px] font-semibold text-[color:var(--pactra-success)] uppercase">
              Role: SETTLEMENT & AUDIT
            </span>
          </div>
        </div>
      </div>
    </Panel>
  );
}
