import { Play, Database, ShieldAlert, CheckCircle2, RefreshCw } from "lucide-react";
import type { ScenarioId } from "./demoScenarios";
import { Badge } from "@/components/ui/Badge";

export type RuntimeEvidenceStatus = "none" | "pending" | "unavailable" | "loaded";

export function ScenarioSelector({
  selectedScenario,
  onSelectScenario,
  runtimeStatus = "none",
}: {
  selectedScenario: ScenarioId;
  onSelectScenario: (id: ScenarioId) => void;
  runtimeStatus?: RuntimeEvidenceStatus;
}) {
  const isLiveRuntime = selectedScenario === "LIVE_RUNTIME";

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="font-display text-[14px] font-bold text-[color:var(--pactra-ink)]">
              INTERACTIVE SCENARIO WORKBENCH
            </span>
            {!isLiveRuntime && (
              <Badge tone="advisory" variant="outline">
                DEMO SCENARIO
              </Badge>
            )}
            {isLiveRuntime && runtimeStatus === "pending" && (
              <Badge tone="advisory" variant="outline">
                AWAITING RUNTIME EVIDENCE
              </Badge>
            )}
            {isLiveRuntime && runtimeStatus === "unavailable" && (
              <Badge tone="critical" variant="outline">
                RUNTIME EVIDENCE UNAVAILABLE
              </Badge>
            )}
            {isLiveRuntime && runtimeStatus === "loaded" && (
              <Badge tone="secure" variant="outline">
                RUNTIME EVIDENCE
              </Badge>
            )}
          </div>
          <p className="text-[12px] text-[color:var(--pactra-ink-secondary)]">
            Select an authored interactive scenario or toggle live API runtime mode to inspect transaction evidence.
          </p>
        </div>

        <div className="flex items-center gap-2 font-mono text-[11px] text-[color:var(--pactra-ink-muted)]">
          <Play className="size-3.5 text-[color:var(--pactra-indigo)] shrink-0" />
          <span>Interactive State Machine</span>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {/* Scenario 1: BENIGN_PURCHASE */}
        <button
          type="button"
          onClick={() => onSelectScenario("BENIGN_PURCHASE")}
          className={`rounded-md border p-3 text-left transition-all duration-150 ${
            selectedScenario === "BENIGN_PURCHASE"
              ? "border-[color:var(--pactra-indigo)] bg-[color:var(--pactra-surface-3)] shadow-sm ring-1 ring-[color:var(--pactra-indigo)]/30"
              : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
          }`}
        >
          <div className="flex items-center justify-between pb-1">
            <span className="font-mono text-[11.5px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
              <CheckCircle2 className="size-3.5 text-[color:var(--pactra-success)]" />
              1. Benign Purchase
            </span>
            <span className="font-mono text-[9.5px] text-[color:var(--pactra-success)] bg-[color:var(--pactra-success)]/10 px-1.5 py-0.5 rounded font-semibold">
              POLICY_AUTO
            </span>
          </div>
          <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
            Auto-approved POLICY_AUTO journey under soft budget limit.
          </p>
        </button>

        {/* Scenario 2: USER_APPROVAL */}
        <button
          type="button"
          onClick={() => onSelectScenario("USER_APPROVAL")}
          className={`rounded-md border p-3 text-left transition-all duration-150 ${
            selectedScenario === "USER_APPROVAL"
              ? "border-[color:var(--pactra-indigo)] bg-[color:var(--pactra-surface-3)] shadow-sm ring-1 ring-[color:var(--pactra-indigo)]/30"
              : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
          }`}
        >
          <div className="flex items-center justify-between pb-1">
            <span className="font-mono text-[11.5px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
              <ShieldAlert className="size-3.5 text-[color:var(--pactra-warning)]" />
              2. User Approval
            </span>
            <span className="font-mono text-[9.5px] text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/10 px-1.5 py-0.5 rounded font-semibold">
              USER_ED25519
            </span>
          </div>
          <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
            Exceeds soft budget. REQUIRE_APPROVAL ➔ AWAIT_USER_SIGNATURE.
          </p>
        </button>

        {/* Scenario 3: PROVIDER_LOST */}
        <button
          type="button"
          onClick={() => onSelectScenario("PROVIDER_LOST")}
          className={`rounded-md border p-3 text-left transition-all duration-150 ${
            selectedScenario === "PROVIDER_LOST"
              ? "border-[color:var(--pactra-indigo)] bg-[color:var(--pactra-surface-3)] shadow-sm ring-1 ring-[color:var(--pactra-indigo)]/30"
              : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
          }`}
        >
          <div className="flex items-center justify-between pb-1">
            <span className="font-mono text-[11.5px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
              <RefreshCw className="size-3.5 text-[color:var(--pactra-warning)]" />
              3. Response Lost
            </span>
            <span className="font-mono text-[9.5px] text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/10 px-1.5 py-0.5 rounded font-semibold">
              RECONCILE
            </span>
          </div>
          <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
            Network timeout. PROVIDER_PENDING ➔ RECONCILE_PAYMENT.
          </p>
        </button>

        {/* Scenario 4: LIVE_RUNTIME */}
        <button
          type="button"
          onClick={() => onSelectScenario("LIVE_RUNTIME")}
          className={`rounded-md border p-3 text-left transition-all duration-150 ${
            selectedScenario === "LIVE_RUNTIME"
              ? "border-[color:var(--pactra-indigo)] bg-[color:var(--pactra-surface-3)] shadow-sm ring-1 ring-[color:var(--pactra-indigo)]/30"
              : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] hover:border-[color:var(--pactra-line-strong)]"
          }`}
        >
          <div className="flex items-center justify-between pb-1">
            <span className="font-mono text-[11.5px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
              <Database className="size-3.5 text-[color:var(--pactra-indigo)]" />
              4. Live Runtime
            </span>
            <span className="font-mono text-[9.5px] text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/10 px-1.5 py-0.5 rounded font-semibold">
              LIVE API
            </span>
          </div>
          <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug">
            Fetch real mission state & authorization from PACTRA API.
          </p>
        </button>
      </div>
    </div>
  );
}
