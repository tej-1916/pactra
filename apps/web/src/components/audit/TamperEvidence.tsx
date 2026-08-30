import { ArrowRight, FileWarning } from "lucide-react";

import { EvidenceTable } from "@/components/ui/EvidenceTable";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { SecurityStatusBadge, SeverityChip } from "@/components/ui/StatusBadges";
import { EmptyState } from "@/components/ui/States";
import type { ScenarioSummary } from "@/lib/attack-lab";

/**
 * What tampering with the ledger actually produces.
 *
 * This is built from RECORDED attack-lab evidence, not from a mutation the
 * console performed. There is no API that edits an audit event, and there should
 * not be one — a console that could rewrite the ledger to demonstrate that the
 * ledger detects rewrites would be the least trustworthy thing on the screen.
 *
 * So the scenarios below are the real audit-category runs from the loaded
 * report, each showing what was changed, what verification then said, and the
 * before/after evidence the harness measured.
 */
export function TamperEvidence({ scenarios }: { scenarios: ScenarioSummary[] }) {
  if (scenarios.length === 0) {
    return (
      <Panel title="Tamper detection">
        <EmptyState
          title="No audit-category evidence in the loaded run"
          detail="This section renders recorded attack-lab results. The console does not mutate audit events to produce them — there is no API that could, and building one would undermine the property being demonstrated."
        />
      </Panel>
    );
  }

  return (
    <Panel
      title="Tamper detection — recorded evidence"
      subtitle="Each row is a real attack-lab run against the hash chain. The console performs no mutation: there is no endpoint that edits an audit event, and a UI that could rewrite the ledger to prove the ledger detects rewrites would prove nothing."
      actions={<Badge tone="advisory" variant="outline">FROM RECORDED RUN</Badge>}
    >
      <div className="space-y-3">
        {scenarios.map((summary) => (
          <article
            key={summary.result.scenario_id}
            className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <FileWarning aria-hidden className="size-3.5 text-[color:var(--color-ink-3)]" />
              <h3 className="text-[12.5px] font-semibold tracking-tight text-[color:var(--color-ink)]">
                {summary.result.scenario_name}
              </h3>
              <SeverityChip severity={summary.result.severity} />
              <SecurityStatusBadge
                status={summary.result.status}
                expectedStatus={summary.result.expected_status}
                category={summary.result.category}
              />
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[11.5px]">
              <span className="num rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] px-2 py-1 text-[color:var(--color-ink-2)]">
                event modified
              </span>
              <ArrowRight aria-hidden className="size-3 text-[color:var(--color-ink-4)]" />
              <span className="num rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] px-2 py-1 text-[color:var(--color-ink-2)]">
                chain recomputed
              </span>
              <ArrowRight aria-hidden className="size-3 text-[color:var(--color-ink-4)]" />
              <ReasonCode code={summary.result.reason_code} />
            </div>

            {summary.result.evidence ? (
              <p className="mt-2 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
                {summary.result.evidence}
              </p>
            ) : null}

            <details className="group mt-2.5">
              <summary className="cursor-pointer text-[11.5px] font-medium text-[color:var(--color-accent)]">
                Observed effects
              </summary>
              <div className="mt-2 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface)]">
                <EvidenceTable effects={summary.result.observed_effects} />
              </div>
            </details>
          </article>
        ))}
      </div>
    </Panel>
  );
}
