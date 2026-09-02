"use client";

import { useState } from "react";
import { motion, type Variants } from "framer-motion";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { SignatureTrustGraph } from "./SignatureTrustGraph";
import { TrustRail } from "./TrustRail";

// Static SSR-stable Animation Variants
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
  hidden: { opacity: 0, y: 6 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.3, ease: [0, 0, 0.2, 1] },
  },
};

const graphVariants: Variants = {
  hidden: { opacity: 0, scale: 0.985 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.4, delay: 0.2, ease: [0, 0, 0.2, 1] },
  },
};

export function Hero() {
  const [activeStage, setActiveStage] = useState<"admit" | "bind" | "execute" | "completed">("admit");

  return (
    <div className="relative w-full min-w-0 max-w-full overflow-hidden rounded-2xl border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-4 sm:p-8 lg:p-10 shadow-sm">
      {/* Infrastructure Dot Grid Background for Light Area */}
      <div className="pactra-dot-grid-light absolute inset-0 pointer-events-none opacity-30" />

      {/* Atmospheric Illumination Glow */}
      <div className="absolute top-1/3 right-1/4 size-96 rounded-full bg-radial from-[#7C78E2]/10 via-[#4B42B9]/05 to-transparent blur-3xl pointer-events-none" />

      {/* Desktop 2-column, Tablet/Mobile 1-column layout */}
      <div className="relative z-10 grid gap-6 sm:gap-8 lg:grid-cols-12 lg:items-center min-w-0 max-w-full">
        {/* LEFT COLUMN: Copy & Trust Rail */}
        <motion.div
          className="lg:col-span-6 flex flex-col justify-between space-y-5 sm:space-y-6 min-w-0 w-full max-w-full"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <div className="space-y-3.5 sm:space-y-4 min-w-0 w-full">
            {/* Eyebrow */}
            <motion.div variants={itemVariants} className="inline-flex items-center gap-2 max-w-full">
              <span className="flex size-2 rounded-full bg-[#4B42B9] shrink-0" />
              <span className="label-xs text-[color:var(--pactra-indigo-bright)] break-words">
                TRUST INFRASTRUCTURE FOR AGENTIC COMMERCE
              </span>
            </motion.div>

            {/* Headline */}
            <motion.h1
              variants={itemVariants}
              className="font-display text-2xl xs:text-3xl sm:text-5xl lg:text-5xl font-extrabold tracking-tight text-[color:var(--pactra-ink)] leading-[1.15] sm:leading-[1.1] break-words"
            >
              Make AI commerce{" "}
              <span className="gradient-headline block sm:inline">
                trustworthy.
              </span>
            </motion.h1>

            {/* Supporting Copy */}
            <motion.p
              variants={itemVariants}
              className="text-sm sm:text-base lg:text-lg leading-relaxed text-[color:var(--pactra-ink-secondary)] max-w-xl break-words"
            >
              PACTRA verifies every AI-initiated transaction through admission, binding, and execution controls — then records the result in a replayable audit trail.
            </motion.p>

            {/* CTAs */}
            <motion.div variants={itemVariants} className="flex flex-col xs:flex-row items-stretch xs:items-center gap-2.5 sm:gap-3 pt-2 w-full">
              <Button variant="primary" showArrow href="/missions" className="w-full xs:w-auto justify-center">
                Open dashboard
              </Button>
              <Button
                variant="secondary"
                showArrow
                href="/commerce"
                icon={<Play className="size-3.5 text-[color:var(--pactra-indigo)] shrink-0" />}
                className="w-full xs:w-auto justify-center"
              >
                Explore live commerce
              </Button>
            </motion.div>
          </div>

          {/* Synchronized Trust Rail */}
          <motion.div variants={itemVariants} className="pt-2 w-full min-w-0">
            <TrustRail activeStage={activeStage} />
          </motion.div>
        </motion.div>

        {/* RIGHT COLUMN: Signature Trust Graph */}
        <motion.div
          className="lg:col-span-6 w-full min-w-0 max-w-full"
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
