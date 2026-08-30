import type { Metadata } from "next";

import { RunnerNotConnected } from "@/components/benchmark/BenchmarkHeader";
import { EvaluationDisclosure } from "@/components/risk/EvaluationDisclosure";
import { RiskExplorer } from "@/components/risk/RiskExplorer";
import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { loadRiskEvaluation } from "@/lib/api/reports";
import { VOCABULARY } from "@/lib/reference";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Risk Intelligence" };

export default async function RiskPage() {
  const evaluation = await loadRiskEvaluation();
  const blurb = ALL_ROUTES.find((item) => item.href === "/risk")?.blurb;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Risk Intelligence"
        title="Advisory only"
        description={blurb}
        actions={<Badge tone="advisory" variant="outline">RISK SCORE ≠ AUTHORITY</Badge>}
      />

      <Panel
        title="The advisory boundary is structural, not a convention"
        subtitle="It is enforced by the type system and the import graph, not by a comment asking callers to behave."
      >
        <div className="grid gap-4 lg:grid-cols-3">
          <Point
            title="No ALLOW, no DENY"
            body={`The recommendation vocabulary is ${VOCABULARY.riskRecommendations.join(", ")}. Every member names an action taken by somebody else. ALLOW and DENY belong to the policy engine, so a risk value cannot be pattern-matched into a policy branch.`}
          />
          <Point
            title="A score cannot arrive from outside"
            body="Neither risk route accepts a request body. There is no Pydantic model bound to either handler, so a caller-supplied score, band, threshold or weight has nowhere to land. Weights come only from a frozen, module-owned config."
          />
          <Point
            title="CRITICAL still returns 200"
            body="A high band changes no response status and no mission. An advisory layer that returned 403 would be enforcing — which is the exact thing this layer exists not to be."
          />
        </div>
      </Panel>

      <RiskExplorer />

      {evaluation.available ? (
        <EvaluationDisclosure report={evaluation.report} sourceFile={evaluation.sourceFile} />
      ) : (
        <Panel title="Evaluation">
          <RunnerNotConnected detail={evaluation.detail} what="risk evaluation harness" />
        </Panel>
      )}
    </div>
  );
}

function Point({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
      <h3 className="text-[12.5px] font-semibold tracking-tight text-[color:var(--color-ink)]">{title}</h3>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">{body}</p>
    </div>
  );
}
