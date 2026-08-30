import { describe, expect, it } from "vitest";

import { humanizeCode, inr, ms, percent, shortId, truncateHash } from "@/lib/format";

describe("percent", () => {
  /**
   * The harness reports `null` for a rate it could not compute. Formatting that
   * as 0.0% or 100.0% would turn an absence of evidence into a claim, which is
   * the specific dishonesty the reporting layer is built to prevent.
   */
  it("renders a rate with no denominator as n/a, never as a number", () => {
    expect(percent(null)).toBe("n/a");
    expect(percent(undefined)).toBe("n/a");
  });

  it("renders real rates", () => {
    expect(percent(1)).toBe("100.0%");
    expect(percent(0)).toBe("0.0%");
    expect(percent(0.9375, 2)).toBe("93.75%");
  });
});

describe("ms", () => {
  it("renders an unmeasured latency as n/a", () => {
    expect(ms(null)).toBe("n/a");
  });

  it("renders a measured latency", () => {
    expect(ms(18.34781)).toBe("18.35 ms");
  });
});

describe("inr", () => {
  it("renders whole rupees as PACTRA stores them", () => {
    expect(inr(3799)).toBe("₹3,799");
  });

  it("renders a missing amount as a dash rather than zero", () => {
    expect(inr(null)).toBe("—");
    expect(inr(null)).not.toBe("₹0");
  });
});

describe("truncateHash", () => {
  it("elides the middle and keeps both ends recognisable", () => {
    const hash = "a".repeat(28) + "b".repeat(36);
    const shown = truncateHash(hash);
    expect(shown).toContain("…");
    expect(shown.startsWith("aaaaaaaaaa")).toBe(true);
    expect(shown.endsWith("bbbbbb")).toBe(true);
  });

  it("leaves a short value alone rather than corrupting it", () => {
    expect(truncateHash("abc123")).toBe("abc123");
  });

  it("renders a missing hash as a dash", () => {
    expect(truncateHash(null)).toBe("—");
  });
});

describe("shortId", () => {
  it("truncates and marks the truncation", () => {
    expect(shortId("6f1c2b90-1111-2222", 8)).toBe("6f1c2b90…");
  });
});

describe("humanizeCode", () => {
  it("produces readable prose without destroying the underlying code", () => {
    expect(humanizeCode("AUTHORIZATION_REPLAY_DETECTED")).toBe("Authorization replay detected");
  });
});
