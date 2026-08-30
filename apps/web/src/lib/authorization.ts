/**
 * How an authorization became active — stated exactly, and never upgraded.
 *
 * Three schemes exist and they are three different facts. The failure this
 * module is built to prevent is a UI that renders a deterministic policy
 * activation as though a human had approved it:
 *
 *   POLICY_AUTO    deterministic policy activated this. NO human approved it,
 *                  nothing was signed, and no cryptographic proof exists.
 *   USER_ED25519   a local Ed25519 approval proof over server-reconstructed
 *                  canonical bytes verified against a PRE-ENROLLED public key.
 *   LEGACY_SERVER  migration-only. It fails closed for payment.
 *
 * The wording is equally careful about what USER_ED25519 does NOT establish.
 * PACTRA has no production enrollment, rotation, recovery or revocation
 * registry, no WebAuthn, no passkeys, and no identity proofing — so the copy
 * says "the pre-enrolled demo signing key", never "the user", and never claims
 * verified identity or non-repudiation. Those claims are listed in
 * `OVERCLAIMS` and asserted against in the test suite so a future edit that
 * reintroduces one fails rather than ships.
 *
 * No signature, private key, nonce, or approval-message byte is presented by
 * any consumer of this module. The API does not send the first three, and the
 * fourth is displayed only on the challenge screen it belongs to.
 */

import type { ApprovalScheme } from "@/lib/types/pactra";
import type { Tone } from "@/lib/semantics";

export interface ApprovalSchemePresentation {
  /** The machine value, printed verbatim. Always. */
  code: ApprovalScheme;
  /** A short label. It never contains the word "user" for POLICY_AUTO. */
  label: string;
  /** One line: what this scheme actually established. */
  headline: string;
  /** The precise mechanism, and its limits. */
  detail: string;
  /** What this scheme explicitly does NOT establish. Never omitted. */
  notEstablished: string;
  tone: Tone;
  /** True only when a person approved. `POLICY_AUTO` is false. */
  humanApproved: boolean;
  /** True only when a cryptographic proof was verified. */
  cryptographic: boolean;
  /** True when this scheme cannot authorize a payment. */
  failsClosedForPayment: boolean;
}

export const APPROVAL_SCHEMES: Readonly<Record<ApprovalScheme, ApprovalSchemePresentation>> = {
  POLICY_AUTO: {
    code: "POLICY_AUTO",
    label: "Deterministic policy activation",
    headline: "Activated by deterministic policy. No person approved this, and nothing was signed.",
    detail:
      "The request satisfied every deterministic policy rule, so the kernel activated the authorization itself. The authority comes from the policy the user set at the trusted API boundary, evaluated by the server.",
    notEstablished:
      "This is not human approval, not a signature, and not a cryptographic proof. No approval message exists for it.",
    tone: "accent",
    humanApproved: false,
    cryptographic: false,
    failsClosedForPayment: false,
  },
  USER_ED25519: {
    code: "USER_ED25519",
    label: "Cryptographic approval proof",
    headline:
      "An Ed25519 signature over the server-reconstructed canonical approval message verified against the pre-enrolled public key.",
    detail:
      "The private key lives outside PACTRA entirely and is never sent to it. The API holds only the configured public key and its key ID, compares the presented key ID against server configuration, and always verifies over bytes it rebuilt from durable state — never over bytes a caller supplied.",
    notEstablished:
      "It does not establish a verified identity, non-repudiation, or a production credential. PACTRA implements no identity proofing, no key enrollment, rotation, recovery or revocation registry, no WebAuthn and no passkeys.",
    tone: "secure",
    humanApproved: true,
    cryptographic: true,
    failsClosedForPayment: false,
  },
  LEGACY_SERVER: {
    code: "LEGACY_SERVER",
    label: "Legacy server scheme — migration only",
    headline: "A pre-migration scheme. It cannot authorize a payment and fails closed.",
    detail:
      "Retained so historical records replay faithfully. The payment path refuses it rather than treating it as an approval of any kind.",
    notEstablished: "It is neither human approval nor a cryptographic proof.",
    tone: "critical",
    humanApproved: false,
    cryptographic: false,
    failsClosedForPayment: true,
  },
};

/**
 * Claims no scheme's copy may make.
 *
 * Every one of these is either false for `POLICY_AUTO` or unsupported by the
 * backend for all three. Kept as data so the test suite can scan the whole
 * presentation table rather than the one string a reviewer happened to read.
 */
export const OVERCLAIMS: readonly string[] = [
  "human approved",
  "approved by the user",
  "signed by user",
  "signed by the user",
  "cryptographically approved by user",
  "cryptographically approved by the user",
  "verified identity",
  "non-repudiation",
  "webauthn",
  "passkey",
  "production identity",
];

export function describeApprovalScheme(
  scheme: ApprovalScheme | null | undefined,
): ApprovalSchemePresentation | null {
  if (!scheme) return null;
  return APPROVAL_SCHEMES[scheme] ?? null;
}

/**
 * The one-line answer to "who authorized this?".
 *
 * Deliberately blunt, because this string is what lands beside an amount on a
 * dense screen and is the sentence a reader will remember.
 */
export function authorityStatement(scheme: ApprovalScheme | null | undefined): string {
  const presentation = describeApprovalScheme(scheme);
  if (!presentation) return "No authorization scheme recorded.";
  switch (presentation.code) {
    case "POLICY_AUTO":
      return "Authorized by deterministic policy — not by a person.";
    case "USER_ED25519":
      return "Authorized by a verified Ed25519 approval proof from the pre-enrolled signing key.";
    case "LEGACY_SERVER":
      return "Legacy scheme. Not a valid authorization for payment.";
  }
}
