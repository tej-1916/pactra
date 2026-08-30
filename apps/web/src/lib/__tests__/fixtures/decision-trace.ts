/**
 * TEST FIXTURES. Not backend data, not a recorded run, and not shipped.
 *
 * Every entry below is hand-written for the unit tests in this directory. It is
 * shaped to the frozen C1 `DecisionTraceEntry` schema — same fields, same enum
 * values, same "nullable fields are present as null" rule — so a drift in the
 * contract breaks these tests instead of passing silently. The captured runtime
 * payload lives in `docs/c1-decision-trace-example.json`; this file deliberately
 * does not import it, because a fixture that reaches into a frozen artefact
 * turns an evidence file into a test dependency.
 *
 * Nothing here is rendered by the application. `traceEntry` is exported as a
 * builder so a test states only the fields it is actually asserting on.
 */

import type { DecisionTraceEntry } from "@/lib/types/pactra";

let nextSequence = 0;

/** One entry, with every required field defaulted to a valid frozen value. */
export function traceEntry(overrides: Partial<DecisionTraceEntry> = {}): DecisionTraceEntry {
  const sequence = overrides.evidence?.sequence ?? nextSequence++;
  return {
    stage: "ADMIT",
    event_type: "MISSION_CREATED",
    verdict: "ACCEPTED",
    reason_codes: [],
    invariant_id: null,
    approval_scheme: null,
    policy_outcome: null,
    payment_state: null,
    advisory: false,
    next_action: "CONTINUE_ADMIT",
    recorded_at: "2026-08-30T12:44:54.683488Z",
    ...overrides,
    evidence: {
      event_id: `test-fixture-event-${String(sequence).padStart(4, "0")}`,
      sequence,
      actor: "orchestrator",
      ...overrides.evidence,
    },
  };
}

/** Reset the sequence counter so each test file starts from zero. */
export function resetFixtureSequence(): void {
  nextSequence = 0;
}

/**
 * A mission that was ADMITted, REFUSED at BIND on offer drift, and therefore
 * never reached EXECUTE. Chosen as the default fixture because it exercises the
 * three things most easily got wrong: a refusal, an empty stage, and an
 * advisory entry that must not read as a decision.
 */
export function refusedAtBindTrace(): DecisionTraceEntry[] {
  resetFixtureSequence();
  return [
    traceEntry({ event_type: "MISSION_CREATED" }),
    traceEntry({ event_type: "OFFERS_RANKED" }),
    traceEntry({
      event_type: "RISK_ASSESSED",
      verdict: "ADVISORY",
      advisory: true,
      next_action: "NONE",
      evidence: { event_id: "test-fixture-event-risk", sequence: 2, actor: "risk-engine" },
    }),
    traceEntry({
      event_type: "POLICY_DECISION",
      policy_outcome: "ALLOW",
      reason_codes: ["WITHIN_LIMITS"],
      next_action: "CONTINUE_BIND",
    }),
    traceEntry({
      stage: "BIND",
      event_type: "SECURITY_VIOLATION",
      verdict: "REFUSED",
      reason_codes: ["BIND_REFUSED_OFFER_CHANGED"],
      invariant_id: "binding.selected_offer_version_matches_authoritative_record",
      next_action: "NONE",
      evidence: { event_id: "test-fixture-event-bind", sequence: 4, actor: "security-kernel" },
    }),
  ];
}

/** A mission that reached EXECUTE with a queued PaymentIntent. */
export function reachedExecuteTrace(): DecisionTraceEntry[] {
  resetFixtureSequence();
  return [
    traceEntry({ event_type: "MISSION_CREATED" }),
    traceEntry({
      event_type: "POLICY_DECISION",
      policy_outcome: "ALLOW",
      reason_codes: ["WITHIN_LIMITS"],
      next_action: "CONTINUE_BIND",
    }),
    traceEntry({
      stage: "BIND",
      event_type: "AUTHORIZATION_CREATED",
      approval_scheme: "POLICY_AUTO",
      next_action: "CREATE_PAYMENT_INTENT",
    }),
    traceEntry({
      stage: "BIND",
      event_type: "AUTHORIZATION_CONSUMED",
      approval_scheme: "POLICY_AUTO",
      next_action: "DISPATCH_PAYMENT",
    }),
    traceEntry({
      stage: "EXECUTE",
      event_type: "PAYMENT_INTENT_CREATED",
      payment_state: "CREATED",
      next_action: "DISPATCH_PAYMENT",
    }),
    traceEntry({
      stage: "EXECUTE",
      event_type: "PAYMENT_QUEUED",
      verdict: "PENDING",
      payment_state: "QUEUED",
      next_action: "AWAIT_PROVIDER",
    }),
  ];
}
