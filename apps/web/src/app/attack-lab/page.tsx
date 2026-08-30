import type { Metadata } from "next";
import { Terminal } from "lucide-react";

import { AttackLabExplorer } from "@/components/attack/AttackLabExplorer";
import { BenchmarkProvenance, RunnerNotConnected } from "@/components/benchmark/BenchmarkHeader";
import { CategoryBreakdown } from "@/components/command/CategoryBreakdown";
import { SecuritySummary } from "@/components/command/SecuritySummary";
import { NAV_ITEMS } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { Panel } from "@/components/ui/Panel";
import { loadAttackReport } from "@/lib/api/reports";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Attack Lab" };

/**
 * The Adversarial Test Lab.
 *
 * There is no "run attack" button and there will not be one in this phase. The
 * harness has no HTTP surface (AL-06) and no safe demo runner exists, so a
 * button here would either invent a production attack endpoint or fake an
 * execution. Both are worse than the honest alternative: display a recorded run
 * and say plainly that the runner is not connected.
 */
export default async function AttackLabPage() {
  const attack = await loadAttackReport();
  const blurb = NAV_ITEMS.find((item) => item.href === "/attack-lab")?.blurb;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Adversarial Test Lab"
        title="Attacks, and what the kernel did about them"
        description={blurb}
        actions={<Badge tone="advisory" variant="outline">RUNNER NOT CONNECTED</Badge>}
      />

      <Panel
        title="Execution model"
        subtitle="Why this page shows a recorded run rather than a live one."
      >
        <div className="grid gap-4 lg:grid-cols-[1.25fr_1fr]">
          <p className="text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
            The attack lab is a CLI harness. It builds hostile inputs and drives them through the
            real kernel — it never turns a control off to make a scenario reach further. It has no
            HTTP endpoint, and that is a decision rather than an omission: an ingress route would be
            an unauthenticated front door accepting arbitrary adversarial payloads, and PACTRA has
            no authentication layer to gate one.
            <br />
            <br />
            So this console displays the most recent recorded run and labels it as development
            evidence. It does not execute attacks, and it does not simulate executing them. Wiring a
            safe demo runner is Phase 10 work; the surface here is built to receive one without
            changing what any of these components claim.
          </p>
          <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
            <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-ink-4)]">
              <Terminal aria-hidden className="size-3.5" />
              Produce a run
            </p>
            <pre className="num overflow-x-auto text-[11px] leading-relaxed text-[color:var(--color-ink-2)]">
{`# every scenario, ten iterations, PostgreSQL required
python -m services.attack_lab.run \\
  --all --iterations 10 --require-postgres \\
  --out reports/attack-lab/run.json

# the pinned 47-scenario Phase 6 baseline
python -m services.attack_lab.run --phase6-baseline`}
            </pre>
            <p className="mt-2 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
              Reports are gitignored on purpose: a benchmark committed by default becomes a number
              nobody re-measures.
            </p>
          </div>
        </div>
      </Panel>

      {attack.available ? (
        <>
          <BenchmarkProvenance
            runId={attack.report.run_id}
            harnessVersion={attack.report.harness_version}
            startedAt={attack.report.started_at}
            scenarios={attack.report.scenarios_selected}
            iterations={attack.report.iterations}
            sourceFile={attack.sourceFile}
          />
          <SecuritySummary metrics={attack.report.metrics} />
          <CategoryBreakdown categories={attack.report.metrics.by_category} />
          <AttackLabExplorer report={attack.report} />

          {attack.report.known_limitations.length > 0 ? (
            <Panel
              id="limitations"
              title="Known limitations reported by this run"
              subtitle="Not findings. A finding is a defect that should be fixed; a limitation is something the design cannot do and does not claim to do. They are separate structures with separate sections in every report, so honest disclosure never looks like breakage."
            >
              <div className="grid gap-3 xl:grid-cols-2">
                {attack.report.known_limitations.map((limitation) => (
                  <LimitationCard
                    key={limitation.id}
                    id={limitation.id}
                    title={limitation.title}
                    detail={limitation.detail}
                    demonstratedBy={limitation.demonstrated_by}
                    register="SECURITY CONTRACT"
                  />
                ))}
              </div>
            </Panel>
          ) : null}
        </>
      ) : (
        <Panel title="Adversarial evaluation">
          <RunnerNotConnected detail={attack.detail} />
        </Panel>
      )}
    </div>
  );
}
