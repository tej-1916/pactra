"use client";

import { motion } from "framer-motion";
import { ArrowRight, Ban, KeyRound, Wallet } from "lucide-react";

import { StageMarker } from "@/components/trace/TraceBadges";
import { cn } from "@/lib/format";
import { STAGE_PRESENTATION } from "@/lib/trace";
import { DECISION_STAGES, type DecisionStage } from "@/lib/types/pactra";

const STAGE_ICON: Record<DecisionStage, typeof Ban> = {
  ADMIT: Ban,
  BIND: KeyRound,
  EXECUTE: Wallet,
};

/**
 * ADMIT → BIND → EXECUTE, as the product model rather than as a diagram.
 *
 * The three stages are the spine of the whole system: the same names appear on
 * the Decision Trace, in the audit projection and in the backend's stage map,
 * and this component draws them from the same frozen constant so the overview
 * cannot drift from the trace it introduces.
 *
 * The motion here is an entrance and nothing else. Each stage arrives once, in
 * order, which reads as "these happen in sequence" — and then it stops. A
 * pipeline that pulses forever teaches nothing on the second look.
 */
export function StagePipeline({ className }: { className?: string }) {
  return (
    <div className={cn("grid gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr]", className)}>
      {DECISION_STAGES.map((stage, index) => {
        const Icon = STAGE_ICON[stage];
        return (
          <div key={stage} className="contents">
            {index > 0 ? (
              <motion.div
                aria-hidden
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.3, delay: 0.12 + index * 0.12 }}
                className="hidden items-center justify-center text-[color:var(--color-ink-4)] lg:flex"
              >
                <ArrowRight className="size-4" />
              </motion.div>
            ) : null}

            <motion.section
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, delay: index * 0.12, ease: "easeOut" }}
              aria-label={`${stage} stage`}
              className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface)] p-3.5"
            >
              <div className="flex items-center gap-2">
                <Icon aria-hidden className="size-4 shrink-0 text-[color:var(--color-accent)]" />
                <StageMarker stage={stage} active />
              </div>
              <p className="mt-2 text-[12.5px] leading-snug font-semibold text-[color:var(--color-ink)]">
                {STAGE_PRESENTATION[stage].question}
              </p>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
                {STAGE_PRESENTATION[stage].purpose}
              </p>
            </motion.section>
          </div>
        );
      })}
    </div>
  );
}

/**
 * The product claim, stated in the three sentences the project actually makes.
 *
 * Kept beside the pipeline because the pipeline alone does not say WHY the
 * middle term is the one that matters.
 */
export function AuthorityClaim({ className }: { className?: string }) {
  return (
    <ul
      className={cn(
        "grid gap-2 text-[12.5px] leading-relaxed sm:grid-cols-3",
        className,
      )}
    >
      <li className="rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2.5 text-[color:var(--color-ink-2)]">
        AI may <span className="font-semibold text-[color:var(--color-ink)]">propose and select</span>.
      </li>
      <li className="rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2.5 text-[color:var(--color-ink-2)]">
        PACTRA controls{" "}
        <span className="font-semibold text-[color:var(--color-secure)]">authority and payments</span>.
      </li>
      <li className="rounded-md border border-[color:var(--color-critical)]/30 bg-[color:var(--color-critical)]/[0.05] px-3 py-2.5 text-[color:var(--color-ink-2)]">
        The model is{" "}
        <span className="font-semibold text-[color:var(--color-critical)]">never the security boundary</span>.
      </li>
    </ul>
  );
}
