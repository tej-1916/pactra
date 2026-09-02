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

  // Intersection observer for performance & off-screen pause
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

  // Motion rhythm: One full transaction traversal -> pause 6s -> subtle replay
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
    if (shouldReduceMotion) return { active: false, passed: true, status: "VERIFIED" };
    if (currentStepIndex > nodeStepIdx) return { active: false, passed: true, status: "VERIFIED" };
    if (currentStepIndex === nodeStepIdx) return { active: true, passed: false, status: "ACTIVE" };
    return { active: false, passed: false, status: "WAITING" };
  };

  return (
    <div
      ref={containerRef}
      className="relative w-full min-w-0 max-w-full overflow-hidden rounded-xl border border-[color:var(--pactra-line-strong)] bg-gradient-to-b from-[#15183F] via-[#202160] via-60% to-[#3B359E] p-3 sm:p-5 text-[#F7F7FF] shadow-xl"
      aria-label="PACTRA Transaction Authority Graph"
    >
      {/* Infrastructure Dot Grid Overlay */}
      <div
        className="pactra-dot-grid-dark absolute inset-0 pointer-events-none opacity-30"
        style={{
          maskImage: "radial-gradient(ellipse at 50% 50%, black 40%, transparent 85%)",
          WebkitMaskImage: "radial-gradient(ellipse at 50% 50%, black 40%, transparent 85%)",
        }}
      />

      {/* Atmospheric Radial Illumination around active nodes */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 size-80 bg-radial from-[#9691EC]/15 via-[#3B359E]/05 to-transparent blur-2xl pointer-events-none" />

      {/* Technical Header */}
      <div className="relative z-10 flex flex-wrap items-center justify-between gap-1.5 mb-3 pb-2 border-b border-white/10">
        <div className="flex items-center gap-1.5">
          <span className="relative flex size-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#9691EC] opacity-75" />
            <span className="relative inline-flex size-2 rounded-full bg-[#9691EC]" />
          </span>
          <span className="font-mono text-[10.5px] sm:text-[11px] font-bold tracking-wider text-[#BBB9F5] uppercase">
            TRANSACTION AUTHORITY GRAPH
          </span>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-[9px] sm:text-[10px] text-[#BBB9F5]">
          <span className="px-1.5 sm:px-2 py-0.5 rounded bg-[#202160] border border-[#7771DF]/40 font-semibold text-white">
            DETERMINISTIC CONTROL PLANE
          </span>
        </div>
      </div>

      {/* Hierarchical System Graph Layout */}
      <div className="relative z-10 flex flex-col items-center gap-2 w-full py-0.5 min-w-0">

        {/* 1. TOP EXTERNAL INPUTS: AI BUYER -> MERCHANT OFFER */}
        <div className="flex items-center gap-1.5 sm:gap-4 justify-center w-full max-w-md min-w-0">
          {/* AI BUYER */}
          {(() => {
            const state = getNodeState("buyer", 0);
            return (
              <div
                className={cn(
                  "flex-1 min-w-0 flex items-center gap-1.5 sm:gap-2 rounded-lg px-2 sm:px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#202160] border-[#9691EC] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <Bot className="size-3.5 sm:size-4 text-[#9691EC] shrink-0" />
                <div className="min-w-0">
                  <span className="font-mono text-[10px] sm:text-[11px] font-bold block leading-tight truncate">AI BUYER</span>
                  <span className="text-[8px] sm:text-[8.5px] font-mono text-[#BBB9F5]/80 block truncate">Autonomous Agent</span>
                </div>
              </div>
            );
          })()}

          <span className="text-[#9691EC] font-mono text-xs shrink-0">➔</span>

          {/* MERCHANT OFFER */}
          {(() => {
            const state = getNodeState("merchant", 1);
            return (
              <div
                className={cn(
                  "flex-1 min-w-0 flex items-center gap-1.5 sm:gap-2 rounded-lg px-2 sm:px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#202160] border-[#9691EC] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <Store className="size-3.5 sm:size-4 text-[#9691EC] shrink-0" />
                <div className="min-w-0">
                  <span className="font-mono text-[10px] sm:text-[11px] font-bold block leading-tight truncate">MERCHANT OFFER</span>
                  <span className="text-[8px] sm:text-[8.5px] font-mono text-[#BBB9F5]/80 block truncate">Untrusted Input</span>
                </div>
              </div>
            );
          })()}
        </div>

        {/* Downward Connector Arrow */}
        <div className="flex flex-col items-center">
          <div className="h-2 w-0.5 bg-[#9691EC]/60" />
          <span className="text-[#9691EC] text-[9px] leading-none">▼</span>
        </div>

        {/* 2. MAIN SECURITY CONTROL PLANE CONTAINER */}
        <div className="w-full max-w-md rounded-xl border border-[#7771DF]/40 bg-[#15183F]/90 p-2.5 sm:p-3.5 relative shadow-inner min-w-0">
          <div className="font-mono text-[8.5px] sm:text-[9px] font-bold tracking-widest text-[#BBB9F5]/50 uppercase mb-2">
            PACTRA CONTROL PLANE BOUNDARY
          </div>

          <div className="flex flex-col items-center gap-2 sm:gap-2.5 w-full min-w-0">

            {/* PRIMARY NODE 1: ADMIT */}
            {(() => {
              const state = getNodeState("admit", 2);
              return (
                <div
                  className={cn(
                    "w-full flex items-center justify-between gap-2 rounded-lg p-2 sm:p-2.5 border transition-all duration-300 min-w-0",
                    state.active || state.passed
                      ? "bg-[#2C297C] border-[#9691EC] text-white shadow-md ring-2 ring-[#9691EC]/30"
                      : "bg-[#202160]/70 border-[#7771DF]/30 text-[#BBB9F5]"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="flex size-6 sm:size-7 items-center justify-center rounded-md bg-[#3B359E] text-white font-bold shrink-0">
                      <ShieldCheck className="size-3.5 sm:size-4 text-white" />
                    </div>
                    <div className="min-w-0">
                      <span className="font-mono text-[12px] sm:text-[13px] font-extrabold tracking-tight block leading-tight truncate">
                        ADMIT
                      </span>
                      <span className="text-[8.5px] sm:text-[9.5px] font-sans text-[#BBB9F5] block truncate">Gate 1 · Policy Admission</span>
                    </div>
                  </div>

                  <span
                    className={cn(
                      "font-mono text-[8.5px] sm:text-[9px] font-bold px-1.5 sm:px-2 py-0.5 rounded uppercase tracking-wider shrink-0",
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

            {/* SECONDARY SUPPORT NODES BRANCH: POLICY, PROVENANCE, CAPABILITY */}
            <div className="grid grid-cols-3 gap-1.5 sm:gap-2 w-full min-w-0">
              <div className="flex items-center justify-center gap-1 rounded-md border border-white/10 bg-[#202160]/60 p-1 sm:p-1.5 text-center min-w-0">
                <Scale className="size-3 text-[#9691EC] shrink-0" />
                <span className="font-mono text-[8.5px] sm:text-[9.5px] font-bold text-[#BBB9F5] truncate">POLICY</span>
              </div>
              <div className="flex items-center justify-center gap-1 rounded-md border border-white/10 bg-[#202160]/60 p-1 sm:p-1.5 text-center min-w-0">
                <Fingerprint className="size-3 text-[#9691EC] shrink-0" />
                <span className="font-mono text-[8.5px] sm:text-[9.5px] font-bold text-[#BBB9F5] truncate">PROVENANCE</span>
              </div>
              <div className="flex items-center justify-center gap-1 rounded-md border border-white/10 bg-[#202160]/60 p-1 sm:p-1.5 text-center min-w-0">
                <Lock className="size-3 text-[#9691EC] shrink-0" />
                <span className="font-mono text-[8.5px] sm:text-[9.5px] font-bold text-[#BBB9F5] truncate">CAPABILITY</span>
              </div>
            </div>

            {/* Connector Line */}
            <div className="h-1.5 w-0.5 bg-[#9691EC]/60" />

            {/* PRIMARY NODE 2: BIND */}
            {(() => {
              const state = getNodeState("bind", 3);
              return (
                <div
                  className={cn(
                    "w-full flex items-center justify-between gap-2 rounded-lg p-2 sm:p-2.5 border transition-all duration-300 min-w-0",
                    state.active || state.passed
                      ? "bg-[#2C297C] border-[#9691EC] text-white shadow-md ring-2 ring-[#9691EC]/30"
                      : "bg-[#202160]/70 border-[#7771DF]/30 text-[#BBB9F5]"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="flex size-6 sm:size-7 items-center justify-center rounded-md bg-[#3B359E] text-white font-bold shrink-0">
                      <KeyRound className="size-3.5 sm:size-4 text-white" />
                    </div>
                    <div className="min-w-0">
                      <span className="font-mono text-[12px] sm:text-[13px] font-extrabold tracking-tight block leading-tight truncate">
                        BIND
                      </span>
                      <span className="text-[8.5px] sm:text-[9.5px] font-sans text-[#BBB9F5] block truncate">Gate 2 · Canonical Authorization</span>
                    </div>
                  </div>

                  <span
                    className={cn(
                      "font-mono text-[8.5px] sm:text-[9px] font-bold px-1.5 sm:px-2 py-0.5 rounded uppercase tracking-wider shrink-0",
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
            <div className="flex items-center justify-center gap-1.5 rounded-md border border-white/10 bg-[#202160]/60 px-2 sm:px-3 py-1 text-center w-full min-w-0">
              <LockKeyhole className="size-3 text-[#9691EC] shrink-0" />
              <span className="font-mono text-[9px] sm:text-[10px] font-semibold text-[#BBB9F5] truncate">
                AUTHORIZATION · Canonical Intent & Scheme
              </span>
            </div>

            {/* Connector Line */}
            <div className="h-1.5 w-0.5 bg-[#9691EC]/60" />

            {/* PRIMARY NODE 3: EXECUTE */}
            {(() => {
              const state = getNodeState("execute", 4);
              return (
                <div
                  className={cn(
                    "w-full flex items-center justify-between gap-2 rounded-lg p-2 sm:p-2.5 border transition-all duration-300 min-w-0",
                    state.active || state.passed
                      ? "bg-[#2C297C] border-[#9691EC] text-white shadow-md ring-2 ring-[#9691EC]/30"
                      : "bg-[#202160]/70 border-[#7771DF]/30 text-[#BBB9F5]"
                  )}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <div className="flex size-6 sm:size-7 items-center justify-center rounded-md bg-[#3B359E] text-white font-bold shrink-0">
                      <Zap className="size-3.5 sm:size-4 text-white" />
                    </div>
                    <div className="min-w-0">
                      <span className="font-mono text-[12px] sm:text-[13px] font-extrabold tracking-tight block leading-tight truncate">
                        EXECUTE
                      </span>
                      <span className="text-[8.5px] sm:text-[9.5px] font-sans text-[#BBB9F5] block truncate">Gate 3 · Payment Execution</span>
                    </div>
                  </div>

                  <span
                    className={cn(
                      "font-mono text-[8.5px] sm:text-[9px] font-bold px-1.5 sm:px-2 py-0.5 rounded uppercase tracking-wider shrink-0",
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
          <div className="h-2 w-0.5 bg-[#9691EC]/60" />
          <span className="text-[#9691EC] text-[9px] leading-none">▼</span>
        </div>

        {/* 3. EXTERNAL OUTPUTS: PAYMENT PROVIDER & AUDIT / REPLAY */}
        <div className="flex items-center gap-1.5 sm:gap-4 justify-center w-full max-w-md min-w-0">
          {/* PAYMENT PROVIDER */}
          {(() => {
            const state = getNodeState("payment", 5);
            return (
              <div
                className={cn(
                  "flex-1 min-w-0 flex items-center gap-1.5 sm:gap-2 rounded-lg px-2 sm:px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#202160] border-[#9691EC] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <CreditCard className="size-3.5 sm:size-4 text-[#9691EC] shrink-0" />
                <div className="min-w-0">
                  <span className="font-mono text-[10px] sm:text-[11px] font-bold block leading-tight truncate">PAYMENT PROVIDER</span>
                  <span className="text-[8px] sm:text-[8.5px] font-mono text-[#BBB9F5]/80 block truncate">Provider Evidence</span>
                </div>
              </div>
            );
          })()}

          <span className="text-[#9691EC] font-mono text-xs shrink-0">➔</span>

          {/* AUDIT / REPLAY */}
          {(() => {
            const state = getNodeState("audit", 6);
            return (
              <div
                className={cn(
                  "flex-1 min-w-0 flex items-center gap-1.5 sm:gap-2 rounded-lg px-2 sm:px-3 py-1.5 border backdrop-blur-sm transition-all duration-200",
                  state.active || state.passed
                    ? "bg-[#059669]/20 border-[#059669] text-white shadow-xs"
                    : "bg-[#15183F]/80 border-white/10 text-[#BBB9F5]/70"
                )}
              >
                <FileCheck className="size-3.5 sm:size-4 text-[#059669] shrink-0" />
                <div className="min-w-0">
                  <span className="font-mono text-[10px] sm:text-[11px] font-bold block leading-tight truncate">AUDIT / REPLAY</span>
                  <span className="text-[8px] sm:text-[8.5px] font-mono text-[#059669] block truncate">Decision Trace</span>
                </div>
              </div>
            );
          })()}
        </div>

      </div>

      {/* Footer Status Bar */}
      <div className="relative z-10 mt-2.5 flex flex-wrap items-center justify-between gap-1.5 pt-2 border-t border-white/10 text-[9.5px] sm:text-[10px] font-mono text-[#BBB9F5] min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-white font-semibold">ACTIVE STAGE:</span>
          <span className="px-1.5 py-0.5 rounded bg-[#3B359E] text-white font-bold uppercase text-[9px]">
            {stepId}
          </span>
        </div>
        <div className="text-[8.5px] sm:text-[9.5px] text-[#BBB9F5]/80 break-words">
          Deterministic 3-Gate Control • Replayable Audit Chain
        </div>
      </div>
    </div>
  );
}
