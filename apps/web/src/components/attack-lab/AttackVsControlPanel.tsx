import { ShieldAlert, ShieldCheck, ArrowRight, Lock } from "lucide-react";
import type { AttackScenario } from "./attackScenarios";
import { Badge } from "@/components/ui/Badge";
import { TaintedText, TaintFindings } from "@/components/ui/Provenance";

export function AttackVsControlPanel({ scenario }: { scenario: AttackScenario }) {
  const { untrustedInput, pactraControl, beforeAfterDiff, replaySequence, capabilityGate } = scenario;

  return (
    <div className="grid gap-5 md:grid-cols-2 items-start">
      {/* Untrusted Input / Threat Side */}
      <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldAlert className="size-4 text-[color:var(--pactra-warning)]" />
            <span className="font-display text-[14px] font-bold text-[color:var(--pactra-ink)]">
              UNTRUSTED INPUT / THREAT VECTOR
            </span>
          </div>
          <Badge tone="advisory" variant="outline">
            HOSTILE ATTEMPT
          </Badge>
        </div>

        {/* Untrusted Payload Card */}
        <div className="rounded bg-[color:var(--pactra-surface-3)] p-3 space-y-1 font-mono text-[11.5px]">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase tracking-wider font-bold">
            {untrustedInput.label}
          </div>
          {untrustedInput.tainted ? (
            <div>
              <TaintedText value={untrustedInput.payload} label="Merchant text" className="text-white font-semibold" />
              <TaintFindings value={untrustedInput.payload} />
            </div>
          ) : (
            <div className="text-white font-semibold break-all bg-black/40 p-2 rounded border border-white/10">
              {untrustedInput.payload}
            </div>
          )}
        </div>

        {/* Before / After Mutation Visual (Scenario B) */}
        {beforeAfterDiff && (
          <div className="rounded border border-[color:var(--pactra-critical)]/40 bg-[color:var(--pactra-critical)]/10 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] font-bold text-[color:var(--pactra-critical)] uppercase tracking-wider">
                MUTATION ATTEMPT COMPARISON
              </span>
              <span className="font-mono text-[9px] text-white/50">SYNTHETIC DEMO DATA</span>
            </div>
            <div className="flex items-center justify-between text-[11.5px] font-mono">
              <div className="space-y-0.5">
                <div className="text-[10px] text-[color:var(--pactra-ink-muted)]">AUTHORIZED AMOUNT</div>
                <div className="text-[color:var(--pactra-success)] font-bold">{beforeAfterDiff.authorizedValue}</div>
              </div>
              <ArrowRight className="size-4 text-[color:var(--pactra-critical)] shrink-0" />
              <div className="space-y-0.5 text-right">
                <div className="text-[10px] text-[color:var(--pactra-critical)]">MUTATED AMOUNT PRESENTED</div>
                <div className="text-[color:var(--pactra-critical)] font-bold line-through">{beforeAfterDiff.mutatedValue}</div>
              </div>
            </div>
          </div>
        )}

        {/* Replay Sequence Visual (Scenario C) */}
        {replaySequence && (
          <div className="rounded border border-[#B7791F]/40 bg-[#B7791F]/10 p-3 space-y-2 font-mono text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-[#B7791F] uppercase tracking-wider">
                REPLAY SEQUENCE EVENT FLOW
              </span>
              <span className="text-[9px] text-white/50">SYNTHETIC DEMO DATA</span>
            </div>
            <div className="space-y-1">
              <div className="text-[color:var(--pactra-success)]">
                Initial: {replaySequence.initialStatus}
              </div>
              <div className="text-[color:var(--pactra-critical)] font-semibold">
                Replay: {replaySequence.attemptedReplayStatus}
              </div>
            </div>
          </div>
        )}

        {/* Capability Gate Visual (Scenario D) */}
        {capabilityGate && (
          <div className="rounded border border-[color:var(--pactra-indigo)]/40 bg-[#15183F]/60 p-3 space-y-2 font-mono text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold text-[#9D9BE7] uppercase tracking-wider">
                CAPABILITY FIREWALL SCOPE CHECK
              </span>
              <span className="text-[9px] text-white/50">SYNTHETIC DEMO DATA</span>
            </div>
            <div className="grid gap-1">
              <div className="text-[color:var(--pactra-ink-secondary)] flex justify-between">
                <span>Required Capability:</span>
                <span className="text-[color:var(--pactra-indigo)] font-bold">{capabilityGate.requiredCapability}</span>
              </div>
              <div className="text-[color:var(--pactra-ink-secondary)] flex justify-between">
                <span>Principal Set:</span>
                <span className="text-[color:var(--pactra-critical)] font-bold">{capabilityGate.principalCapability}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Control & Authority Side */}
      <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-[color:var(--pactra-success)]" />
            <span className="font-display text-[14px] font-bold text-white">
              PACTRA DETERMINISTIC CONTROL
            </span>
          </div>
          <Badge tone="secure" variant="outline">
            SECURITY KERNEL
          </Badge>
        </div>

        <div className="space-y-3">
          <div className="rounded bg-[color:var(--pactra-surface-2)] p-3 space-y-1">
            <span className="font-mono text-[10.5px] font-bold text-[color:var(--pactra-indigo)] uppercase tracking-wider">
              {pactraControl.label}
            </span>
            <p className="text-[12px] text-[color:var(--pactra-ink)] leading-relaxed">
              {pactraControl.explanation}
            </p>
            <p className="font-mono text-[11px] text-[color:var(--pactra-ink-secondary)] pt-1 border-t border-[color:var(--pactra-line)]">
              Mechanism: {pactraControl.mechanism}
            </p>
          </div>

          <div className="rounded border border-[#7C78E2]/30 bg-[#7C78E2]/10 p-3 space-y-1">
            <div className="flex items-center gap-1.5 font-mono text-[10px] font-bold text-[#9D9BE7] uppercase">
              <Lock className="size-3 text-[#9D9BE7]" />
              DETERMINISTIC INVARIANT RULE
            </div>
            <p className="font-mono text-[12px] font-bold text-white tracking-tight">
              {scenario.invariantStatement}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
