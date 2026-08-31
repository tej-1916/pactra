"use client";

import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";
import {
  Bot,
  Store,
  ShieldCheck,
  KeyRound,
  Zap,
  CreditCard,
  FileCheck,
  Scale,
  Fingerprint,
  Lock,
  LockKeyhole,
} from "lucide-react";
import { cn } from "@/lib/format";

export interface TrustGraphProps {
  activeStage?: "admit" | "bind" | "execute" | "completed";
  onStageChange?: (stage: "admit" | "bind" | "execute" | "completed") => void;
}

// 7 Sequential Traversal Steps in the Pipeline
const GRAPH_STEPS = [
  { id: "buyer", name: "AI BUYER" },
  { id: "merchant", name: "MERCHANT OFFER" },
  { id: "admit", name: "ADMIT" },
  { id: "bind", name: "BIND" },
  { id: "execute", name: "EXECUTE" },
  { id: "payment", name: "PAYMENT PROVIDER" },
  { id: "audit", name: "AUDIT / REPLAY" },
];

export function SignatureTrustGraph({ activeStage: _activeStage, onStageChange }: TrustGraphProps) {
  const shouldReduceMotion = useReducedMotion();
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isVisible, setIsVisible] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  // Intersection observer for performance & off-screen pause (Section 14)
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]) {
          setIsVisible(entries[0].isIntersecting);
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Motion rhythm: One full transaction traversal -> pause 6s -> subtle replay (Section 15)
  useEffect(() => {
    if (shouldReduceMotion || !isVisible) return;

    const isEnd = currentStepIndex === GRAPH_STEPS.length - 1;
    const delay = isEnd ? 6000 : 900;

    const timeout = setTimeout(() => {
      setCurrentStepIndex((prev) => {
        const next = (prev + 1) % GRAPH_STEPS.length;
        if (next <= 1) onStageChange?.("admit");
        else if (next === 2) onStageChange?.("admit");
        else if (next === 3) onStageChange?.("bind");
        else if (next === 4) onStageChange?.("execute");
        else onStageChange?.("completed");
        return next;
      });
    }, delay);

    return () => clearTimeout(timeout);
  }, [currentStepIndex, shouldReduceMotion, isVisible, onStageChange]);

  const stepId = GRAPH_STEPS[currentStepIndex]?.id || "admit";

  // Helper to resolve node status
  const getNodeState = (nodeId: string, nodeStepIdx: number) => {
    if (shouldReduceMotion) return { active: false, passed: true, status: "VERIFIED", tone: "emerald" };
    if (currentStepIndex > nodeStepIdx) return { active: false, passed: true, status: "VERIFIED", tone: "emerald" };
    if (currentStepIndex === nodeStepIdx) return { active: true, passed: false, status: "ACTIVE", tone: "periwinkle" };
    return { active: false, passed: false, status: "WAITING", tone: "amber" };
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full overflow-hidden rounded-xl border border-[color:var(--pactra-line-strong)] bg-gradient-to-b from-[#15183F] via-[#202160] via-60% to-[#3B359E] p-4 sm:p-5 text-[#F7F7FF] shadow-xl max-h-[620px]"
      aria-label="PACTRA Transaction Authority Graph"
    >
      {/* Infrastructure Dot Grid Overlay (Section 10) */}
      <div
        className="pactra-dot-grid-dark absolute inset-0 pointer-events-none opacity-30"
        style={{
          maskImage: "radial-gradient(ellipse at 50% 50%, black 40%, transparent 85%)",
          WebkitMaskImage: "radial-gradient(ellipse at 50% 50%, black 40%, transparent 85%)",
        }}
      />

      {/* Atmospheric Radial Illumination around active nodes */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 size-80 bg-radial from-[#9691EC]/15 via-[#3B359E]/05 to-transparent blur-2xl pointer-events-none" />

      {/* Dark Section Technical Header (Section 13) */}
      <div className="relative z-10 flex items-center justify-between mb-3 pb-2.5 border-b border-white/10">
        <div className="flex items-center gap-2">
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#9691EC] opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-[#9691EC]" />
          </span>
          <span className="font-mono text-[11px] font-bold tracking-wider text-[#BBB9F5] uppercase">
            TRANSACTION AUTHORITY GRAPH
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono text-[10px] text-[#BBB9F5]">
          <span className="px-2 py-0.5 rounded bg-[#202160] border border-[#7771DF]/40 font-semibold text-white">
            DETERMINISTIC CONTROL PLANE
          </span>
          <span className="hidden sm:inline-flex items-center gap-1 font-semibold text-[#BBB9F5] bg-[#202160] px-2 py-0.5 rounded border border-white/10">
            TRANSACTION PATH
          </span>
        </div>
      </div>

      {/* Hierarchical System Graph Layout (Section 4 & 5) */}
      <div className="relative z-10 flex flex-col items-center gap-2.5 w-full py-1">

        {/* 1. TOP EXTERNAL INPUTS: AI BUYER -> MERCHANT OFFER */}
        <div className="flex items-center gap-3 sm:gap-6 justify-center w-full">
          {/* AI BUYER */}
          {(() => {
            const state = getNodeState("buyer", 0);
            return (
              <div
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#202160] border-[#9691EC] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <Bot className="size-4 text-[#9691EC]" />
                <div>
                  <span className="font-mono text-[11px] font-bold block leading-none">AI BUYER</span>
                  <span className="text-[8.5px] font-mono text-[#BBB9F5]/80">Autonomous Agent</span>
                </div>
              </div>
            );
          })()}

          <span className="text-[#9691EC] font-mono text-xs">➔</span>

          {/* MERCHANT OFFER */}
          {(() => {
            const state = getNodeState("merchant", 1);
            return (
              <div
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#202160] border-[#9691EC] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <Store className="size-4 text-[#9691EC]" />
                <div>
                  <span className="font-mono text-[11px] font-bold block leading-none">MERCHANT OFFER</span>
                  <span className="text-[8.5px] font-mono text-[#BBB9F5]/80">Untrusted Input</span>
                </div>
              </div>
            );
          })()}
        </div>

        {/* Downward Connector Arrow */}
        <div className="flex flex-col items-center">
          <div className="h-2.5 w-0.5 bg-[#9691EC]/60" />
          <span className="text-[#9691EC] text-[10px] leading-none">▼</span>
        </div>

        {/* 2. MAIN SECURITY CONTROL PLANE CONTAINER (Section 4) */}
        <div className="w-full max-w-2xl rounded-xl border border-[#7771DF]/40 bg-[#15183F]/90 p-3.5 sm:p-4 relative shadow-inner">
          <div className="absolute top-2 left-3 font-mono text-[9px] font-bold tracking-widest text-[#BBB9F5]/50 uppercase">
            PACTRA CONTROL PLANE BOUNDARY
          </div>

          <div className="flex flex-col items-center gap-3 mt-3">

            {/* PRIMARY NODE 1: ADMIT */}
            {(() => {
              const state = getNodeState("admit", 2);
              return (
                <div
                  className={cn(
                    "w-full max-w-xs flex items-center justify-between rounded-lg p-2.5 sm:p-3 border transition-all duration-300",
                    state.active || state.passed
                      ? "bg-[#2C297C] border-[#9691EC] text-white shadow-md ring-2 ring-[#9691EC]/30"
                      : "bg-[#202160]/70 border-[#7771DF]/30 text-[#BBB9F5]"
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <div className="flex size-7 items-center justify-center rounded-md bg-[#3B359E] text-white font-bold">
                      <ShieldCheck className="size-4 text-white" />
                    </div>
                    <div>
                      <span className="font-mono text-[13px] font-extrabold tracking-tight block leading-none">
                        ADMIT
                      </span>
                      <span className="text-[9.5px] font-sans text-[#BBB9F5]">Gate 1 · Policy Admission</span>
                    </div>
                  </div>

                  <span
                    className={cn(
                      "font-mono text-[9px] font-bold px-2 py-0.5 rounded uppercase tracking-wider",
                      state.passed
                        ? "bg-[#059669] text-white"
                        : state.active
                        ? "bg-[#7771DF] text-white animate-pulse"
                        : "bg-[#202160] text-[#BBB9F5]"
                    )}
                  >
                    {state.passed ? "VERIFIED ✓" : state.active ? "CHECKING" : "STAGE 1"}
                  </span>
                </div>
              );
            })()}

            {/* SECONDARY SUPPORT NODES BRANCH: POLICY, PROVENANCE, CAPABILITY (Section 5) */}
            <div className="grid grid-cols-3 gap-2 w-full max-w-lg">
              <div className="flex items-center gap-1.5 rounded-md border border-white/10 bg-[#202160]/60 p-1.5 text-center justify-center">
                <Scale className="size-3 text-[#9691EC] shrink-0" />
                <span className="font-mono text-[9.5px] font-bold text-[#BBB9F5] truncate">POLICY</span>
              </div>
              <div className="flex items-center gap-1.5 rounded-md border border-white/10 bg-[#202160]/60 p-1.5 text-center justify-center">
                <Fingerprint className="size-3 text-[#9691EC] shrink-0" />
                <span className="font-mono text-[9.5px] font-bold text-[#BBB9F5] truncate">PROVENANCE</span>
              </div>
              <div className="flex items-center gap-1.5 rounded-md border border-white/10 bg-[#202160]/60 p-1.5 text-center justify-center">
                <Lock className="size-3 text-[#9691EC] shrink-0" />
                <span className="font-mono text-[9.5px] font-bold text-[#BBB9F5] truncate">CAPABILITY</span>
              </div>
            </div>

            {/* Connector Line */}
            <div className="h-2 w-0.5 bg-[#9691EC]/60" />

            {/* PRIMARY NODE 2: BIND */}
            {(() => {
              const state = getNodeState("bind", 3);
              return (
                <div
                  className={cn(
                    "w-full max-w-xs flex items-center justify-between rounded-lg p-2.5 sm:p-3 border transition-all duration-300",
                    state.active || state.passed
                      ? "bg-[#2C297C] border-[#9691EC] text-white shadow-md ring-2 ring-[#9691EC]/30"
                      : "bg-[#202160]/70 border-[#7771DF]/30 text-[#BBB9F5]"
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <div className="flex size-7 items-center justify-center rounded-md bg-[#3B359E] text-white font-bold">
                      <KeyRound className="size-4 text-white" />
                    </div>
                    <div>
                      <span className="font-mono text-[13px] font-extrabold tracking-tight block leading-none">
                        BIND
                      </span>
                      <span className="text-[9.5px] font-sans text-[#BBB9F5]">Gate 2 · Canonical Authorization</span>
                    </div>
                  </div>

                  <span
                    className={cn(
                      "font-mono text-[9px] font-bold px-2 py-0.5 rounded uppercase tracking-wider",
                      state.passed
                        ? "bg-[#059669] text-white"
                        : state.active
                        ? "bg-[#7771DF] text-white animate-pulse"
                        : "bg-[#202160] text-[#BBB9F5]"
                    )}
                  >
                    {state.passed ? "BOUND ✓" : state.active ? "BINDING" : "STAGE 2"}
                  </span>
                </div>
              );
            })()}

            {/* SECONDARY SUPPORT NODE: AUTHORIZATION */}
            <div className="flex items-center gap-2 rounded-md border border-white/10 bg-[#202160]/60 px-3 py-1 text-center">
              <LockKeyhole className="size-3 text-[#9691EC]" />
              <span className="font-mono text-[10px] font-semibold text-[#BBB9F5]">
                AUTHORIZATION · Canonical Intent & Scheme
              </span>
            </div>

            {/* Connector Line */}
            <div className="h-2 w-0.5 bg-[#9691EC]/60" />

            {/* PRIMARY NODE 3: EXECUTE */}
            {(() => {
              const state = getNodeState("execute", 4);
              return (
                <div
                  className={cn(
                    "w-full max-w-xs flex items-center justify-between rounded-lg p-2.5 sm:p-3 border transition-all duration-300",
                    state.active || state.passed
                      ? "bg-[#2C297C] border-[#9691EC] text-white shadow-md ring-2 ring-[#9691EC]/30"
                      : "bg-[#202160]/70 border-[#7771DF]/30 text-[#BBB9F5]"
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <div className="flex size-7 items-center justify-center rounded-md bg-[#3B359E] text-white font-bold">
                      <Zap className="size-4 text-white" />
                    </div>
                    <div>
                      <span className="font-mono text-[13px] font-extrabold tracking-tight block leading-none">
                        EXECUTE
                      </span>
                      <span className="text-[9.5px] font-sans text-[#BBB9F5]">Gate 3 · Payment Execution</span>
                    </div>
                  </div>

                  <span
                    className={cn(
                      "font-mono text-[9px] font-bold px-2 py-0.5 rounded uppercase tracking-wider",
                      state.passed
                        ? "bg-[#059669] text-white"
                        : state.active
                        ? "bg-[#7771DF] text-white animate-pulse"
                        : "bg-[#202160] text-[#BBB9F5]"
                    )}
                  >
                    {state.passed ? "DISPATCHED" : state.active ? "EXECUTING" : "STAGE 3"}
                  </span>
                </div>
              );
            })()}

          </div>
        </div>

        {/* Downward Connector Arrow Exit Control Plane */}
        <div className="flex flex-col items-center">
          <div className="h-2.5 w-0.5 bg-[#9691EC]/60" />
          <span className="text-[#9691EC] text-[10px] leading-none">▼</span>
        </div>

        {/* 3. EXTERNAL OUTPUTS: PAYMENT PROVIDER & AUDIT / REPLAY */}
        <div className="flex items-center gap-3 sm:gap-6 justify-center w-full">
          {/* PAYMENT PROVIDER */}
          {(() => {
            const state = getNodeState("payment", 5);
            return (
              <div
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#202160] border-[#9691EC] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <CreditCard className="size-4 text-[#9691EC]" />
                <div>
                  <span className="font-mono text-[11px] font-bold block leading-none">PAYMENT PROVIDER</span>
                  <span className="text-[8.5px] font-mono text-[#BBB9F5]/80">Provider Evidence</span>
                </div>
              </div>
            );
          })()}

          <span className="text-[#9691EC] font-mono text-xs">➔</span>

          {/* AUDIT / REPLAY */}
          {(() => {
            const state = getNodeState("audit", 6);
            return (
              <div
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#059669]/20 border-[#059669] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <FileCheck className="size-4 text-[#059669]" />
                <div>
                  <span className="font-mono text-[11px] font-bold block leading-none">AUDIT / REPLAY</span>
                  <span className="text-[8.5px] font-mono text-[#059669]">Decision Trace</span>
                </div>
              </div>
            );
          })()}
        </div>

      </div>

      {/* Footer Status Bar */}
      <div className="relative z-10 mt-3 flex flex-wrap items-center justify-between gap-2 pt-2.5 border-t border-white/10 text-[10.5px] font-mono text-[#BBB9F5]">
        <div className="flex items-center gap-2">
          <span className="text-white font-semibold">ACTIVE STAGE:</span>
          <span className="px-2 py-0.5 rounded bg-[#3B359E] text-white font-bold uppercase text-[9.5px]">
            {stepId}
          </span>
        </div>
        <div className="text-[9.5px] text-[#BBB9F5]/80">
          Deterministic 3-Gate Control • Replayable Audit Chain
        </div>
      </div>
    </div>
  );
}
