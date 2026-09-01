import { AlertOctagon, Info } from "lucide-react";
import type { AttackScenario } from "./attackScenarios";

export function DeterministicResultPanel({ scenario }: { scenario: AttackScenario }) {
  const { demoResult, advisoryRisk } = scenario;

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--pactra-line)] pb-3">
        <div className="flex items-center gap-2">
          <AlertOctagon className="size-4 text-[color:var(--pactra-critical)]" />
          <span className="font-mono text-[13px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            EXPECTED DETERMINISTIC RESULT
          </span>
        </div>
        <span className="font-mono text-[11px] font-bold text-[color:var(--pactra-critical)] bg-[color:var(--pactra-critical)]/15 px-2.5 py-1 rounded">
          {demoResult.status}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1 bg-[color:var(--pactra-surface-2)] p-3 rounded font-mono text-[11.5px]">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase">verdict</div>
          <div className="text-[color:var(--pactra-critical)] font-bold">{demoResult.verdict}</div>
          {demoResult.policyOutcome && (
            <div className="pt-1 text-[11px] text-[color:var(--pactra-ink-secondary)]">
              policy_outcome: <span className="text-[color:var(--pactra-ink)] font-bold">{demoResult.policyOutcome}</span>
            </div>
          )}
          <div className="text-[11px] text-[color:var(--pactra-ink-secondary)]">
            next_action: <span className="text-[color:var(--pactra-indigo)] font-bold">{demoResult.nextAction}</span>
          </div>
        </div>

        <div className="space-y-1 bg-[color:var(--pactra-surface-2)] p-3 rounded font-mono text-[11.5px]">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase">reason_codes</div>
          <div className="flex flex-wrap gap-1 pt-1">
            {demoResult.reasonCodes.map((code) => (
              <span key={code} className="text-[10px] font-bold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-2 py-0.5 rounded">
                {code}
              </span>
            ))}
          </div>
        </div>
      </div>

      <p className="text-[12px] text-[color:var(--pactra-ink-secondary)] leading-relaxed">
        {demoResult.explanation}
      </p>

      {/* Advisory Risk Section */}
      <div className="rounded border border-[color:var(--pactra-warning)]/30 bg-[color:var(--pactra-warning)]/10 p-3 space-y-1">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] font-bold text-[color:var(--pactra-warning)] uppercase tracking-wider flex items-center gap-1">
            <Info className="size-3 text-[color:var(--pactra-warning)]" />
            ADVISORY RISK EVALUATION (ADVISORY ONLY)
          </span>
          <span className="font-mono text-[10px] font-bold text-[color:var(--pactra-warning)]">
            {advisoryRisk.band} ({advisoryRisk.riskIndex})
          </span>
        </div>
        <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
          {advisoryRisk.note}
        </p>
      </div>
    </div>
  );
}
