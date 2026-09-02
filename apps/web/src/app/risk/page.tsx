import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { RunnerNotConnected } from "@/components/benchmark/BenchmarkHeader";
import { EvaluationDisclosure } from "@/components/risk/EvaluationDisclosure";
import { RiskExplorer } from "@/components/risk/RiskExplorer";
import { AuthoritySeparationDiagram } from "@/components/risk/AuthoritySeparationDiagram";
import { DemoAdvisorySignals } from "@/components/risk/DemoAdvisorySignals";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { PageContainer } from "@/components/ui/PageContainer";
import { loadRiskEvaluation } from "@/lib/api/reports";
import { VOCABULARY } from "@/lib/reference";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Risk & Advisory" };

export default async function RiskPage() {
  const evaluation = await loadRiskEvaluation();

  return (
    <PageContainer variant="wide">
      <div className="space-y-6">
        <PageHeader
          eyebrow="RISK & ADVISORY"
          title="Signals for operator context — never transaction authority."
          description="Advisory scoring provides informational telemetry and risk indices for human operators and workflows without granting or denying transaction authority."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="advisory" variant="outline">
                ADVISORY ONLY
              </Badge>
              <Badge tone="secure" variant="outline">
                RISK SCORE ≠ AUTHORITY
              </Badge>
            </div>
          }
        />

        {/* 1. Authority Separation Architecture */}
        <AuthoritySeparationDiagram />

        {/* 2. Demo Advisory Signals Grid */}
        <DemoAdvisorySignals />

        {/* 3. Structural Guarantees */}
        <Panel
          title="The advisory boundary is structural, not a convention"
          subtitle="It is enforced by the type system and the import graph, not by a comment asking callers to behave."
        >
          <div className="grid gap-4 lg:grid-cols-3">
            <Point
              title="No ALLOW, no DENY"
              body={`The recommendation vocabulary is ${VOCABULARY.riskRecommendations.join(", ")}. Every member names an action taken by somebody else. ALLOW, REQUIRE_APPROVAL, and DENY belong strictly to the policy engine, so a risk value cannot be pattern-matched into a policy branch.`}
            />
            <Point
              title="A score cannot arrive from outside"
              body="Neither risk route accepts a request body. There is no Pydantic model bound to either handler, so a caller-supplied score, band, threshold, or weight has nowhere to land. Weights come only from a frozen, module-owned config."
            />
            <Point
              title="CRITICAL still returns 200"
              body="A high risk band changes no response status and aborts no mission. An advisory layer that returned 403 would be enforcing — which is the exact thing this layer exists not to be."
            />
          </div>
        </Panel>

        {/* 4. Runtime Mission Risk Assessment */}
        <Panel
          title="Runtime Mission Risk Assessment"
          subtitle="Query or record advisory assessment for missions created on this browser session."
        >
          <RiskExplorer />
        </Panel>

        {/* 5. Cross-Page Navigation */}
        <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-display text-[13.5px] font-bold text-[color:var(--pactra-ink)]">
              Explore Live Commerce Adjudication
            </h3>
            <p className="text-[11.5px] text-[color:var(--pactra-ink-secondary)]">
              See how advisory signals are kept strictly separate from deterministic policy evaluations in the Live Commerce Workbench.
            </p>
          </div>
          <Link
            href="/commerce"
            className="inline-flex items-center gap-1.5 rounded-md border border-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/15 px-3.5 py-1.5 font-mono text-[12px] font-bold text-[color:var(--pactra-indigo)] transition-colors hover:bg-[color:var(--pactra-indigo)]/25"
          >
            Open Live Commerce
            <ArrowRight className="size-3.5" />
          </Link>
        </div>

        {/* 6. Evaluation Harness Report */}
        {evaluation.available ? (
          <EvaluationDisclosure report={evaluation.report} sourceFile={evaluation.sourceFile} />
        ) : (
          <Panel title="Evaluation">
            <RunnerNotConnected detail={evaluation.detail} what="risk evaluation harness" />
          </Panel>
        )}
      </div>
    </PageContainer>
  );
}

function Point({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-3.5">
      <h3 className="text-[12.5px] font-semibold tracking-tight text-[color:var(--pactra-ink)]">{title}</h3>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">{body}</p>
    </div>
  );
}
