import { describe, expect, it } from "vitest";

import {
  refusedAtBindTrace,
  reachedExecuteTrace,
  traceEntry,
} from "./fixtures/decision-trace";
import {
  currentNextAction,
  describeEventType,
  EVENT_TYPE_STATEMENT,
  groupByStage,
  NEXT_ACTION_MEANING,
  orderTrace,
  summarizeStage,
  VERDICT_PRESENTATION,
  verdictTone,
} from "@/lib/trace";
import { DECISION_STAGES } from "@/lib/types/pactra";

describe("decision trace ordering", () => {
  it("orders ascending by evidence.sequence", () => {
    const shuffled = [
      traceEntry({ evidence: { event_id: "c", sequence: 2, actor: "orchestrator" } }),
      traceEntry({ evidence: { event_id: "a", sequence: 0, actor: "orchestrator" } }),
      traceEntry({ evidence: { event_id: "b", sequence: 1, actor: "orchestrator" } }),
    ];

    expect(orderTrace(shuffled).map((entry) => entry.evidence.sequence)).toEqual([0, 1, 2]);
  });

  it("breaks a sequence tie on event_id, so ordering is total", () => {
    const tied = [
      traceEntry({ evidence: { event_id: "zzz", sequence: 7, actor: "orchestrator" } }),
      traceEntry({ evidence: { event_id: "aaa", sequence: 7, actor: "orchestrator" } }),
    ];

    expect(orderTrace(tied).map((entry) => entry.evidence.event_id)).toEqual(["aaa", "zzz"]);
  });

  it("does not mutate the input array", () => {
    const entries = [
      traceEntry({ evidence: { event_id: "b", sequence: 1, actor: "orchestrator" } }),
      traceEntry({ evidence: { event_id: "a", sequence: 0, actor: "orchestrator" } }),
    ];
    const before = entries.map((entry) => entry.evidence.event_id);

    orderTrace(entries);

    expect(entries.map((entry) => entry.evidence.event_id)).toEqual(before);
  });
});

describe("ADMIT / BIND / EXECUTE grouping", () => {
  it("always returns all three stages in the frozen order", () => {
    expect(groupByStage([]).map((group) => group.stage)).toEqual(["ADMIT", "BIND", "EXECUTE"]);
    expect(DECISION_STAGES).toEqual(["ADMIT", "BIND", "EXECUTE"]);
  });

  it("keeps a stage a mission never reached, rather than dropping it", () => {
    const groups = groupByStage(refusedAtBindTrace());
    const execute = groups.find((group) => group.stage === "EXECUTE");

    expect(execute).toBeDefined();
    expect(execute?.entries).toHaveLength(0);
    expect(summarizeStage(execute!).reached).toBe(false);
  });

  it("assigns a bind-refused security violation to BIND, not ADMIT", () => {
    const groups = groupByStage(refusedAtBindTrace());
    const bind = groups.find((group) => group.stage === "BIND")!;
    const admit = groups.find((group) => group.stage === "ADMIT")!;

    expect(bind.entries.map((entry) => entry.event_type)).toEqual(["SECURITY_VIOLATION"]);
    expect(admit.entries.some((entry) => entry.verdict === "REFUSED")).toBe(false);
  });

  it("summarizes refusals and advisories separately", () => {
    const groups = groupByStage(refusedAtBindTrace());
    const admit = summarizeStage(groups.find((group) => group.stage === "ADMIT")!);
    const bind = summarizeStage(groups.find((group) => group.stage === "BIND")!);

    expect(admit.advisory).toBe(1);
    expect(admit.refused).toBe(0);
    expect(bind.refused).toBe(1);
  });

  it("reports the next action from the LAST entry by sequence", () => {
    const next = currentNextAction(reachedExecuteTrace());

    expect(next?.action).toBe("AWAIT_PROVIDER");
    expect(next?.from.event_type).toBe("PAYMENT_QUEUED");
  });

  it("reports no next action for an empty trace rather than guessing one", () => {
    expect(currentNextAction([])).toBeNull();
  });
});

describe("verdict presentation", () => {
  it("never renders a refusal in the critical tone — a refusal is a control holding", () => {
    expect(verdictTone("REFUSED")).toBe("secure");
    expect(verdictTone("FAILED")).toBe("critical");
  });

  it("keeps ACCEPTED neutral so it cannot read as a security success", () => {
    expect(verdictTone("ACCEPTED")).toBe("neutral");
  });

  it("covers every frozen verdict value", () => {
    expect(Object.keys(VERDICT_PRESENTATION).sort()).toEqual(
      [
        "ACCEPTED",
        "ADVISORY",
        "FAILED",
        "IGNORED",
        "PENDING",
        "REFUSED",
        "SUCCEEDED",
      ].sort(),
    );
  });

  it("says an advisory verdict authorizes nothing", () => {
    expect(VERDICT_PRESENTATION.ADVISORY.meaning).toMatch(/authorizes nothing/i);
  });
});

describe("event-type statements", () => {
  it("returns null for an event type it does not know, rather than inventing one", () => {
    expect(describeEventType("SOME_FUTURE_EVENT_TYPE")).toBeNull();
  });

  it("describes what the event RECORDS, never a particular mission's circumstances", () => {
    expect(describeEventType("POLICY_DECISION")).toMatch(/deterministic policy/i);
    expect(describeEventType("RISK_ASSESSED")).toMatch(/grants no authority/i);
  });

  it("carries no chain-of-thought or reasoning language", () => {
    const forbidden = /chain[- ]of[- ]thought|reasoning|the model (thought|decided|believed)/i;
    for (const [eventType, statement] of Object.entries(EVENT_TYPE_STATEMENT)) {
      expect(statement, eventType).not.toMatch(forbidden);
    }
  });
});

describe("next actions", () => {
  it("has a meaning for every frozen next_action value", () => {
    expect(Object.keys(NEXT_ACTION_MEANING).sort()).toEqual(
      [
        "AWAIT_PROVIDER",
        "AWAIT_USER_SIGNATURE",
        "CONTINUE_ADMIT",
        "CONTINUE_BIND",
        "CREATE_PAYMENT_INTENT",
        "DISPATCH_PAYMENT",
        "NONE",
        "RECONCILE_PAYMENT",
        "RETRY_PAYMENT",
      ].sort(),
    );
  });
});
