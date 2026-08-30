import { describe, expect, it } from "vitest";

import {
  attackVerdict,
  authorityName,
  authorityTone,
  paymentStateTone,
  policyOutcomeTone,
  protocolStatusTone,
  riskBandTone,
  severityTone,
  trustTone,
} from "@/lib/semantics";

/**
 * These tests guard the one mapping that is expensive to get wrong: a blocked
 * attack is a SUCCESS for PACTRA and must never be rendered as a failure, while
 * a blocked benign control must never be rendered as a success.
 */
describe("attackVerdict", () => {
  it("treats a blocked hostile scenario as a security success, not a failure", () => {
    const verdict = attackVerdict("BLOCKED", "BLOCKED", "TRANSACTION");
    expect(verdict.label).toBe("BLOCKED");
    expect(verdict.tone).toBe("secure");
    expect(verdict.decisive).toBe(true);
  });

  it("treats a blocked benign control as a false positive", () => {
    const verdict = attackVerdict("BLOCKED", "NOT_BLOCKED", "BENIGN_CONTROL");
    expect(verdict.label).toBe("FALSE POSITIVE");
    expect(verdict.tone).toBe("critical");
  });

  it("treats an allowed benign control as the pass it is", () => {
    const verdict = attackVerdict("NOT_BLOCKED", "NOT_BLOCKED", "BENIGN_CONTROL");
    expect(verdict.label).toBe("ALLOWED · CONTROL");
    expect(verdict.tone).toBe("secure");
  });

  it("treats an unblocked hostile scenario as a bypass", () => {
    const verdict = attackVerdict("NOT_BLOCKED", "BLOCKED", "AUTHORITY");
    expect(verdict.label).toBe("NOT BLOCKED");
    expect(verdict.tone).toBe("critical");
  });

  it("never presents ERROR as BLOCKED — an exception is not a block", () => {
    const verdict = attackVerdict("ERROR", "BLOCKED", "AUDIT");
    expect(verdict.label).toBe("ERROR");
    expect(verdict.label).not.toBe("BLOCKED");
    expect(verdict.decisive).toBe(false);
    expect(verdict.meaning).toMatch(/proves nothing/i);
  });

  it("never presents INCONCLUSIVE as secure, and marks it indecisive", () => {
    const verdict = attackVerdict("INCONCLUSIVE", "BLOCKED", "CONCURRENCY");
    expect(verdict.label).toBe("INCONCLUSIVE");
    expect(verdict.tone).toBe("neutral");
    expect(verdict.decisive).toBe(false);
  });

  it("gives KNOWN_LIMITATION its own state rather than counting it either way", () => {
    const verdict = attackVerdict("NOT_BLOCKED", "NOT_BLOCKED", "KNOWN_LIMITATION");
    expect(verdict.label).toBe("KNOWN LIMITATION");
    expect(verdict.decisive).toBe(false);
    expect(verdict.tone).not.toBe("critical");
  });
});

describe("severity vs result", () => {
  it("keeps severity on its own axis so CRITICAL severity is not a failed result", () => {
    // Severity CRITICAL and result BLOCKED must not resolve to the same tone
    // treatment path: severity renders outlined, result renders solid.
    expect(severityTone("CRITICAL")).toBe("critical");
    expect(attackVerdict("BLOCKED", "BLOCKED", "TRANSACTION").tone).toBe("secure");
  });

  it("scales severity downward for lower ordinals", () => {
    expect(severityTone("MEDIUM")).toBe("advisory");
    expect(severityTone("LOW")).toBe("neutral");
  });
});

describe("payment state semantics", () => {
  it("marks the uncertain state as advisory rather than failed", () => {
    expect(paymentStateTone("PROVIDER_PENDING")).toBe("advisory");
  });

  it("marks settlement secure and terminal failure critical", () => {
    expect(paymentStateTone("SUCCEEDED")).toBe("secure");
    expect(paymentStateTone("FAILED_TERMINAL")).toBe("critical");
  });
});

describe("policy and risk semantics", () => {
  it("maps policy outcomes to their decision meaning", () => {
    expect(policyOutcomeTone("ALLOW")).toBe("secure");
    expect(policyOutcomeTone("REQUIRE_APPROVAL")).toBe("advisory");
    expect(policyOutcomeTone("DENY")).toBe("critical");
  });

  it("maps risk bands without ever borrowing the policy vocabulary", () => {
    expect(riskBandTone("LOW")).toBe("secure");
    expect(riskBandTone("CRITICAL")).toBe("critical");
  });
});

describe("provenance semantics", () => {
  it("resolves the real authority lattice values", () => {
    expect(authorityName(10)).toBe("MERCHANT_DATA");
    expect(authorityName(20)).toBe("AGENT_PROPOSAL");
    expect(authorityName(30)).toBe("TRUSTED_INTERNAL_SERVICE");
    expect(authorityName(60)).toBe("USER_POLICY");
  });

  it("does not invent a name for an unknown level", () => {
    expect(authorityName(99)).toBe("AUTHORITY_99");
  });

  it("renders low authority and untrusted data in the taint tone", () => {
    expect(authorityTone(10)).toBe("taint");
    expect(authorityTone(20)).toBe("taint");
    expect(trustTone("untrusted")).toBe("taint");
    expect(trustTone("authoritative")).toBe("secure");
  });
});

describe("protocol status semantics", () => {
  it("distinguishes IMPLEMENTED from PARTIAL", () => {
    expect(protocolStatusTone("IMPLEMENTED")).toBe("secure");
    expect(protocolStatusTone("PARTIAL")).toBe("advisory");
    expect(protocolStatusTone("PLANNED")).toBe("neutral");
  });

  it("has no treatment for a status the backend cannot emit", () => {
    // There is no `SUPPORTED` status in the backend vocabulary — it is the word
    // that lets a claim mean whatever the reader hopes. An unknown status must
    // fall back to neutral rather than acquiring a favourable colour.
    expect(protocolStatusTone("SUPPORTED")).toBe("neutral");
  });
});
