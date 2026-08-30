import { describe, expect, it } from "vitest";

import {
  AUTHORITATIVE_FIELDS,
  isAuthoritativeField,
  isTaintedField,
  MAX_DISPLAY_LENGTH,
  RESERVED_AUTHORITATIVE_HEADINGS,
  sanitizeDisplayString,
  TAINTED_FIELDS,
} from "@/lib/tainted";

/*
 * Escape sequences rather than literal characters throughout, and the codepoint
 * named in a comment beside each one. An invisible or direction-flipping
 * character pasted into a source file is a test nobody can review -- and
 * reviewing this particular file is the entire point of it.
 */
const RLO = "\u202E"; // U+202E right-to-left override
const LRI = "\u2066"; // U+2066 left-to-right isolate
const ZWJ = "\u200D"; // U+200D zero-width joiner
const ZWSP = "\u200B"; // U+200B zero-width space
const BOM = "\uFEFF"; // U+FEFF zero-width no-break space
const BELL = "\u0007"; // U+0007, a C0 control
const CYRILLIC_A = "\u0410"; // U+0410, visually identical to Latin A

describe("bidi handling", () => {
  it("removes a right-to-left override from a merchant title", () => {
    const result = sanitizeDisplayString(`Headphones ${RLO}999`);

    expect(result.text).not.toContain(RLO);
    expect(result.text).toBe("Headphones 999");
    expect(result.findings.map((finding) => finding.code)).toContain("BIDI_CONTROL_REMOVED");
    expect(result.suspicious).toBe(true);
  });

  it("removes isolates too", () => {
    const result = sanitizeDisplayString(`a${LRI}b`);

    expect(result.text).toBe("ab");
    expect(result.findings.map((finding) => finding.code)).toContain("BIDI_CONTROL_REMOVED");
  });

  it("does not leave a stateful regex that skips the NEXT string", () => {
    // A shared /g/ regex would advance lastIndex on the first call and miss a
    // match at position 0 of the second. That is the bug the two-regex split in
    // lib/tainted.ts exists to prevent, so it is asserted rather than assumed.
    sanitizeDisplayString(`padding padding padding ${RLO}x`);
    const second = sanitizeDisplayString(`${RLO}y`);

    expect(second.text).toBe("y");
    expect(second.findings.map((finding) => finding.code)).toContain("BIDI_CONTROL_REMOVED");
  });
});

describe("invisible characters", () => {
  it("removes zero-width joiners and spaces", () => {
    const result = sanitizeDisplayString(`Mer${ZWJ}chant${ZWSP}A${BOM}`);

    expect(result.text).toBe("MerchantA");
    expect(result.findings.map((finding) => finding.code)).toContain("ZERO_WIDTH_REMOVED");
  });

  it("collapses control characters into spaces rather than deleting them", () => {
    const result = sanitizeDisplayString(`Total:${BELL}999`);

    expect(result.text).toBe("Total: 999");
    expect(result.findings.map((finding) => finding.code)).toContain("CONTROL_CHARACTER_REMOVED");
  });

  it("reports a value that was entirely formatting characters", () => {
    const result = sanitizeDisplayString(`${RLO}${ZWSP}${BOM}`);

    expect(result.text).toBe("");
    expect(result.findings.map((finding) => finding.code)).toContain("EMPTY_AFTER_SANITIZATION");
  });
});

describe("confusables", () => {
  it("flags a Latin/Cyrillic mix without rewriting the characters", () => {
    // "Apple Store" with a Cyrillic capital A. Visually identical; a different
    // string, and potentially a different merchant.
    const raw = `${CYRILLIC_A}pple Store`;
    const result = sanitizeDisplayString(raw);

    expect(result.text).toBe(raw);
    expect(result.findings.map((finding) => finding.code)).toContain("MIXED_SCRIPT");
    expect(result.findings.find((finding) => finding.code === "MIXED_SCRIPT")?.detail).toMatch(
      /not corrected/i,
    );
  });

  it("does not flag a single-script string", () => {
    expect(sanitizeDisplayString("Premium Headphones").suspicious).toBe(false);
  });

  it("still detects a mix hidden behind a zero-width character", () => {
    const result = sanitizeDisplayString(`${CYRILLIC_A}${ZWSP}pple`);

    expect(result.findings.map((finding) => finding.code)).toEqual(
      expect.arrayContaining(["ZERO_WIDTH_REMOVED", "MIXED_SCRIPT"]),
    );
  });
});

describe("length and whitespace", () => {
  it("truncates a layout-attack length string and says so", () => {
    const result = sanitizeDisplayString("x".repeat(MAX_DISPLAY_LENGTH + 50));

    // The cap plus one ellipsis character.
    expect(result.text).toHaveLength(MAX_DISPLAY_LENGTH + 1);
    expect(result.findings.map((finding) => finding.code)).toContain("TRUNCATED");
    expect(result.originalLength).toBe(MAX_DISPLAY_LENGTH + 50);
  });

  it("collapses runs of whitespace", () => {
    expect(sanitizeDisplayString("  a \n\n  b  ").text).toBe("a b");
  });

  it("treats null and undefined as empty without inventing findings", () => {
    expect(sanitizeDisplayString(null)).toMatchObject({ text: "", suspicious: false });
    expect(sanitizeDisplayString(undefined)).toMatchObject({ text: "", suspicious: false });
  });
});

describe("field classification", () => {
  it("keeps the merchant display name OUT of the authoritative set", () => {
    expect(isTaintedField("merchant_name")).toBe(true);
    expect(isAuthoritativeField("merchant_name")).toBe(false);
  });

  it("keeps the bound merchant ID authoritative", () => {
    expect(isAuthoritativeField("bound_merchant_id")).toBe(true);
    expect(isTaintedField("bound_merchant_id")).toBe(false);
  });

  it("treats the bound product ID as merchant-originated descriptive identity", () => {
    expect(isTaintedField("bound_product_id")).toBe(true);
  });

  it("never lists a field as both authoritative and tainted", () => {
    const overlap = AUTHORITATIVE_FIELDS.filter((field) => TAINTED_FIELDS.includes(field));
    expect(overlap).toEqual([]);
  });

  it("reserves the five headings a merchant string may never wear", () => {
    expect([...RESERVED_AUTHORITATIVE_HEADINGS].sort()).toEqual(
      ["AUTHORIZATION", "PAYEE", "PAYMENT STATE", "POLICY", "TOTAL"].sort(),
    );
  });
});
