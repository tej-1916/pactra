import { ShieldAlert, FileText, RefreshCw, KeyRound } from "lucide-react";
import type { AttackScenarioId } from "./attackScenarios";

export function AttackScenarioSelector({
  selectedScenario,
  onSelectScenario,
}: {
  selectedScenario: AttackScenarioId;
  onSelectScenario: (id: AttackScenarioId) => void;
}) {
  return (
    <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
      {/* Scenario A: MERCHANT_PROMPT_INJECTION */}
      <button
        type="button"
        onClick={() => onSelectScenario("MERCHANT_PROMPT_INJECTION")}
        className={`rounded-md border p-3.5 text-left transition-all duration-150 ${
          selectedScenario === "MERCHANT_PROMPT_INJECTION"
            ? "border-[#7C78E2] bg-[#15183F]/80 shadow-sm"
            : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
        }`}
      >
        <div className="flex items-center justify-between pb-1.5">
          <span className="font-mono text-[12px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
            <FileText className="size-3.5 text-[color:var(--pactra-warning)]" />
            1. Prompt Injection
          </span>
          <span className="font-mono text-[9px] text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/10 px-1.5 py-0.5 rounded font-semibold">
            PROMPT INJECTION
          </span>
        </div>
        <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
          Merchant text attempts to override policy and force ₹0 price.
        </p>
      </button>

      {/* Scenario B: POST_AUTH_MUTATION */}
      <button
        type="button"
        onClick={() => onSelectScenario("POST_AUTH_MUTATION")}
        className={`rounded-md border p-3.5 text-left transition-all duration-150 ${
          selectedScenario === "POST_AUTH_MUTATION"
            ? "border-[#7C78E2] bg-[#15183F]/80 shadow-sm"
            : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
        }`}
      >
        <div className="flex items-center justify-between pb-1.5">
          <span className="font-mono text-[12px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
            <ShieldAlert className="size-3.5 text-[color:var(--pactra-critical)]" />
            2. Post-Auth Mutation
          </span>
          <span className="font-mono text-[9px] text-[color:var(--pactra-critical)] bg-[color:var(--pactra-critical)]/10 px-1.5 py-0.5 rounded font-semibold">
            TRANSACTION MUTATION
          </span>
        </div>
        <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
          Amount altered from ₹3,499 to ₹13,499 after authorization digest bound.
        </p>
      </button>

      {/* Scenario C: AUTHORIZATION_REPLAY */}
      <button
        type="button"
        onClick={() => onSelectScenario("AUTHORIZATION_REPLAY")}
        className={`rounded-md border p-3.5 text-left transition-all duration-150 ${
          selectedScenario === "AUTHORIZATION_REPLAY"
            ? "border-[#7C78E2] bg-[#15183F]/80 shadow-sm"
            : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
        }`}
      >
        <div className="flex items-center justify-between pb-1.5">
          <span className="font-mono text-[12px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
            <RefreshCw className="size-3.5 text-[#B7791F]" />
            3. Auth Replay
          </span>
          <span className="font-mono text-[9px] text-[#B7791F] bg-[#B7791F]/10 px-1.5 py-0.5 rounded font-semibold">
            AUTHORIZATION REPLAY
          </span>
        </div>
        <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
          Second spend attempt using an already-consumed authorization artifact.
        </p>
      </button>

      {/* Scenario D: CAPABILITY_DENIAL */}
      <button
        type="button"
        onClick={() => onSelectScenario("CAPABILITY_DENIAL")}
        className={`rounded-md border p-3.5 text-left transition-all duration-150 ${
          selectedScenario === "CAPABILITY_DENIAL"
            ? "border-[#7C78E2] bg-[#15183F]/80 shadow-sm"
            : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
        }`}
      >
        <div className="flex items-center justify-between pb-1.5">
          <span className="font-mono text-[12px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
            <KeyRound className="size-3.5 text-[color:var(--pactra-indigo)]" />
            4. Capability Denial
          </span>
          <span className="font-mono text-[9.5px] text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/10 px-1.5 py-0.5 rounded font-semibold">
            CAPABILITY VIOLATION
          </span>
        </div>
        <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
          Privileged payment dispatch attempt without holding required capability.
        </p>
      </button>
    </div>
  );
}
