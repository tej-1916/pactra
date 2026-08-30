import { describe, expect, it } from "vitest";

import {
  headlineInvariants,
  LIMITATIONS,
  PAYMENT_STATE_MACHINE,
  PROTOCOL_SUPPORT,
  VOCABULARY,
} from "@/lib/reference";

/**
 * The generated export is the console's only source for backend declarations, so
 * these tests guard against it silently going stale or losing structure. They do
 * NOT re-assert the backend's own invariants — those are the backend's tests.
 * They assert the properties the UI depends on to render honestly.
 */

describe("protocol support matrix", () => {
  it("carries every protocol with both a supported and a not-supported statement", () => {
    expect(PROTOCOL_SUPPORT.length).toBeGreaterThan(0);
    for (const entry of PROTOCOL_SUPPORT) {
      expect(entry.supported.length).toBeGreaterThan(0);
      // The gaps are mandatory on EVERY row, including implemented ones: they
      // are the half a reader is most likely to assume away.
      expect(entry.notSupported.length).toBeGreaterThan(0);
      expect(entry.reason.length).toBeGreaterThan(0);
    }
  });

  it("uses only statuses the backend can emit — there is no SUPPORTED", () => {
    const permitted = new Set(["IMPLEMENTED", "PARTIAL", "PLANNED", "NOT_APPLICABLE"]);
    for (const entry of PROTOCOL_SUPPORT) {
      expect(permitted.has(entry.status)).toBe(true);
    }
    expect(PROTOCOL_SUPPORT.some((entry) => entry.status === "SUPPORTED")).toBe(false);
  });

  it("scopes MCP as PARTIAL and never claims a server", () => {
    const mcp = PROTOCOL_SUPPORT.find((entry) => entry.protocol === "MCP");
    expect(mcp).toBeDefined();
    expect(mcp?.status).toBe("PARTIAL");
    expect(mcp?.notSupported).toMatch(/NOT an MCP server/i);
    expect(mcp?.notSupported).toMatch(/tools\/list/);
  });

  it("leaves a family unassigned rather than guessing one", () => {
    const x402 = PROTOCOL_SUPPORT.find((entry) => entry.protocol === "x402");
    expect(x402?.status).toBe("PLANNED");
    expect(x402?.family).toBeNull();
  });

  it("names an adapter for every implemented or partial row that has one", () => {
    const implemented = PROTOCOL_SUPPORT.filter((entry) => entry.status === "IMPLEMENTED");
    expect(implemented.length).toBeGreaterThan(0);
    for (const entry of implemented) {
      expect(entry.adapterId).not.toBeNull();
    }
    // A PLANNED protocol must name no adapter — that is what PLANNED means.
    for (const entry of PROTOCOL_SUPPORT.filter((e) => e.status === "PLANNED")) {
      expect(entry.adapterId).toBeNull();
    }
  });
});

describe("limitation registers", () => {
  it("keeps the three registers separate and non-empty", () => {
    expect(LIMITATIONS.security.length).toBeGreaterThan(0);
    expect(LIMITATIONS.risk.length).toBeGreaterThan(0);
    expect(LIMITATIONS.adapter.length).toBeGreaterThan(0);
  });

  it("uses a distinct id prefix per register so they cannot be conflated", () => {
    for (const entry of LIMITATIONS.security) expect(entry.id.startsWith("KL-")).toBe(true);
    for (const entry of LIMITATIONS.risk) expect(entry.id.startsWith("RL-")).toBe(true);
    for (const entry of LIMITATIONS.adapter) expect(entry.id.startsWith("AL-")).toBe(true);
  });

  it("discloses the audit tail-truncation boundary", () => {
    const tail = LIMITATIONS.security.find((entry) => entry.id.startsWith("KL-01"));
    expect(tail).toBeDefined();
    expect(tail?.detail).toMatch(/anchor outside itself/i);
  });

  it("discloses that the risk corpus is synthetic and has no held-out set", () => {
    const synthetic = LIMITATIONS.risk.find((entry) => entry.id.startsWith("RL-03"));
    const heldOut = LIMITATIONS.risk.find((entry) => entry.id.startsWith("RL-07"));
    expect(synthetic).toBeDefined();
    expect(heldOut).toBeDefined();
  });
});

describe("payment state machine", () => {
  it("gives the terminal states no outgoing transitions", () => {
    for (const state of PAYMENT_STATE_MACHINE.terminal) {
      expect(PAYMENT_STATE_MACHINE.transitions[state]).toEqual([]);
    }
  });

  it("treats PROVIDER_PENDING as the single uncertain state", () => {
    expect(PAYMENT_STATE_MACHINE.uncertain).toEqual(["PROVIDER_PENDING"]);
  });

  it("never draws an edge to a state that does not exist", () => {
    const known = new Set(PAYMENT_STATE_MACHINE.states);
    for (const [from, targets] of Object.entries(PAYMENT_STATE_MACHINE.transitions)) {
      expect(known.has(from)).toBe(true);
      for (const target of targets) expect(known.has(target)).toBe(true);
    }
  });
});

describe("vocabulary", () => {
  it("publishes the full invariant contract", () => {
    expect(VOCABULARY.invariantContract.length).toBeGreaterThanOrEqual(11);
    expect(VOCABULARY.invariantContract).toContain("NO VALID AUTHORIZATION → NO PAYMENT");
    expect(VOCABULARY.invariantContract).toContain("AUDIT EVENT MODIFIED → VERIFICATION FAILURE");
  });

  it("selects headline invariants only from the published contract", () => {
    for (const invariant of headlineInvariants()) {
      expect(VOCABULARY.invariantContract).toContain(invariant);
    }
    expect(headlineInvariants().length).toBe(5);
  });

  it("has no ALLOW or DENY in the risk recommendation vocabulary", () => {
    // Those words belong to PolicyOutcome. A risk value must not be
    // pattern-matchable into a policy branch.
    expect(VOCABULARY.riskRecommendations).not.toContain("ALLOW");
    expect(VOCABULARY.riskRecommendations).not.toContain("DENY");
    expect(VOCABULARY.policyOutcomes).toContain("ALLOW");
    expect(VOCABULARY.policyOutcomes).toContain("DENY");
  });

  it("excludes benign controls and known limitations from the malicious set", () => {
    expect(VOCABULARY.maliciousCategories).not.toContain("BENIGN_CONTROL");
    expect(VOCABULARY.maliciousCategories).not.toContain("KNOWN_LIMITATION");
    expect(VOCABULARY.maliciousCategories).toContain("ADAPTER");
  });

  it("orders the authority lattice ascending", () => {
    const values = VOCABULARY.authorityLevels.map((level) => level.value);
    expect([...values].sort((a, b) => a - b)).toEqual(values);
  });
});
