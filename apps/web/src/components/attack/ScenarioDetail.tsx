import { ArrowRight, Crosshair, Database, X } from "lucide-react";

import { EvidenceTable } from "@/components/ui/EvidenceTable";
import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { SecurityStatusBadge, SeverityChip } from "@/components/ui/StatusBadges";
import { splitInvariant } from "@/components/ui/InvariantCard";
import { attackVerdict } from "@/lib/semantics";
import { cn, ms } from "@/lib/format";
import type { ScenarioSummary } from "@/lib/attack-lab";

/**
 * One scenario, in full.
 *
 * The layout follows what a reader needs to trust the result: the ATTACK, the
 * INVARIANT it targets, the OBSERVED EVIDENCE, and only then the RESULT and its
 * REASON. Putting the verdict first and the evidence last would invite the
 * verdict to be read on its own, which is exactly how a security claim becomes
 * an assertion.
 */
export function ScenarioDetail({
  summary,
  onClose,
}: {
  summary: ScenarioSummary;
  onClose?: () => void;
}) {
  const { result } = summary;
  const verdict = attackVerdict(result.status, result.expected_status, result.category);
  const isLimitation = result.category === "KNOWN_LIMITATION";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="label-xs mb-1.5 flex items-center gap-1.5 text-[color:var(--color-accent)]">
            <Crosshair aria-hidden className="size-3" />
            {isLimitation ? "Demonstrated limitation" : "Attack"}
          </p>
          <h2 className="text-[17px] leading-tight font-semibold tracking-tight text-[color:var(--color-ink)]">
            {result.scenario_name}
          </h2>
          <code className="num mt-1 block text-[11px] text-[color:var(--color-ink-4)]">
            {result.scenario_id}
          </code>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SeverityChip severity={result.severity} />
          <SecurityStatusBadge
            status={result.status}
            expectedStatus={result.expected_status}
            category={result.category}
          />
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close scenario detail"
              className="rounded border border-[color:var(--color-line-strong)] p-1.5 text-[color:var(--color-ink-3)] hover:text-[color:var(--color-ink)]"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          ) : null}
        </div>
      </div>

      <p
        className={cn(
          "rounded-lg border px-3.5 py-2.5 text-[12px] leading-relaxed",
          verdict.tone === "secure" &&
            "border-[color:var(--color-secure)]/30 bg-[color:var(--color-secure)]/[0.06] text-[color:var(--color-ink-2)]",
          verdict.tone === "critical" &&
            "border-[color:var(--color-critical)]/30 bg-[color:var(--color-critical)]/[0.06] text-[color:var(--color-ink-2)]",
          verdict.tone === "advisory" &&
            "border-[color:var(--color-advisory)]/30 bg-[color:var(--color-advisory)]/[0.06] text-[color:var(--color-ink-2)]",
          verdict.tone === "neutral" &&
            "border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] text-[color:var(--color-ink-2)]",
        )}
      >
        {verdict.meaning}
      </p>

      <section>
        <p className="label-xs mb-2 text-[color:var(--color-ink-4)]">Target invariant</p>
        <ul className="space-y-1.5">
          {result.target_invariants.map((invariant) => {
            const [precondition, consequence] = splitInvariant(invariant);
            return (
              <li
                key={invariant}
                className="flex flex-wrap items-center gap-2 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2"
              >
                <span className="num text-[11.5px] font-semibold text-[color:var(--color-ink)]">
                  {precondition}
                </span>
                {consequence ? (
                  <>
                    <ArrowRight aria-hidden className="size-3 text-[color:var(--color-secure)]" />
                    <span className="num text-[11.5px] font-semibold text-[color:var(--color-secure)]">
                      {consequence}
                    </span>
                  </>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <p className="label-xs mb-2 text-[color:var(--color-ink-4)]">Observed evidence</p>
        <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)]">
          <EvidenceTable effects={result.observed_effects} />
        </div>
        {result.evidence ? (
          <p className="mt-2 text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
            {result.evidence}
          </p>
        ) : null}
      </section>

      <section>
        <p className="label-xs mb-2 text-[color:var(--color-ink-4)]">Result</p>
        <KeyValueGrid columns={3}>
          <KeyValue label="Status">
            <SecurityStatusBadge
              status={result.status}
              expectedStatus={result.expected_status}
              category={result.category}
            />
          </KeyValue>
          <KeyValue label="Expected status">
            <span className="num">{result.expected_status}</span>
          </KeyValue>
          <KeyValue
            label="Invariant preserved"
            hint="null means the scenario measured no invariant-level state — not that the invariant failed."
          >
            <span className="num">
              {result.invariant_preserved === null ? "n/a" : String(result.invariant_preserved)}
            </span>
          </KeyValue>
          <KeyValue label="Reason" className="sm:col-span-2 xl:col-span-3">
            <ReasonCode
              code={result.reason_code}
              expected={result.expected_reason_code}
              describe
            />
          </KeyValue>
          <KeyValue label="Enforcement time" hint="Attack execution only. Harness-local (KL-07).">
            <span className="num">{ms(result.execute_ms)}</span>
            {summary.iterations > 1 ? (
              <span className="num mt-0.5 block text-[11px] text-[color:var(--color-ink-4)]">
                mean over {summary.iterations} iterations: {ms(summary.meanExecuteMs)}
              </span>
            ) : null}
          </KeyValue>
          <KeyValue label="Backend">
            <Badge tone="neutral" variant="outline" icon={<Database aria-hidden className="size-3" />}>
              {result.backend}
            </Badge>
          </KeyValue>
          <KeyValue label="Iterations">
            <span className="num">
              {summary.iterations}
              {summary.statuses.length > 1 ? (
                <span className="ml-1.5 text-[color:var(--color-critical)]">
                  ({summary.statuses.join(", ")})
                </span>
              ) : null}
            </span>
          </KeyValue>
        </KeyValueGrid>
        {result.error ? (
          <pre className="num mt-3 overflow-auto rounded border border-[color:var(--color-critical)]/30 bg-[color:var(--color-critical)]/[0.05] p-3 text-[11px] whitespace-pre-wrap text-[color:var(--color-ink-2)]">
            {result.error}
          </pre>
        ) : null}
      </section>
    </div>
  );
}
