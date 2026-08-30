import { describe, expect, it } from "vitest";

import {
  APPROVAL_SCHEMES,
  authorityStatement,
  describeApprovalScheme,
  OVERCLAIMS,
} from "@/lib/authorization";
import type { ApprovalScheme } from "@/lib/types/pactra";

const SCHEMES: ApprovalScheme[] = ["POLICY_AUTO", "USER_ED25519", "LEGACY_SERVER"];

/**
 * The distinction these tests protect is the reason the scheme field exists: a
 * deterministic policy activation must never be presented as a person
 * approving something, and a verified signature must never be inflated into a
 * verified identity. Both errors flatter the system in the same direction.
 */
describe("POLICY_AUTO wording", () => {
  const scheme = APPROVAL_SCHEMES.POLICY_AUTO;

  it("states that no person approved it and nothing was signed", () => {
    expect(scheme.humanApproved).toBe(false);
    expect(scheme.cryptographic).toBe(false);
    expect(scheme.headline).toMatch(/no person approved/i);
    expect(scheme.headline).toMatch(/nothing was signed/i);
  });

  it("names deterministic policy as the source of the authority", () => {
    expect(scheme.label).toMatch(/deterministic policy/i);
    expect(authorityStatement("POLICY_AUTO")).toMatch(/not by a person/i);
  });

  it("never uses signature, approval-proof or human-approval language", () => {
    const copy = [scheme.label, scheme.headline, scheme.detail, authorityStatement("POLICY_AUTO")]
      .join(" ")
      .toLowerCase();

    expect(copy).not.toMatch(/\bsigned by\b/);
    expect(copy).not.toMatch(/human approved/);
    expect(copy).not.toMatch(/cryptographic proof/);
    expect(copy).not.toMatch(/approved by the user/);
  });
});

describe("USER_ED25519 wording", () => {
  const scheme = APPROVAL_SCHEMES.USER_ED25519;

  it("describes the cryptographic proof accurately", () => {
    expect(scheme.cryptographic).toBe(true);
    expect(scheme.headline).toMatch(/ed25519 signature/i);
    expect(scheme.headline).toMatch(/pre-enrolled public key/i);
    expect(scheme.detail).toMatch(/rebuilt from durable state/i);
  });

  it("refuses the identity and non-repudiation claims the backend does not support", () => {
    expect(scheme.notEstablished).toMatch(/does not establish a verified identity/i);
    expect(scheme.notEstablished).toMatch(/non-repudiation/i);
    expect(scheme.notEstablished).toMatch(/webauthn/i);
    expect(scheme.notEstablished).toMatch(/passkeys/i);
  });
});

describe("LEGACY_SERVER wording", () => {
  it("says it fails closed for payment and is not an approval of any kind", () => {
    const scheme = APPROVAL_SCHEMES.LEGACY_SERVER;

    expect(scheme.failsClosedForPayment).toBe(true);
    expect(scheme.humanApproved).toBe(false);
    expect(scheme.cryptographic).toBe(false);
    expect(authorityStatement("LEGACY_SERVER")).toMatch(/not a valid authorization for payment/i);
  });
});

describe("the whole presentation table", () => {
  it("makes no overclaim in any scheme's ASSERTED copy", () => {
    // `notEstablished` is excluded on purpose: it is the field whose job is to
    // NAME these claims and deny them, so scanning it would be self-defeating.
    for (const code of SCHEMES) {
      const scheme = APPROVAL_SCHEMES[code];
      const asserted = [scheme.label, scheme.headline, scheme.detail, authorityStatement(code)]
        .join(" ")
        .toLowerCase();

      for (const claim of OVERCLAIMS) {
        expect(asserted, `${code} / ${claim}`).not.toContain(claim);
      }
    }
  });

  it("prints the machine value verbatim as the code", () => {
    for (const code of SCHEMES) {
      expect(APPROVAL_SCHEMES[code].code).toBe(code);
    }
  });

  it("returns null for a missing scheme rather than defaulting to a benign one", () => {
    expect(describeApprovalScheme(null)).toBeNull();
    expect(describeApprovalScheme(undefined)).toBeNull();
    expect(authorityStatement(null)).toMatch(/no authorization scheme recorded/i);
  });

  it("exposes no field that could carry a signature or key material", () => {
    for (const code of SCHEMES) {
      const keys = Object.keys(APPROVAL_SCHEMES[code]);
      expect(keys.some((key) => /signature|private|secret|nonce/i.test(key))).toBe(false);
    }
  });
});
