"use client";

import { useMemo, useState } from "react";
import { ChevronRight, Search } from "lucide-react";

import { ScenarioDetail } from "@/components/attack/ScenarioDetail";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { EmptyState } from "@/components/ui/States";
import { SecurityStatusBadge, SeverityChip } from "@/components/ui/StatusBadges";
import {
  CATEGORY_BLURB,
  CATEGORY_ORDER,
  featuredSummaries,
  sortByCategory,
  summarizeScenarios,
  type ScenarioSummary,
} from "@/lib/attack-lab";
import { cn, ms } from "@/lib/format";
import type { AttackRunReport } from "@/lib/types/benchmark";

/**
 * The scenario explorer.
 *
 * Grouped by benchmark category because the categories are not interchangeable:
 * `BENIGN_CONTROL` scenarios pass by being ALLOWED and `KNOWN_LIMITATION`
 * scenarios pass by demonstrating a documented boundary, so listing all 63 in
 * one flat table sorted by status would put the correct outcomes for those two
 * groups next to the failures of the other eight.
 */
export function AttackLabExplorer({ report }: { report: AttackRunReport }) {
  const summaries = useMemo(() => sortByCategory(summarizeScenarios(report)), [report]);
  const featured = useMemo(() => featuredSummaries(summaries), [summaries]);
  const [selected, setSelected] = useState<ScenarioSummary | null>(featured[0] ?? summaries[0] ?? null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("ALL");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return summaries.filter((summary) => {
      if (category !== "ALL" && summary.result.category !== category) return false;
      if (needle.length === 0) return true;
      const haystack = [
        summary.result.scenario_id,
        summary.result.scenario_name,
        summary.result.reason_code ?? "",
        summary.result.target_invariants.join(" "),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [summaries, query, category]);

  const categories = useMemo(
    () => ["ALL", ...CATEGORY_ORDER.filter((name) => summaries.some((s) => s.result.category === name))],
    [summaries],
  );

  const grouped = useMemo(() => {
    const map = new Map<string, ScenarioSummary[]>();
    for (const summary of filtered) {
      const bucket = map.get(summary.result.category);
      if (bucket) bucket.push(summary);
      else map.set(summary.result.category, [summary]);
    }
    return map;
  }, [filtered]);

  return (
    <div className="space-y-5">
      {featured.length > 0 ? (
        <Panel
          title="The attacks that tell the story"
          subtitle="Ten scenarios that exercise the properties PACTRA exists to hold. Select one to see its target invariant and the evidence recorded against it."
          flush
        >
          <div className="grid gap-2 p-3 sm:grid-cols-2 xl:grid-cols-5">
            {featured.map((summary) => {
              const active = selected?.result.scenario_id === summary.result.scenario_id;
              return (
                <button
                  key={summary.result.scenario_id}
                  type="button"
                  onClick={() => setSelected(summary)}
                  className={cn(
                    "flex flex-col items-start gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
                    active
                      ? "border-[color:var(--color-accent)]/50 bg-[color:var(--color-accent)]/[0.08]"
                      : "border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] hover:border-[color:var(--color-line-strong)]",
                  )}
                >
                  <span className="text-[12px] leading-snug font-medium text-[color:var(--color-ink)]">
                    {summary.result.scenario_name}
                  </span>
                  <span className="flex flex-wrap items-center gap-1.5">
                    <SeverityChip severity={summary.result.severity} />
                    <SecurityStatusBadge
                      status={summary.result.status}
                      expectedStatus={summary.result.expected_status}
                      category={summary.result.category}
                    />
                  </span>
                </button>
              );
            })}
          </div>
        </Panel>
      ) : null}

      {/* `min-w-0` on both tracks: a grid item defaults to min-width:auto, so
          the wide evidence tables in the detail panel would otherwise push past
          their track and squeeze the inventory column to nothing. */}
      <div className="grid items-start gap-5 xl:grid-cols-[1.05fr_1fr]">
        <Panel
          className="min-w-0"
          title={`Scenario inventory (${filtered.length} of ${summaries.length})`}
          subtitle="One row per scenario. Where a scenario ran more than once, the WORST iteration is shown — “usually blocked” is not blocked."
          actions={
            <label className="relative">
              <span className="sr-only">Filter scenarios</span>
              <Search
                aria-hidden
                className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-[color:var(--color-ink-4)]"
              />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="scenario, reason code, invariant"
                className="w-[210px] rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-2)] py-1.5 pr-2 pl-7 text-[11.5px] text-[color:var(--color-ink)] placeholder:text-[color:var(--color-ink-4)]"
              />
            </label>
          }
          flush
        >
          <div className="flex flex-wrap gap-1 border-b border-[color:var(--color-line)] px-3 py-2">
            {categories.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => setCategory(name)}
                aria-pressed={category === name}
                title={CATEGORY_BLURB[name]}
                className={cn(
                  "num rounded border px-2 py-1 text-[10.5px] font-semibold transition-colors",
                  category === name
                    ? "border-[color:var(--color-accent)]/45 bg-[color:var(--color-accent)]/12 text-[color:var(--color-accent)]"
                    : "border-[color:var(--color-line)] text-[color:var(--color-ink-3)] hover:text-[color:var(--color-ink-2)]",
                )}
              >
                {name}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="p-4">
              <EmptyState
                title="No scenario matches this filter"
                detail="Nothing is hidden by default — clear the filter to see every scenario in the run."
              />
            </div>
          ) : (
            <div className="max-h-[720px] overflow-y-auto">
              {[...grouped.entries()].map(([name, rows]) => (
                <section key={name}>
                  <header className="sticky top-0 z-10 border-y border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-4 py-2">
                    <p className="num text-[11px] font-semibold text-[color:var(--color-ink)]">
                      {name}
                      <span className="ml-2 font-normal text-[color:var(--color-ink-4)]">
                        {rows.length}
                      </span>
                    </p>
                    {CATEGORY_BLURB[name] ? (
                      <p className="mt-0.5 text-[11px] leading-snug text-[color:var(--color-ink-4)]">
                        {CATEGORY_BLURB[name]}
                      </p>
                    ) : null}
                  </header>
                  <ul>
                    {rows.map((summary) => {
                      const active = selected?.result.scenario_id === summary.result.scenario_id;
                      return (
                        <li key={summary.result.scenario_id}>
                          <button
                            type="button"
                            onClick={() => setSelected(summary)}
                            aria-current={active ? "true" : undefined}
                            className={cn(
                              "flex w-full items-start gap-3 border-b border-[color:var(--color-line)]/60 px-4 py-2.5 text-left transition-colors",
                              active
                                ? "bg-[color:var(--color-accent)]/[0.07]"
                                : "hover:bg-[color:var(--color-surface-2)]",
                            )}
                          >
                            <div className="min-w-0 flex-1">
                              <p className="truncate text-[12px] font-medium text-[color:var(--color-ink)]">
                                {summary.result.scenario_name}
                              </p>
                              <p className="num mt-0.5 truncate text-[10.5px] text-[color:var(--color-ink-4)]">
                                {summary.result.scenario_id} · {ms(summary.meanExecuteMs)} ·{" "}
                                {summary.result.backend}
                              </p>
                              {summary.result.reason_code ? (
                                <span className="mt-1.5 inline-block">
                                  <ReasonCode
                                    code={summary.result.reason_code}
                                    expected={summary.result.expected_reason_code}
                                  />
                                </span>
                              ) : null}
                            </div>
                            <div className="flex shrink-0 flex-col items-end gap-1.5">
                              <SecurityStatusBadge
                                status={summary.result.status}
                                expectedStatus={summary.result.expected_status}
                                category={summary.result.category}
                              />
                              <SeverityChip severity={summary.result.severity} />
                            </div>
                            <ChevronRight
                              aria-hidden
                              className="mt-1 size-3.5 shrink-0 text-[color:var(--color-ink-4)]"
                            />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          )}
        </Panel>

        <div className="min-w-0 xl:sticky xl:top-6 xl:self-start">
          <Panel title="Scenario detail">
            {selected ? (
              <ScenarioDetail summary={selected} />
            ) : (
              <EmptyState
                title="Select a scenario"
                detail="Every scenario records what it measured — before/after counts, whether the protected value moved, and the reason code the control produced."
              />
            )}
          </Panel>
        </div>
      </div>

      {report.findings.length > 0 ? (
        <Panel
          title="Security findings"
          subtitle="Derived from actual NOT_BLOCKED hostile runs. Findings are never authored by hand and there is no code path that produces one from anything but a measured bypass."
          actions={<Badge tone="critical">{report.findings.length} OPEN</Badge>}
        >
          <ul className="space-y-3">
            {report.findings.map((finding) => (
              <li
                key={finding.id}
                className="rounded border border-[color:var(--color-critical)]/35 bg-[color:var(--color-critical)]/[0.05] p-3.5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityChip severity={finding.severity} />
                  <code className="num text-[11.5px] text-[color:var(--color-ink)]">{finding.id}</code>
                  <span className="num text-[11px] text-[color:var(--color-ink-4)]">
                    ×{finding.occurrences}
                  </span>
                </div>
                <p className="mt-2 text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
                  {finding.description}
                </p>
                <p className="num mt-1.5 text-[11px] text-[color:var(--color-ink-4)]">
                  reproduce: {finding.reproduction}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      ) : (
        <Panel title="Security findings">
          <p className="text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
            None — no malicious scenario went through in any iteration of this run. A finding is
            produced only from a measured bypass, so an empty list here is a measurement, not a
            default.
          </p>
        </Panel>
      )}
    </div>
  );
}
