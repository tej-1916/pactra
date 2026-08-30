import { describe, expect, it } from "vitest";

import { describeReasonCode, REASON_CODE_DESCRIPTIONS } from "@/lib/reason-codes";
import { VOCABULARY } from "@/lib/reference";

describe("describeReasonCode", () => {
  it("describes the codes that carry the project's headline security claims", () => {
    expect(describeReasonCode("AUTHORIZATION_REPLAY_DETECTED")).toBe(
      "The authorization was already consumed and cannot authorize another payment.",
    );
    expect(describeReasonCode("IDEMPOTENCY_CONFLICT")).toMatch(/materially different transaction/);
    expect(describeReasonCode("AUDIT_EVENT_HASH_MISMATCH")).toMatch(/edited payload/);
  });

  /**
   * An unexplained REAL code is strictly better than an invented explanation,
   * and returning null makes a missing description visible instead of papering
   * over it. The component that consumes this prints the code either way.
   */
  it("returns null for a code it has no description for, rather than inventing one", () => {
    expect(describeReasonCode("SOME_CODE_ADDED_LATER")).toBeNull();
  });

  it("returns null for a missing code", () => {
    expect(describeReasonCode(null)).toBeNull();
    expect(describeReasonCode(undefined)).toBeNull();
  });

  it("never describes a code the backend cannot emit", () => {
    // Everything described must exist in one of the backend's real vocabularies,
    // or be an HTTP-layer code the API raises directly. A description for a code
    // that does not exist would be documentation of a fiction.
    const known = new Set<string>([
      ...VOCABULARY.reasonCodes,
      ...VOCABULARY.auditReasonCodes,
      ...VOCABULARY.adapterWarningCodes,
      // Raised by the API layer or the replay reducer rather than the ReasonCode enum.
      "INVARIANT_VIOLATION",
      "NO_AUTHORIZATION",
      "MISSION_NOT_AWAITING_APPROVAL",
      "IDEMPOTENCY_KEY_INVALID",
      "UNKNOWN_PAYMENT_PROVIDER",
      "PAYMENT_PROVIDER_UNAVAILABLE",
      "WEBHOOK_BODY_TOO_LARGE",
      "REPLAY_OK",
      "REPLAY_AUDIT_INVALID",
      "REPLAY_UNSUPPORTED_EVENT_TYPE",
      "REPLAY_MALFORMED_EVENT",
    ]);

    const unknown = Object.keys(REASON_CODE_DESCRIPTIONS).filter((code) => !known.has(code));
    expect(unknown).toEqual([]);
  });
});
