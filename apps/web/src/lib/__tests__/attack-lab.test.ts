import { describe, expect, it } from "vitest";

import { featuredSummaries, sortByCategory, summarizeScenarios } from "@/lib/attack-lab";
import type { AttackResult, AttackRunReport } from "@/lib/types/benchmark";

function result(overrides: Partial<AttackResult>): AttackResult {
  return {
    scenario_id: "scenario",
    scenario_name: "Scenario",
    category: "TRANSACTION",
    severity: "HIGH",
    target_invariants: ["A -> B"],
    backend: "SQLITE",
    run_id: "attack-run-test",
    iteration: 1,
    started_at: "2026-08-28T00:00:00Z",
    duration_ms: 10,
    execute_ms: 5,
    status: "BLOCKED",
    expected_status: "BLOCKED",
    blocked: true,
    reason_code: null,
    expected_reason_code: null,
    reason_match: null,
    invariant_preserved: true,
    observed_effects: {},
    evidence: null,
    error: null,
    critical: false,
    ...overrides,
  };
}

function report(results: AttackResult[]): AttackRunReport {
  return {
    run_id: "attack-run-test",
    system: "PACTRA",
    harness_version: "pactra-attack-lab-v1",
    iterations: 1,
    scenarios_selected: new Set(results.map((r) => r.scenario_id)).size,
    started_at: "2026-08-28T00:00:00Z",
    completed_at: "2026-08-28T00:00:01Z",
    duration_ms: 1000,
    postgres_included: true,
    postgres_exercised: true,
    results,
    metrics: {} as AttackRunReport["metrics"],
    findings: [],
    known_limitations: [],
  };
}

describe("summarizeScenarios", () => {
  /**
   * The rule the harness's own text report uses: a scenario that failed in ANY
   * iteration is shown as failed. Showing the majority outcome would let a
   * one-in-ten bypass disappear behind nine successes.
   */
  it("shows the WORST iteration, so 'usually blocked' is never shown as blocked", () => {
    const summaries = summarizeScenarios(
      report([
        result({ scenario_id: "replay", iteration: 1, status: "BLOCKED" }),
        result({ scenario_id: "replay", iteration: 2, status: "NOT_BLOCKED", blocked: false }),
        result({ scenario_id: "replay", iteration: 3, status: "BLOCKED" }),
      ]),
    );
    expect(summaries).toHaveLength(1);
    expect(summaries[0]?.result.status).toBe("NOT_BLOCKED");
    expect(summaries[0]?.iterations).toBe(3);
    expect(summaries[0]?.statuses).toContain("BLOCKED");
    expect(summaries[0]?.statuses).toContain("NOT_BLOCKED");
  });

  it("ranks an ERROR as worse than a BLOCKED — an exception is not a block", () => {
    const summaries = summarizeScenarios(
      report([
        result({ scenario_id: "x", iteration: 1, status: "BLOCKED" }),
        result({ scenario_id: "x", iteration: 2, status: "ERROR" }),
      ]),
    );
    expect(summaries[0]?.result.status).toBe("ERROR");
  });

  it("ranks INCONCLUSIVE as worse than BLOCKED so it is never counted on the safe side", () => {
    const summaries = summarizeScenarios(
      report([
        result({ scenario_id: "pg", iteration: 1, status: "BLOCKED" }),
        result({ scenario_id: "pg", iteration: 2, status: "INCONCLUSIVE" }),
      ]),
    );
    expect(summaries[0]?.result.status).toBe("INCONCLUSIVE");
  });

  it("averages execute time across iterations", () => {
    const summaries = summarizeScenarios(
      report([
        result({ scenario_id: "y", iteration: 1, execute_ms: 10 }),
        result({ scenario_id: "y", iteration: 2, execute_ms: 20 }),
      ]),
    );
    expect(summaries[0]?.meanExecuteMs).toBe(15);
  });
});

describe("featuredSummaries", () => {
  it("shows nothing for a pinned id the run did not produce", () => {
    const summaries = summarizeScenarios(
      report([result({ scenario_id: "authorization_replay" })]),
    );
    const featured = featuredSummaries(summaries);
    expect(featured).toHaveLength(1);
    expect(featured[0]?.result.scenario_id).toBe("authorization_replay");
  });

  it("falls back to the run's own CRITICAL scenarios when no pinned id matches", () => {
    const summaries = summarizeScenarios(
      report([
        result({ scenario_id: "renamed_scenario", critical: true }),
        result({ scenario_id: "another_one", critical: false }),
      ]),
    );
    const featured = featuredSummaries(summaries);
    expect(featured).toHaveLength(1);
    expect(featured[0]?.result.scenario_id).toBe("renamed_scenario");
  });
});

describe("sortByCategory", () => {
  it("keeps benign controls and known limitations at the end, away from hostile results", () => {
    const summaries = summarizeScenarios(
      report([
        result({ scenario_id: "c", category: "BENIGN_CONTROL", expected_status: "NOT_BLOCKED" }),
        result({ scenario_id: "k", category: "KNOWN_LIMITATION", expected_status: "NOT_BLOCKED" }),
        result({ scenario_id: "a", category: "INPUT_TRUST" }),
      ]),
    );
    const ordered = sortByCategory(summaries).map((s) => s.result.category);
    expect(ordered).toEqual(["INPUT_TRUST", "BENIGN_CONTROL", "KNOWN_LIMITATION"]);
  });
});
