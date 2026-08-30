/**
 * Client-side redaction, as the LAST line rather than the first.
 *
 * The API is already built not to disclose these: the authorization nonce never
 * leaves the kernel, `request_fingerprint` is not projected, webhook secrets are
 * server-held, and the attack lab's `observed_effects` are constructed to carry
 * no secret. So nothing here should ever fire.
 *
 * It exists anyway because the console renders two open-ended maps —
 * `AuditEvent.payload` and `AttackResult.observed_effects` — straight to screen.
 * A future backend change that put a sensitive key into either one would
 * otherwise be published by this UI before anyone noticed. A key matching a
 * sensitive name is replaced with a marker that names the rule, so the redaction
 * is visible rather than silent.
 */

const SENSITIVE_KEY_PATTERNS: ReadonlyArray<RegExp> = [
  /nonce/i,
  /secret/i,
  /signature/i,
  /\bapi[_-]?key\b/i,
  /\bprivate[_-]?key\b/i,
  /password/i,
  /\btoken\b/i,
  /authorization[_-]?header/i,
  /webhook[_-]?secret/i,
  /request[_-]?fingerprint/i,
  /razorpay[_-]?key[_-]?secret/i,
];

export const REDACTION_MARKER = "[redacted — sensitive field name]";

export function isSensitiveKey(key: string): boolean {
  return SENSITIVE_KEY_PATTERNS.some((pattern) => pattern.test(key));
}

/** Recursively redact by KEY NAME. Values are never inspected or guessed at. */
export function redact(value: unknown, depth = 0): unknown {
  if (depth > 8) return value;
  if (Array.isArray(value)) return value.map((item) => redact(item, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, inner] of Object.entries(value as Record<string, unknown>)) {
      out[key] = isSensitiveKey(key) ? REDACTION_MARKER : redact(inner, depth + 1);
    }
    return out;
  }
  return value;
}

/**
 * An idempotency key is a client handle, not a secret — but it is also a
 * replay-relevant identifier, so the console shows a stable prefix rather than
 * the whole value. Enough to correlate two views of the same payment; not
 * enough to copy out of a screenshot and reuse.
 */
export function idempotencyFingerprint(key: string | null | undefined): string {
  if (!key) return "—";
  if (key.length <= 12) return `${key.slice(0, 4)}…`;
  return `${key.slice(0, 8)}…${key.slice(-4)}`;
}
