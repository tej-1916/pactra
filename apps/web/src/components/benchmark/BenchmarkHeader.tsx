import { FlaskConical } from "lucide-react";

import { DataTierBadge } from "@/components/ui/DataTier";
import { UnavailableState } from "@/components/ui/States";
import { timestamp } from "@/lib/format";

/**
 * The banner every benchmark-derived number sits under.
 *
 * A recorded harness run is evidence about a measurement someone made, at a
 * moment, over a stated denominator. It is not runtime system health, and the
 * console is not allowed to let it read as such — so the run id, the harness
 * version, the iteration count and the wall-clock time travel with the numbers
 * wherever they go.
 */
export function BenchmarkProvenance({
  runId,
  harnessVersion,
  startedAt,
  scenarios,
  iterations,
  sourceFile,
}: {
  runId: string;
  harnessVersion: string;
  startedAt: string;
  scenarios: number;
  iterations: number;
  sourceFile: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-[color:var(--color-advisory)]/25 bg-[color:var(--color-advisory)]/[0.04] px-3.5 py-2.5">
      <DataTierBadge tier="benchmark" />
      <Fact label="run" value={runId.replace(/^attack-run-/, "").slice(0, 8)} title={runId} />
      <Fact label="harness" value={harnessVersion} />
      <Fact label="measured" value={timestamp(startedAt)} />
      <Fact label="scenarios" value={String(scenarios)} />
      <Fact label="iterations" value={`×${iterations}`} />
      <Fact label="file" value={sourceFile} />
    </div>
  );
}

function Fact({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5" title={title}>
      <span className="label-xs text-[color:var(--color-ink-4)]">{label}</span>
      <span className="num text-[11.5px] text-[color:var(--color-ink-2)]">{value}</span>
    </span>
  );
}

/**
 * What the console shows when no harness report exists.
 *
 * Not zeroes, and not a placeholder scenario list. The Attack Lab has no HTTP
 * surface by design (AL-06), so "nothing has been measured here" is the honest
 * answer, and the command that would change it is printed rather than described.
 */
export function RunnerNotConnected({
  detail,
  what = "attack lab",
}: {
  detail: string;
  what?: string;
}) {
  return (
    <UnavailableState
      title="RUNNER NOT CONNECTED — no benchmark on disk"
      detail={
        <div className="space-y-2">
          <p>
            The {what} exposes no HTTP surface. That is deliberate: an ingress route would be an
            unauthenticated front door accepting arbitrary payloads, and PACTRA has no
            authentication layer to gate one. Results therefore come from a recorded harness run,
            and no run has been found.
          </p>
          <p className="num text-[11px] break-all text-[color:var(--color-ink-4)]">{detail}</p>
          <p className="flex items-center gap-1.5 text-[color:var(--color-ink-4)]">
            <FlaskConical aria-hidden className="size-3.5" />
            Nothing is fabricated to fill this space. An empty benchmark is not a passing one.
          </p>
        </div>
      }
    />
  );
}
