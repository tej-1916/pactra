/**
 * Safe presentation of merchant-controlled strings.
 *
 * The C1 trust contract puts the requirement plainly: no merchant string may
 * visually masquerade as TOTAL, PAYEE, POLICY, AUTHORIZATION or PAYMENT STATE.
 * The backend already keeps the two apart in the data — free-form description
 * is dropped at ingress, and the bound amount, currency and merchant ID come
 * from server-side state rather than from a payload. What is left is a
 * PRESENTATION problem, and it is a real one: a title carrying a bidi override
 * can render right-to-left across a neighbouring cell, a zero-width joiner can
 * hide the difference between two merchant names, and a Cyrillic "a" is
 * indistinguishable from a Latin "a" at 12px.
 *
 * So every merchant-originated string passes through `sanitizeDisplayString`
 * before it reaches the DOM, and what is removed is REPORTED rather than
 * silently swallowed. A quietly-cleaned string is a string whose attack nobody
 * ever saw.
 *
 * This is defence in depth at the last layer, not the first. It does not
 * replace the ingress classification that already happened, and it makes no
 * claim to be a complete confusable-detection implementation — it handles the
 * classes that are practical at the presentation layer and says so.
 */

// --------------------------------------------------------------------------- //
// Field classification — straight from `docs/c1-trust-contract.md`
// --------------------------------------------------------------------------- //

/**
 * Machine-authoritative for the exact proposed payment. These may carry a
 * TOTAL / PAYEE / POLICY / AUTHORIZATION / PAYMENT STATE heading.
 */
export const AUTHORITATIVE_FIELDS: readonly string[] = [
  "bound_merchant_id",
  "bound_amount_inr",
  "bound_currency",
  "bound_quantity",
  "expires_at",
  "approval_scheme",
  "signing_key_id",
  "transaction_digest",
  "binding_version",
  "policy_version",
  "offer_version",
  "policy_outcome",
  "payment_state",
  "authorization_status",
];

/**
 * Merchant-supplied or registry display data. These may NEVER carry one of
 * those headings, and every one of them renders through `TaintedText`.
 *
 * `merchant_name` is on this list on purpose: it is server-registry DISPLAY
 * data, not cryptographic merchant identity, and it must never stand in for the
 * authoritative merchant ID. `bound_product_id` is here too — it is
 * integrity-protected as the exact selected value, and it is still
 * merchant-originated descriptive identity.
 */
export const TAINTED_FIELDS: readonly string[] = [
  "title",
  "product_id",
  "bound_product_id",
  "merchant_name",
  "description",
  "raw_query",
  "merchant_payload_price",
  "merchant_payload_currency",
];

/** Headings a merchant string may never be rendered under. */
export const RESERVED_AUTHORITATIVE_HEADINGS: readonly string[] = [
  "TOTAL",
  "PAYEE",
  "POLICY",
  "AUTHORIZATION",
  "PAYMENT STATE",
];

export function isAuthoritativeField(field: string): boolean {
  return AUTHORITATIVE_FIELDS.includes(field);
}

export function isTaintedField(field: string): boolean {
  return TAINTED_FIELDS.includes(field);
}

// --------------------------------------------------------------------------- //
// Sanitization
// --------------------------------------------------------------------------- //

export type TaintFindingCode =
  | "BIDI_CONTROL_REMOVED"
  | "CONTROL_CHARACTER_REMOVED"
  | "ZERO_WIDTH_REMOVED"
  | "MIXED_SCRIPT"
  | "TRUNCATED"
  | "EMPTY_AFTER_SANITIZATION";

export interface TaintFinding {
  code: TaintFindingCode;
  /** What was found and why it matters. Shown to the reader, not just logged. */
  detail: string;
}

export interface SanitizedDisplay {
  /** Safe to place in the DOM as text. */
  text: string;
  /** Non-empty when the raw string was modified or is suspicious. */
  findings: TaintFinding[];
  /** True when anything at all was found. */
  suspicious: boolean;
  /** The length of the string as received, before any truncation. */
  originalLength: number;
}

/*
 * Two regexes per class: one non-global for detection, one global for removal.
 *
 * Not a style choice. `RegExp.prototype.test` on a `/g/` pattern advances
 * `lastIndex` and resumes from there on the next call, so a single shared
 * global regex would start mid-string on the second row of a table and miss a
 * match at the front of it. A stateful regex silently skipping an attack string
 * on row two is precisely the bug this file exists to prevent.
 */

