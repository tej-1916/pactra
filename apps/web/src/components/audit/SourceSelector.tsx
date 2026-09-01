import { useState } from "react";
import { Database, FileText, CheckCircle2, AlertTriangle, Loader2, ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { AUDIT_DEMO_SCENARIOS } from "./auditScenarios";

export type AuditSourceMode = "DEMO" | "RUNTIME";

export interface SourceSelectorProps {
  mode: AuditSourceMode;
  onSelectMode: (mode: AuditSourceMode) => void;
  selectedDemoScenarioId: string;
  onSelectDemoScenario: (id: string) => void;
  missions: Array<{ id: string; raw_query?: string }>;
  selectedMissionId: string | null;
  onSelectMission: (id: string) => void;
  runtimeStatus: "none" | "pending" | "unavailable" | "loaded";
}

export function SourceSelector({
  mode,
  onSelectMode,
  selectedDemoScenarioId,
  onSelectDemoScenario,
  missions,
  selectedMissionId,
  onSelectMission,
  runtimeStatus,
}: SourceSelectorProps) {
  const [manualId, setManualId] = useState("");

  const handleManualSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (manualId.trim()) {
      onSelectMission(manualId.trim());
    }
  };

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-4 space-y-4">
      {/* Mode Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--pactra-line)] pb-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onSelectMode("DEMO")}
            className={`rounded px-3 py-1.5 font-mono text-[12px] font-bold transition-colors ${
              mode === "DEMO"
                ? "bg-[#15183F] text-white border border-[#7C78E2]"
                : "bg-transparent text-[color:var(--pactra-ink-muted)] hover:text-white"
            }`}
          >
            <FileText className="size-3.5 inline mr-1.5 text-[color:var(--pactra-indigo)]" />
            AUTHORED DEMO TRACES
          </button>
          <button
            type="button"
            onClick={() => onSelectMode("RUNTIME")}
            className={`rounded px-3 py-1.5 font-mono text-[12px] font-bold transition-colors ${
              mode === "RUNTIME"
                ? "bg-[#15183F] text-white border border-[#7C78E2]"
                : "bg-transparent text-[color:var(--pactra-ink-muted)] hover:text-white"
            }`}
          >
            <Database className="size-3.5 inline mr-1.5 text-[color:var(--pactra-indigo)]" />
            RUNTIME MODE
          </button>
        </div>

        <div>
          {mode === "DEMO" ? (
            <Badge tone="accent" variant="outline">
              DEMO TRACE
            </Badge>
          ) : runtimeStatus === "pending" ? (
            <span className="font-mono text-[10.5px] font-semibold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-2.5 py-1 rounded inline-flex items-center gap-1.5">
              <Loader2 className="size-3 animate-spin" />
              AWAITING RUNTIME EVIDENCE
            </span>
          ) : runtimeStatus === "unavailable" ? (
            <span className="font-mono text-[10.5px] font-semibold text-[color:var(--pactra-critical)] bg-[color:var(--pactra-critical)]/15 px-2.5 py-1 rounded inline-flex items-center gap-1.5">
              <AlertTriangle className="size-3" />
              RUNTIME EVIDENCE UNAVAILABLE
            </span>
          ) : runtimeStatus === "loaded" ? (
            <span className="font-mono text-[10.5px] font-semibold text-[color:var(--pactra-success)] bg-[color:var(--pactra-success)]/15 px-2.5 py-1 rounded inline-flex items-center gap-1.5">
              <CheckCircle2 className="size-3" />
              RUNTIME EVIDENCE
            </span>
          ) : (
            <span className="font-mono text-[10.5px] text-[color:var(--pactra-ink-muted)] bg-[color:var(--pactra-surface-2)] px-2.5 py-1 rounded">
              NO MISSION SELECTED
            </span>
          )}
        </div>
      </div>

      {/* Scenario / Mission Selector Grid */}
      {mode === "DEMO" ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {Object.values(AUDIT_DEMO_SCENARIOS).map((sc) => (
            <button
              key={sc.id}
              type="button"
              onClick={() => onSelectDemoScenario(sc.id)}
              className={`rounded-md border p-3 text-left transition-all ${
                selectedDemoScenarioId === sc.id
                  ? "border-[#7C78E2] bg-[#15183F]/80 shadow-sm"
                  : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] hover:border-[color:var(--pactra-line-strong)]"
              }`}
            >
              <div className="font-mono text-[12px] font-bold text-white pb-1">
                {sc.name}
              </div>
              <p className="text-[11px] text-[color:var(--pactra-ink-secondary)] leading-snug line-clamp-2">
                {sc.description}
              </p>
            </button>
          ))}
        </div>
      ) : (
        <div className="space-y-3 font-mono text-[11.5px]">
          {/* Manual Mission ID Entry */}
          <form onSubmit={handleManualSubmit} className="flex gap-2 items-center">
            <input
              type="text"
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              placeholder="Enter UUID or mission ID (e.g. 550e8400-e29b-41d4-a716-446655440000)"
              className="flex-1 rounded border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] px-3 py-1.5 text-white text-[12px] placeholder:text-[color:var(--pactra-ink-muted)] focus:outline-none focus:border-[#7C78E2]"
            />
            <button
              type="submit"
              className="rounded bg-[#15183F] border border-[#7C78E2] px-3 py-1.5 font-bold text-white hover:bg-[#202160] transition-colors flex items-center gap-1 shrink-0"
            >
              Load Replay <ArrowRight className="size-3" />
            </button>
          </form>

          {/* Browser Registered Missions List */}
          <div className="space-y-1.5 pt-1">
            <div className="text-[10.5px] font-bold text-[color:var(--pactra-ink-muted)] uppercase">
              BROWSER-LOCAL MISSIONS (THIS BROWSER SESSION)
            </div>
            {missions.length === 0 ? (
              <div className="p-3 rounded bg-[color:var(--pactra-surface-2)] text-[color:var(--pactra-ink-secondary)]">
                No missions created in this browser session yet. You can paste a mission ID above or select an Authored Demo Trace.
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {missions.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => onSelectMission(m.id)}
                    className={`rounded border px-3 py-1.5 transition-colors ${
                      selectedMissionId === m.id
                        ? "border-[#7C78E2] bg-[#15183F] text-white font-bold"
                        : "border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] text-[color:var(--pactra-ink-muted)] hover:text-white"
                    }`}
                  >
                    {m.id} {m.raw_query ? `· "${m.raw_query}"` : ""}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
