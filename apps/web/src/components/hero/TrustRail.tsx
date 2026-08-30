"use client";

import { CheckCircle2, ShieldCheck, KeyRound, Zap } from "lucide-react";
import { cn } from "@/lib/format";

export interface TrustRailProps {
  activeStage?: "admit" | "bind" | "execute" | "completed";
  className?: string;
}

export function TrustRail({ activeStage = "admit", className }: TrustRailProps) {
  const stages = [
    {
      id: "admit",
      title: "ADMIT",
      icon: ShieldCheck,
    },
    {
      id: "bind",
      title: "BIND",
      icon: KeyRound,
    },
    {
      id: "execute",
      title: "EXECUTE",
      icon: Zap,
    },
  ];

  const getStageState = (stageId: string) => {
    if (activeStage === "completed") return { status: "completed", label: "VERIFIED ✓", color: "emerald" };
    if (stageId === "admit") {
      if (activeStage === "admit") return { status: "active", label: "ACTIVE", color: "indigo" };
      return { status: "completed", label: "VERIFIED ✓", color: "emerald" };
    }
    if (stageId === "bind") {
      if (activeStage === "bind") return { status: "active", label: "ACTIVE", color: "indigo" };
      if (activeStage === "execute") return { status: "completed", label: "VERIFIED ✓", color: "emerald" };
      return { status: "pending", label: "WAITING", color: "neutral" };
    }
    if (stageId === "execute") {
      if (activeStage === "execute") return { status: "active", label: "ACTIVE", color: "indigo" };
      return { status: "pending", label: "WAITING", color: "neutral" };
    }
    return { status: "pending", label: "WAITING", color: "neutral" };
  };

  return (
    <div
      className={cn(
        "w-full rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-3 shadow-xs",
        className
      )}
      aria-label="Trust Pipeline Status: ADMIT BIND EXECUTE"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-[10px] font-bold tracking-wider text-[color:var(--pactra-ink-secondary)] uppercase">
          TRUST PIPELINE STATUS
        </span>
        <span className="font-mono text-[10px] font-semibold text-[color:var(--pactra-indigo)]">
          3-STAGE CONTROL
        </span>
      </div>

      <div className="flex items-center justify-between gap-1.5 sm:gap-3">
        {stages.map((stage, idx) => {
          const stateInfo = getStageState(stage.id);
          const Icon = stage.icon;

          return (
            <div key={stage.id} className="flex-1 flex items-center gap-2">
              <div
                className={cn(
                  "flex-1 flex items-center justify-between gap-2 rounded-md px-2.5 py-1.5 border transition-all duration-200",
                  stateInfo.status === "completed"
                    ? "bg-[#04785A]/10 border-[#04785A]/40 text-[#04785A]"
                    : stateInfo.status === "active"
                    ? "bg-[#1E2160] border-[#7C78E2] text-white shadow-xs"
                    : "bg-[color:var(--pactra-surface-2)] border-[color:var(--pactra-line)] text-[color:var(--pactra-ink-muted)]"
                )}
              >
                <div className="flex items-center gap-1.5 min-w-0">
                  {stateInfo.status === "completed" ? (
                    <CheckCircle2 className="size-3.5 shrink-0 text-[#04785A]" />
                  ) : (
                    <Icon className="size-3.5 shrink-0" />
                  )}
                  <span className="font-mono text-[11.5px] font-bold tracking-tight truncate">
                    {stage.title}
                  </span>
                </div>

                <span
                  className={cn(
                    "font-mono text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase shrink-0",
                    stateInfo.status === "completed"
                      ? "bg-[#04785A] text-white"
                      : stateInfo.status === "active"
                      ? "bg-[#4B42B9] text-white"
                      : "bg-[color:var(--pactra-line)] text-[color:var(--pactra-ink-secondary)]"
                  )}
                >
                  {stateInfo.label}
                </span>
              </div>

              {idx < stages.length - 1 && (
                <span className="text-[color:var(--pactra-line-strong)] font-mono text-[10px] hidden sm:inline">
                  ──
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