/**
 * Bidirectional formatting characters: the LRE/RLE/PDF/LRO/RLO run at
 * U+202A-202E, the isolates at U+2066-2069, LRM/RLM, and the Arabic letter
 * mark. One RLO in a product title is enough to make the text after it read
 * backwards across whatever sits beside it on the row.
 */
const BIDI_SOURCE = "[\\u202A-\\u202E\\u2066-\\u2069\\u200E\\u200F\\u061C]";
const HAS_BIDI = new RegExp(BIDI_SOURCE, "u");
const ALL_BIDI = new RegExp(BIDI_SOURCE, "gu");

/**
 * Zero-width and invisible characters. They make two different strings look
 * identical, which is the whole trick.
 */
const ZERO_WIDTH_SOURCE = "[\\u200B-\\u200D\\u2060\\uFEFF\\u00AD]";
const HAS_ZERO_WIDTH = new RegExp(ZERO_WIDTH_SOURCE, "u");
const ALL_ZERO_WIDTH = new RegExp(ZERO_WIDTH_SOURCE, "gu");

/**
 * C0/C1 control characters, with nothing exempted: a display string has no
 * legitimate use for a newline, a tab, or an escape either. Replaced with a
 * space rather than deleted, so words do not run together.
 */
const CONTROL_SOURCE = "[\\u0000-\\u0008\\u000A-\\u001F\\u007F-\\u009F]";
const HAS_CONTROL = new RegExp(CONTROL_SOURCE, "u");
const ALL_CONTROL = new RegExp(CONTROL_SOURCE, "gu");

/** The scripts whose letters are most commonly confused with one another. */
const SCRIPT_PATTERNS: ReadonlyArray<{ name: string; pattern: RegExp }> = [
  { name: "Latin", pattern: /\p{Script=Latin}/u },
  { name: "Cyrillic", pattern: /\p{Script=Cyrillic}/u },
  { name: "Greek", pattern: /\p{Script=Greek}/u },
];

/** A display string longer than this is a layout attack, not a product title. */
export const MAX_DISPLAY_LENGTH = 240;

/**
 * Clean one merchant-controlled string for display, and say what was cleaned.
 *
 * Order matters. Invisibles come out before the script check, so a string
 * hiding its Cyrillic behind a zero-width joiner still reports as mixed-script
 * rather than slipping through on a technicality.
 *
 * A mixed-script string is REPORTED and displayed as received. It is not
 * transliterated or "corrected": silently rewriting a merchant's characters
 * would make the console lie about what the merchant actually sent.
 */
export function sanitizeDisplayString(raw: string | null | undefined): SanitizedDisplay {
  const original = raw ?? "";
  const findings: TaintFinding[] = [];
  let text = original;

  if (HAS_BIDI.test(text)) {
    findings.push({
      code: "BIDI_CONTROL_REMOVED",
      detail:
        "Contained bidirectional formatting characters, which can reorder how text renders across neighbouring fields. Removed.",
    });
    text = text.replace(ALL_BIDI, "");
  }

  if (HAS_ZERO_WIDTH.test(text)) {
    findings.push({
      code: "ZERO_WIDTH_REMOVED",
      detail:
        "Contained zero-width or invisible characters, which can make two different strings look identical. Removed.",
    });
    text = text.replace(ALL_ZERO_WIDTH, "");
  }

  if (HAS_CONTROL.test(text)) {
    findings.push({
      code: "CONTROL_CHARACTER_REMOVED",
      detail: "Contained control characters. Replaced with spaces.",
    });
    text = text.replace(ALL_CONTROL, " ");
  }

  const scripts = SCRIPT_PATTERNS.filter((script) => script.pattern.test(text)).map(
    (script) => script.name,
  );
  if (scripts.length > 1) {
    findings.push({
      code: "MIXED_SCRIPT",
      detail: `Mixes ${scripts.join(" and ")} letters, which are visually confusable. Shown as received, not corrected.`,
    });
  }

  text = text.replace(/\s+/gu, " ").trim();

  if (text.length > MAX_DISPLAY_LENGTH) {
    findings.push({
      code: "TRUNCATED",
      detail: `Longer than ${MAX_DISPLAY_LENGTH} characters. Truncated for display; the stored value is unchanged.`,
    });
    text = `${text.slice(0, MAX_DISPLAY_LENGTH)}…`;
  }

  if (original.length > 0 && text.length === 0) {
    findings.push({
      code: "EMPTY_AFTER_SANITIZATION",
      detail:
        "Consisted entirely of formatting or control characters. Nothing displayable remained.",
    });
  }

  return { text, findings, suspicious: findings.length > 0, originalLength: original.length };
}
