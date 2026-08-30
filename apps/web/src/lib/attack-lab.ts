import type { AttackResult, AttackRunReport } from "@/lib/types/benchmark";

/**
 * Collapsing a multi-iteration run into one row per scenario.
 *
 * The rule is the one the harness's own text report uses, and it matters: a
 * scenario that failed in ANY iteration is shown as failed. "Usually blocked"
 * is not blocked, and showing the majority outcome would let a one-in-ten bypass
 * disappear behind nine successes.
 */
const STATUS_RANK: Record<string, number> = {
  NOT_BLOCKED: 0,
  ERROR: 1,
  INCONCLUSIVE: 2,
  BLOCKED: 3,
};

export interface ScenarioSummary {
  /** The representative run — the WORST iteration, per the rule above. */
  result: AttackResult;
  iterations: number;
  /** Distinct statuses seen across iterations, when more than one occurred. */
  statuses: string[];
  meanExecuteMs: number;
}

export function summarizeScenarios(report: AttackRunReport): ScenarioSummary[] {
  const grouped = new Map<string, AttackResult[]>();
  for (const result of report.results) {
    const bucket = grouped.get(result.scenario_id);
    if (bucket) bucket.push(result);
    else grouped.set(result.scenario_id, [result]);
  }

  const summaries: ScenarioSummary[] = [];
  for (const [, runs] of grouped) {
    const worst = runs.reduce((current, candidate) =>
      (STATUS_RANK[candidate.status] ?? 9) < (STATUS_RANK[current.status] ?? 9) ? candidate : current,
    );
    summaries.push({
      result: worst,
      iterations: runs.length,
      statuses: [...new Set(runs.map((run) => run.status))],
      meanExecuteMs: runs.reduce((total, run) => total + run.execute_ms, 0) / runs.length,
    });
  }
  return summaries;
}

/**
 * The scenarios that tell the project's story best.
 *
 * Pinned by id and INTERSECTED with what the report actually contains, so a
 * scenario that was renamed or never run simply does not appear rather than
 * rendering as an empty highlight. Nothing is displayed for an id the harness
 * did not produce a result for.
 */
export const FEATURED_SCENARIO_IDS: readonly string[] = [
  "authorization_replay",
  "transaction_mutation",
  "capability_escalation",
  "merchant_identity_spoof",
  "provider_timeout_after_create",
  "webhook_forgery",
  "duplicate_payment",
  "audit_payload_tamper",
  "adapter_registry_bypass",
  "adapter_confused_deputy",
];

export function featuredSummaries(summaries: ScenarioSummary[]): ScenarioSummary[] {
  const byId = new Map(summaries.map((summary) => [summary.result.scenario_id, summary]));
  const exact = FEATURED_SCENARIO_IDS.map((id) => byId.get(id)).filter(
    (summary): summary is ScenarioSummary => summary !== undefined,
  );
  if (exact.length > 0) return exact;

  // Nothing matched the pinned list — a plausible outcome if scenario ids were
  // renamed. Fall back to the CRITICAL scenarios the report does contain rather
  // than showing an empty section that implies none exist.
  return summaries.filter((summary) => summary.result.critical).slice(0, 10);
}

export const CATEGORY_ORDER: readonly string[] = [
  "INPUT_TRUST",
  "AUTHORITY",
  "TRANSACTION",
  "PAYMENT_RELIABILITY",
  "WEBHOOK",
  "AUDIT",
  "CONCURRENCY",
  "ADAPTER",
  "BENIGN_CONTROL",
  "KNOWN_LIMITATION",
];

export const CATEGORY_BLURB: Readonly<Record<string, string>> = {
  INPUT_TRUST: "Hostile merchant payloads: injected instructions, spoofed identity, self-assigned trust.",
  AUTHORITY: "Lower-authority data attempting to write state only higher authority may write.",
  TRANSACTION: "Attacks on the binding between an approval and the one transaction it commits to.",
  PAYMENT_RELIABILITY: "Duplicates, lost responses, and the uncertain state between them.",
  WEBHOOK: "Forged, duplicated and out-of-order provider messages.",
  AUDIT: "Attempts to edit, remove, reorder or inject events in the hash chain.",
  CONCURRENCY: "Races that only exist under a real concurrent database. Requires PostgreSQL.",
  ADAPTER: "Attacks arriving through a protocol adapter rather than the merchant or payment path.",
  BENIGN_CONTROL: "Legitimate requests that MUST go through. Without them there is no honest false-positive rate.",
  KNOWN_LIMITATION: "Demonstrations of documented boundaries. Never counted as blocked attacks.",
};

export function sortByCategory(summaries: ScenarioSummary[]): ScenarioSummary[] {
  return [...summaries].sort((a, b) => {
    const left = CATEGORY_ORDER.indexOf(a.result.category);
    const right = CATEGORY_ORDER.indexOf(b.result.category);
    if (left !== right) return (left < 0 ? 99 : left) - (right < 0 ? 99 : right);
    return a.result.scenario_id.localeCompare(b.result.scenario_id);
  });
}
