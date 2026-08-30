import { Activity, AlertOctagon, Percent, ShieldCheck, Timer, TriangleAlert } from "lucide-react";

import { MetricCard } from "@/components/ui/MetricCard";
import { Panel } from "@/components/ui/Panel";
import { count, ms, percent } from "@/lib/format";
import type { AttackMetrics } from "@/lib/types/benchmark";

/**
 * The measured security posture from one recorded harness run.
 *
 * Every rate prints with the counts it was computed from, because a block rate
 * over three runs must not look like one over six hundred and thirty. Rates the
 * harness reported as `null` print as `n/a`.
 *
 * Note what is NOT here: a test count. `1272 tests passing` is a development
 * verification metric about the repository, not a statement about a running
 * system, and mixing it into a posture panel is how the two stop being
 * distinguishable.
 */
export function SecuritySummary({ metrics }: { metrics: AttackMetrics }) {
  const clean = metrics.attacks_not_blocked === 0 && metrics.controls_blocked === 0;

  return (
    <Panel
      id="security-posture"
      title="Measured security posture"
      subtitle="Derived from the most recent adversarial evaluation on disk. Development evidence — not runtime health."
      actions={
        clean ? (
          <span className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-secure)]/40 bg-[color:var(--color-secure)]/10 px-2 py-1 text-[11px] font-semibold text-[color:var(--color-secure)]">
            <ShieldCheck aria-hidden className="size-3.5" />
            NO MALICIOUS SCENARIO WENT THROUGH
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded border border-[color:var(--color-critical)]/40 bg-[color:var(--color-critical)]/10 px-2 py-1 text-[11px] font-semibold text-[color:var(--color-critical)]">
            <AlertOctagon aria-hidden className="size-3.5" />
            SECURITY FAILURE IN THIS RUN
          </span>
        )
      }
    >
      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Attack block rate"
          value={percent(metrics.attack_block_rate)}
          denominator={`${count(metrics.attacks_blocked)} / ${count(metrics.valid_attack_runs)} decisive hostile runs`}
          tone={metrics.attacks_not_blocked === 0 ? "secure" : "critical"}
          icon={<ShieldCheck aria-hidden className="size-3.5" />}
          hint="Blocked hostile runs over hostile runs that reached a verdict. ERROR and INCONCLUSIVE runs are excluded from the denominator, never counted on the safe side."
        />
        <MetricCard
          label="Benign controls allowed"
          value={`${count(metrics.controls_allowed)} / ${count(metrics.valid_control_runs)}`}
          denominator={`false-positive rate ${percent(metrics.false_positive_rate)}`}
          tone={metrics.controls_blocked === 0 ? "secure" : "critical"}
          icon={<Percent aria-hidden className="size-3.5" />}
          hint="For a benign control, being BLOCKED is the failure. Without controls there is no honest false-positive rate."
        />
        <MetricCard
          label="Invariant preservation"
          value={percent(metrics.invariant_preservation_rate)}
          denominator={`over ${count(metrics.invariant_checked_runs)} runs that measured one`}
          tone="secure"
          icon={<Activity aria-hidden className="size-3.5" />}
        />
        <MetricCard
          label="Reason-code match"
          value={percent(metrics.reason_match_rate)}
          denominator={`${count(metrics.reason_code_matches)} / ${count(metrics.reason_code_checked_runs)} runs with an expectation`}
          tone="accent"
          hint="Whether the control that refused produced the reason code the scenario declared. A block for the wrong reason is not the same control."
        />
        <MetricCard
          label="Replay attacks succeeding"
          value={count(metrics.replay_unauthorized_effects)}
          denominator={`over ${count(metrics.replay_attempts)} replay attempts`}
          tone={metrics.replay_unauthorized_effects === 0 ? "secure" : "critical"}
        />
        <MetricCard
          label="Duplicate payments observed"
          value={count(metrics.duplicate_payment_observations)}
          denominator={`over ${count(metrics.duplicate_payment_attempts)} duplicate attempts`}
          tone={metrics.duplicate_payment_observations === 0 ? "secure" : "critical"}
        />
        <MetricCard
          label="Errored / inconclusive"
          value={`${count(metrics.errors)} / ${count(metrics.inconclusive)}`}
          denominator={`of ${count(metrics.total_runs)} total runs`}
          tone={metrics.errors === 0 ? "neutral" : "critical"}
          icon={<TriangleAlert aria-hidden className="size-3.5" />}
          hint="An exception is not a block, and an unestablished precondition is not a secure result. Both are reported separately."
        />
        <MetricCard
          label="Enforcement latency p95"
          value={ms(metrics.latency.p95_ms)}
          denominator={`p50 ${ms(metrics.latency.p50_ms)} · ${count(metrics.latency.samples)} samples`}
          tone="neutral"
          icon={<Timer aria-hidden className="size-3.5" />}
          hint="KL-07: harness-local, in-process, no network and no concurrent load. Useful for spotting a regression in this harness; not a claim about deployed latency."
        />
      </div>
    </Panel>
  );
}
