import { PostureBanner } from "@/components/command/PostureBanner";
import { Hero } from "@/components/hero/Hero";
import { DarkProductSection } from "@/components/hero/DarkProductSection";
import { PactraBootReveal } from "@/components/motion/PactraBootReveal";
import { PageContainer } from "@/components/ui/PageContainer";
import { WhyPactraSection } from "@/components/overview/WhyPactraSection";
import { PipelineExplainerSection } from "@/components/overview/PipelineExplainerSection";
import { InvariantsSection } from "@/components/overview/InvariantsSection";
import { DecisionTracePreviewSection } from "@/components/overview/DecisionTracePreviewSection";
import { AttackLabPreviewSection } from "@/components/overview/AttackLabPreviewSection";
import { PaymentReliabilitySection } from "@/components/overview/PaymentReliabilitySection";
import { NextActionsSection } from "@/components/overview/NextActionsSection";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  return (
    <PageContainer variant="standard" className="space-y-8">
      {/* Boot Wireframe Edge-Scan Transition (Initial Hard Load - Frozen Phase 1) */}
      <PactraBootReveal />

      {/* Step 3 & 4: Deep Indigo Visual Foundation + Hero + Signature Trust Graph (Frozen Phase 1) */}
      <Hero />

      <PostureBanner />

      {/* Step 12: High-Impact Dark-Indigo Product Visualization Region (Frozen Phase 1) */}
      <DarkProductSection />

      {/* 1. Product Thesis: Why PACTRA */}
      <WhyPactraSection />

      {/* 2. ADMIT -> BIND -> EXECUTE Pipeline Explainer */}
      <PipelineExplainerSection />

      {/* 3. Critical Security Invariants */}
      <InvariantsSection />

      {/* 4. Replayable Decision Trace & Evidence Preview */}
      <DecisionTracePreviewSection />

      {/* 5. Attack Lab Adversarial Preview */}
      <AttackLabPreviewSection />

      {/* 6. Payment Reliability & Reconciliation */}
      <PaymentReliabilitySection />

      {/* 7. Next Actions / Judge Verification Paths */}
      <NextActionsSection />
    </PageContainer>
  );
}
