"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ATTACK_SCENARIOS, type AttackScenarioId } from "./attackScenarios";
import { HarnessDisclosure } from "./HarnessDisclosure";
import { AttackScenarioSelector } from "./AttackScenarioSelector";
import { AttackVsControlPanel } from "./AttackVsControlPanel";
import { DeterministicResultPanel } from "./DeterministicResultPanel";
import { AttackTraceTimeline } from "./AttackTraceTimeline";
import { PageContainer } from "@/components/ui/PageContainer";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { ALL_ROUTES } from "@/components/shell/nav";

export function AttackLabConsole() {
  const [selectedId, setSelectedId] = useState<AttackScenarioId>("MERCHANT_PROMPT_INJECTION");
  const scenario = ATTACK_SCENARIOS[selectedId];
  const blurb = ALL_ROUTES.find((item) => item.href === "/attack-lab")?.blurb;

  return (
    <PageContainer variant="wide">
      <div className="space-y-6">
        <PageHeader
          eyebrow="ATTACK LAB"
          title="Adversarial regression against deterministic transaction boundaries"
          description={blurb ?? "Authored adversarial regression suite demonstrating PACTRA's deterministic transaction boundaries against hostile input."}
          actions={
            <Badge tone="advisory" variant="outline">
              AUTHORED HARNESS
            </Badge>
          }
        />

        {/* Harness Disclosure Banner */}
        <HarnessDisclosure />

        {/* Scenario Selector */}
        <div className="space-y-2">
          <div className="flex items-center justify-between font-mono text-[11px] text-[color:var(--pactra-ink-muted)]">
            <span className="font-bold text-white uppercase tracking-wider">
              AUTHORED SCENARIO SUITE
            </span>
            <span>4 PRIMARY REGRESSION SCENARIOS</span>
          </div>
          <AttackScenarioSelector selectedScenario={selectedId} onSelectScenario={setSelectedId} />
        </div>

        {/* Scenario Analysis Grid */}
        <AttackVsControlPanel scenario={scenario} />

        {/* Expected Deterministic Result */}
        <DeterministicResultPanel scenario={scenario} />

        {/* Decision Trace Evidence */}
        <AttackTraceTimeline entries={scenario.decisionTrace} />

        {/* Reliability Scenario Cross-Link Notice (Step 9) */}
        <div className="rounded-md border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-3 flex flex-wrap items-center justify-between gap-3 font-mono text-[11.5px]">
          <span className="text-[color:var(--pactra-ink-secondary)]">
            Provider uncertainty & lost provider response scenarios are reliability workflows, not security attacks.
          </span>
          <Link
            href="/commerce"
            className="inline-flex items-center gap-1.5 font-bold text-[color:var(--pactra-indigo)] hover:text-[#9D9BE7] transition-colors"
          >
            See provider uncertainty handling in Live Commerce
            <ArrowRight className="size-3.5" />
          </Link>
        </div>
      </div>
    </PageContainer>
  );
}
