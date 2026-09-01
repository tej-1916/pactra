import Link from "next/link";
import { ArrowUpRight, Boxes, Gauge, ShieldCheck } from "lucide-react";

import { BenchmarkProvenance, RunnerNotConnected } from "@/components/benchmark/BenchmarkHeader";
import { CategoryBreakdown } from "@/components/command/CategoryBreakdown";
import { PostureBanner } from "@/components/command/PostureBanner";
import { RecentMissions } from "@/components/command/RecentMissions";
import { SecuritySummary } from "@/components/command/SecuritySummary";
import { AuthorityClaim, StagePipeline } from "@/components/command/StagePipeline";
import { SystemStatus } from "@/components/command/SystemStatus";
import { Hero } from "@/components/hero/Hero";
import { DarkProductSection } from "@/components/hero/DarkProductSection";
import { PactraBootReveal } from "@/components/motion/PactraBootReveal";
import { Badge } from "@/components/ui/Badge";
import { DataTierBadge } from "@/components/ui/DataTier";
import { InvariantCard } from "@/components/ui/InvariantCard";
import { MetricCard } from "@/components/ui/MetricCard";
import { PageContainer } from "@/components/ui/PageContainer";
import { Panel } from "@/components/ui/Panel";
import { ProtocolStatusBadge } from "@/components/ui/StatusBadges";
import { loadAttackReport, loadRiskEvaluation } from "@/lib/api/reports";
import { count, percent } from "@/lib/format";
import { headlineInvariants, PROTOCOL_SUPPORT } from "@/lib/reference";

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const [attack, risk] = await Promise.all([loadAttackReport(), loadRiskEvaluation()]);
  const invariants = headlineInvariants();

  return (
    <PageContainer variant="standard" className="space-y-8">
      {/* Boot Wireframe Edge-Scan Transition (Initial Hard Load) */}
      <PactraBootReveal />

      {/* Step 3 & 4: Deep Indigo Visual Foundation + Hero + Signature Trust Graph */}
      <Hero />

      <PostureBanner />

      {/* Step 12: High-Impact Dark-Indigo Product Visualization Region */}
      <DarkProductSection />

      <Panel
        title="ADMIT → BIND → EXECUTE"
        subtitle="The three stages every mission passes through, and the three questions the Decision Trace answers about each one. The same stage names appear on every screen in this console."
      >
        <div className="space-y-3">
          <StagePipeline />
          <AuthorityClaim />
        </div>
      </Panel>

      <SystemStatus />

      <Panel
        title="Critical invariants — the test contract"
        subtitle="The properties that must hold even when the reasoning layer, merchant input, or a participating agent is compromised. Parsed from the project's published contract, not written for this screen."
        actions={<DataTierBadge tier="generated" />}
      >
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
          {invariants.map((invariant) => (
            <InvariantCard key={invariant} invariant={invariant} />
          ))}
        </div>
        <p className="mt-3 text-[11.5px] text-[color:var(--color-ink-4)]">
          <Link href="/system" className="text-[color:var(--color-accent)] hover:underline">
            The full contract
          </Link>{" "}
          — eleven invariants — is on the System page, alongside the documented boundaries of what
          each one does and does not claim.
        </p>
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
        </>
      ) : (
        <Panel title="Measured security posture" actions={<DataTierBadge tier="benchmark" />}>
          <RunnerNotConnected detail={attack.detail} />
        </Panel>
      )}

      <div className="grid items-start gap-5 xl:grid-cols-[1.35fr_1fr]">
        <RecentMissions />

        <div className="space-y-5">
          <Panel
            title="Advisory risk engine"
            subtitle="Risk is advisory. A score is never an authority — the deterministic policy engine owns every decision."
            actions={<Badge tone="advisory" variant="outline">ADVISORY ONLY</Badge>}
          >
            {risk.available ? (
              <div className="space-y-3">
                <div className="grid gap-2.5 sm:grid-cols-2">
                  <MetricCard
                    label="Assessments measured"
                    value={count(risk.report.outcomes.length)}
                    denominator={`${count(risk.report.scenarios_selected)} scenarios × ${risk.report.iterations} iterations`}
                    tone="accent"
                    icon={<Gauge aria-hidden className="size-3.5" />}
                  />
                  <MetricCard
                    label="Score semantics"
                    value="RISK INDEX"
                    denominator={`${risk.report.engine_version} · ${risk.report.model_type}`}
                    tone="neutral"
                    hint="A normalized index in [0,1] — not a probability and not a fraud likelihood."
                  />
                </div>
                <p className="rounded border border-[color:var(--color-advisory)]/25 bg-[color:var(--color-advisory)]/[0.05] p-3 text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">
                  {risk.report.data_disclosure}
                </p>
                <Link
                  href="/risk"
                  className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[color:var(--color-accent)] hover:underline"
                >
                  Risk intelligence, factors and methodology
                  <ArrowUpRight aria-hidden className="size-3" />
                </Link>
              </div>
            ) : (
              <RunnerNotConnected detail={risk.detail} what="risk evaluation harness" />
            )}
          </Panel>

          <Panel
            title="Protocol adapter surface"
            subtitle="What PACTRA can translate, stated at the granularity the code supports."
            actions={<DataTierBadge tier="generated" />}
          >
            <ul className="space-y-1.5">
              {PROTOCOL_SUPPORT.map((entry) => (
                <li
                  key={entry.protocol}
                  className="flex items-center justify-between gap-3 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2"
                >
                  <span className="num truncate text-[12px] text-[color:var(--color-ink)]">
                    {entry.protocol}
                  </span>
                  <ProtocolStatusBadge status={entry.status} />
                </li>
              ))}
            </ul>
            <Link
              href="/adapters"
              className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-medium text-[color:var(--color-accent)] hover:underline"
            >
              <Boxes aria-hidden className="size-3.5" />
              Exactly what each status means
              <ArrowUpRight aria-hidden className="size-3" />
            </Link>
          </Panel>
        </div>
      </div>

      {attack.available && attack.report.known_limitations.length > 0 ? (
        <Panel
          title="Declared boundaries of the security contract"
          subtitle="Reported on every run, and never counted as blocked attacks. Credibility comes from stating these, not from omitting them."
          actions={
            <Badge tone="advisory" variant="outline" icon={<ShieldCheck aria-hidden className="size-3.5" />}>
              {attack.report.known_limitations.length} DISCLOSED
            </Badge>
          }
        >
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {attack.report.known_limitations.map((limitation) => (
              <li
                key={limitation.id}
                className="rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2.5"
              >
                <code className="num text-[10.5px] text-[color:var(--color-ink-4)]">{limitation.id}</code>
                <p className="mt-1 text-[12px] leading-snug text-[color:var(--color-ink-2)]">
                  {limitation.title}
                </p>
              </li>
            ))}
          </ul>
          <Link
            href="/system#limitations"
            className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-medium text-[color:var(--color-accent)] hover:underline"
          >
            Read each one in full
            <ArrowUpRight aria-hidden className="size-3" />
          </Link>
        </Panel>
      ) : null}

      {attack.available ? (
        <p className="text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
          Benchmark figures on this page describe run{" "}
          <code className="num">{attack.report.run_id}</code>, measured{" "}
          {new Date(attack.report.started_at).toISOString().slice(0, 10)} over{" "}
          {count(attack.report.metrics.total_runs)} runs. They are development evidence about that
          run — not live system health, and not a claim about production enforcement. Latency in
          particular is harness-local (KL-07). Where a rate had no denominator it reads{" "}
          <code className="num">n/a</code> rather than {percent(0)}.
        </p>
      ) : null}
    </PageContainer>
  );
}
