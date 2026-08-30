import { AlertTriangle, FlaskConical } from "lucide-react";

import { BenchmarkProvenance } from "@/components/benchmark/BenchmarkHeader";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { MetricCard } from "@/components/ui/MetricCard";
import { Panel } from "@/components/ui/Panel";
import { count, percent } from "@/lib/format";
import { LIMITATIONS } from "@/lib/reference";
import type { RiskEvalReport } from "@/lib/types/benchmark";

/**
 * The evaluation, and what it is worth.
 *
 * The disclosure is printed FIRST and verbatim, before any metric, because a
 * detection rate read before its corpus disclosure has already been misread. The
 * corpus is synthetic, its labels are authored, and there is no held-out set —
 * so the numbers below measure whether a deterministic heuristic reproduces on a
 * corpus written to exercise it, and nothing else.
 */
export function EvaluationDisclosure({
  report,
  sourceFile,
}: {
  report: RiskEvalReport;
  sourceFile: string;
}) {
  const metrics = report.metrics as Record<string, number | boolean | undefined>;
  const num = (key: string): number | null =>
    typeof metrics[key] === "number" ? (metrics[key] as number) : null;

  return (
    <div className="space-y-4">
      <BenchmarkProvenance
        runId={report.run_id}
        harnessVersion={report.harness_version}
        startedAt={report.started_at}
        scenarios={report.scenarios_selected}
        iterations={report.iterations}
        sourceFile={sourceFile}
      />

      <Panel
        title="Evaluation disclosure — read this before the numbers"
        subtitle="Stated up front rather than in a footnote, because a detection rate read before its corpus disclosure has already been misread."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-advisory)]/40 bg-[color:var(--color-advisory)]/10 px-2 py-1 text-[11px] font-semibold text-[color:var(--color-advisory)]">
            <AlertTriangle aria-hidden className="size-3.5" />
            SYNTHETIC CORPUS
          </span>
        }
      >
        <p className="max-w-[92ch] rounded border border-[color:var(--color-advisory)]/25 bg-[color:var(--color-advisory)]/[0.05] p-3.5 text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
          {report.data_disclosure}
        </p>

        <dl className="mt-4 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <Fact label="Evaluation dataset" value="SYNTHETIC" />
          <Fact label="Labels" value="AUTHORED" />
          <Fact label="Scenario families" value={count(report.scenarios_selected)} />
          <Fact label="Iterations" value={`×${report.iterations}`} />
          <Fact label="Assessments" value={count(report.outcomes.length)} />
          <Fact label="Held-out real-world fraud data" value="NONE" tone="critical" />
          <Fact label="Engine" value={report.engine_version} />
          <Fact label="Score semantics" value={report.score_semantics} />
        </dl>

        <p className="mt-3 flex items-start gap-2 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
          <FlaskConical aria-hidden className="mt-[2px] size-3.5 shrink-0" />
          This is a development benchmark, not a real-world fraud-detection accuracy. It measures
          whether a deterministic heuristic reproduces on a corpus constructed to exercise it. It
          cannot measure generalization, and nothing here should be read as if it could.
        </p>
      </Panel>

      <Panel
        title="Measured on the synthetic corpus"
        subtitle="Metric formulas were fixed before the numbers. The harness exits non-zero only if a scenario failed to execute or a score did not reproduce — never because a detection rate was poor, which would create pressure to report a flattering number instead of an honest one."
      >
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Risk detection rate"
            value={percent(num("risk_detection_rate"))}
            denominator={`${count(num("risky_flagged"))} / ${count(num("risky_runs"))} authored-RISKY runs`}
            tone="accent"
            hint="On an authored corpus. Not a fraud-detection rate."
          />
          <MetricCard
            label="False positive rate"
            value={percent(num("false_positive_rate"))}
            denominator={`${count(num("benign_flagged"))} / ${count(num("benign_runs"))} authored-BENIGN runs`}
            tone="accent"
          />
          <MetricCard
            label="Mean separation"
            value={(num("mean_separation") ?? 0).toFixed(3)}
            denominator={`risky ${(num("risky_mean_score") ?? 0).toFixed(3)} vs benign ${(num("benign_mean_score") ?? 0).toFixed(3)}`}
            tone="neutral"
            hint="The corpus is trivially separable, which is why this gap is wide. Stated because it changes the reading."
          />
          <MetricCard
            label="Deterministic across iterations"
            value={metrics.deterministic_across_iterations ? "YES" : "NO"}
            denominator={`review threshold ${(num("review_threshold") ?? 0).toFixed(2)}`}
            tone={metrics.deterministic_across_iterations ? "secure" : "critical"}
            hint="What ten iterations actually measure: reproducibility of a deterministic function, not statistical confidence."
          />
        </div>
      </Panel>

      <Panel
        title="Declared boundaries of the measurement"
        subtitle="Kept separate from the security-contract limitations, because a boundary of a MEASUREMENT is a different kind of claim from a boundary of a SECURITY GUARANTEE."
      >
        <div className="grid gap-3 xl:grid-cols-2">
          {LIMITATIONS.risk.map((limitation) => (
            <LimitationCard
              key={limitation.id}
              id={limitation.id}
              title={limitation.title}
              detail={limitation.detail}
              demonstratedBy={limitation.demonstratedBy}
              register="RISK MEASUREMENT"
            />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Fact({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "critical";
}) {
  return (
    <div className="rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2">
      <dt className="label-xs text-[color:var(--color-ink-4)]">{label}</dt>
      <dd
        className={
          tone === "critical"
            ? "num mt-0.5 text-[13px] font-semibold text-[color:var(--color-critical)]"
            : "num mt-0.5 text-[13px] font-semibold text-[color:var(--color-ink)]"
        }
      >
        {value}
      </dd>
    </div>
  );
}
