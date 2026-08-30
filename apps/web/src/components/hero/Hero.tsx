"use client";

import { useState } from "react";
import { motion, useReducedMotion, type Variants } from "framer-motion";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SignatureTrustGraph } from "./SignatureTrustGraph";
import { TrustRail } from "./TrustRail";

export function Hero() {
  const [activeStage, setActiveStage] = useState<"admit" | "bind" | "execute" | "completed">("admit");
  const shouldReduceMotion = useReducedMotion();

  // Load Animation Stagger Variants (Step 10)
  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1,
        delayChildren: 0.05,
      },
    },
  };

  const itemVariants: Variants = {
    hidden: shouldReduceMotion ? { opacity: 1, y: 0 } : { opacity: 0, y: 6 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.3, ease: [0, 0, 0.2, 1] },
    },
  };

  const graphVariants: Variants = {
    hidden: shouldReduceMotion ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.985 },
    visible: {
      opacity: 1,
      scale: 1,
      transition: { duration: 0.4, delay: 0.2, ease: [0, 0, 0.2, 1] },
    },
  };

  return (
    <div className="relative w-full overflow-hidden rounded-2xl border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-6 sm:p-8 lg:p-10 shadow-sm">
      {/* Infrastructure Dot Grid Background for Light Area (Step 5) */}
      <div className="pactra-dot-grid-light absolute inset-0 pointer-events-none opacity-30" />

      {/* Atmospheric Illumination Glow */}
      <div className="absolute top-1/3 right-1/4 size-96 rounded-full bg-radial from-[#7C78E2]/10 via-[#4B42B9]/05 to-transparent blur-3xl pointer-events-none" />

      {/* Desktop 2-column, Tablet/Mobile 1-column layout (Step 16) */}
      <div className="relative z-10 grid gap-8 lg:grid-cols-12 lg:items-center">
        {/* LEFT COLUMN: Copy & Trust Rail */}
        <motion.div
          className="lg:col-span-6 flex flex-col justify-between space-y-6"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <div className="space-y-4">
            {/* Eyebrow */}
            <motion.div variants={itemVariants} className="inline-flex items-center gap-2">
              <span className="flex size-2 rounded-full bg-[#4B42B9]" />
              <span className="label-xs text-[color:var(--pactra-indigo-bright)]">
                TRUST INFRASTRUCTURE FOR AGENTIC COMMERCE
              </span>
            </motion.div>

            {/* Headline */}
            <motion.h1
              variants={itemVariants}
              className="font-display text-3xl sm:text-5xl lg:text-5xl font-extrabold tracking-tight text-[color:var(--pactra-ink)] leading-[1.1]"
            >
              Make AI commerce{" "}
              <span className="gradient-headline block sm:inline">
                trustworthy.
              </span>
            </motion.h1>

            {/* Supporting Copy */}
            <motion.p
              variants={itemVariants}
              className="text-base sm:text-lg leading-relaxed text-[color:var(--pactra-ink-secondary)] max-w-xl"
            >
              PACTRA verifies every AI-initiated transaction through admission, binding, and execution controls — then records the result in a replayable audit trail.
            </motion.p>

            {/* CTAs */}
            <motion.div variants={itemVariants} className="flex flex-wrap items-center gap-3 pt-2">
              <Button variant="primary" showArrow href="/missions">
                Open dashboard
              </Button>
              <Button
                variant="secondary"
                showArrow
                href="/commerce"
                icon={<Play className="size-3.5 text-[color:var(--pactra-indigo)]" />}
              >
                Explore live commerce
              </Button>
            </motion.div>
          </div>

          {/* Synchronized Trust Rail (Step 11) */}
          <motion.div variants={itemVariants} className="pt-2">
            <TrustRail activeStage={activeStage} />
          </motion.div>
        </motion.div>

        {/* RIGHT COLUMN: Signature Trust Graph */}
        <motion.div
          className="lg:col-span-6 w-full"
          variants={graphVariants}
          initial="hidden"
          animate="visible"
        >
          <SignatureTrustGraph activeStage={activeStage} onStageChange={setActiveStage} />
        </motion.div>
      </div>
    </div>
  );
}
