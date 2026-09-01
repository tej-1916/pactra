import { CheckCircle2, ShieldCheck, Lock, FileCode } from "lucide-react";
import { Panel } from "@/components/ui/Panel";

export function PipelineExplainerSection() {
  return (
    <Panel
      title="ADMIT → BIND → EXECUTE"
      subtitle="The 3-stage deterministic security pipeline every transaction must pass through. No fourth stage exists — Audit is evidence, not another stage."
    >
      <div className="grid gap-4 md:grid-cols-3">
        {/* Stage 1: ADMIT */}
        <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileCode className="size-4 text-[#7C78E2]" />
              <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
                1. ADMIT
              </span>
            </div>
            <span className="font-mono text-[10px] font-semibold text-[#9D9BE7] bg-[#7C78E2]/15 px-2 py-0.5 rounded uppercase">
              GATE 1 · POLICY
            </span>
          </div>

          <p className="text-[12px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
            Validates payload schema, assesses data provenance/taint, and checks capability boundaries before intent creation.
          </p>

          <div className="space-y-1.5 pt-2 border-t border-[color:var(--pactra-line)]">
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0" />
              <span>Typed Intent & Schema</span>
            </div>
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0" />
              <span>Provenance & Taint Isolation</span>
            </div>
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0" />
              <span>Merchant Capability Check</span>
            </div>
          </div>

          <div className="pt-2 space-y-1 text-[10px] font-mono text-[color:var(--pactra-ink-muted)]">
            <div>Verdicts: <span className="text-[color:var(--pactra-success)]">ACCEPTED</span> · <span className="text-[color:var(--pactra-critical)]">REFUSED</span></div>
            <div>Policy Outcome: <span className="text-[color:var(--pactra-indigo)]">ALLOW</span> · <span className="text-[color:var(--pactra-warning)]">REQUIRE_APPROVAL</span> · <span className="text-[color:var(--pactra-critical)]">DENY</span></div>
          </div>
        </div>

        {/* Stage 2: BIND */}
        <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Lock className="size-4 text-[#7C78E2]" />
              <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
                2. BIND
              </span>
            </div>
            <span className="font-mono text-[10px] font-semibold text-[#9D9BE7] bg-[#7C78E2]/15 px-2 py-0.5 rounded uppercase">
              GATE 2 · AUTHORIZATION
            </span>
          </div>

          <p className="text-[12px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
            Binds intent into a canonical transaction digest. Verifies nonces, expiry, and user signatures where required.
          </p>

          <div className="space-y-1.5 pt-2 border-t border-[color:var(--pactra-line)]">
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0" />
              <span>Canonical Digest Calculation</span>
            </div>
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0" />
              <span>POLICY_AUTO vs USER_ED25519</span>
            </div>
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[#7C78E2] shrink-0" />
              <span>Expiry & Replay Nonce Check</span>
            </div>
          </div>

          <div className="pt-2 text-[10px] font-mono text-[color:var(--pactra-warning)] font-semibold">
            Rule: Transaction mutation invalidates authorization digest.
          </div>
        </div>

        {/* Stage 3: EXECUTE */}
        <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-[color:var(--pactra-success)]" />
              <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
                3. EXECUTE
              </span>
            </div>
            <span className="font-mono text-[10px] font-semibold text-[color:var(--pactra-success)] bg-[color:var(--pactra-success)]/15 px-2 py-0.5 rounded uppercase">
              GATE 3 · EXECUTION
            </span>
          </div>

          <p className="text-[12px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
            Creates durable PaymentIntent, dispatches idempotently to provider, reconciles lost responses, and records audit trace.
          </p>

          <div className="space-y-1.5 pt-2 border-t border-[color:var(--pactra-line)]">
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[color:var(--pactra-success)] shrink-0" />
              <span>Idempotent Dispatch & Nonce</span>
            </div>
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[color:var(--pactra-success)] shrink-0" />
              <span>Provider Evidence & Webhook</span>
            </div>
            <div className="flex items-center gap-2 text-[11.5px] font-mono text-[color:var(--pactra-ink-secondary)]">
              <CheckCircle2 className="size-3.5 text-[color:var(--pactra-success)] shrink-0" />
              <span>Recorded Decision Trace Event</span>
            </div>
          </div>

          <div className="pt-2 text-[10px] font-mono text-[color:var(--pactra-success)] font-semibold">
            Rule: Same idempotency key ➔ at most one logical payment.
          </div>
        </div>
      </div>
    </Panel>
  );
}
