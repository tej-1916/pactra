import { describe, expect, it } from "vitest";

import {
  REDACTION_MARKER,
  idempotencyFingerprint,
  isSensitiveKey,
  redact,
} from "@/lib/redaction";

/**
 * The API is built not to disclose any of these, so nothing here should ever
 * fire in practice. The console renders two open-ended maps straight to screen —
 * audit event payloads and attack-lab observed effects — so a backend change
 * that put a sensitive key into either one must not be published by this UI.
 */
describe("sensitive key detection", () => {
  it.each([
    "nonce",
    "authorization_nonce",
    "webhook_secret",
    "razorpay_key_secret",
    "signature",
    "api_key",
    "private_key",
    "password",
    "token",
    "request_fingerprint",
  ])("flags %s", (key) => {
    expect(isSensitiveKey(key)).toBe(true);
  });

  it.each([
    "reason_code",
    "payment_intents_after",
    "merchant_id",
    "transaction_digest",
    "idempotency_key",
    "sequence",
  ])("does not flag %s", (key) => {
    expect(isSensitiveKey(key)).toBe(false);
  });
});

describe("redact", () => {
  it("replaces a sensitive value with a marker that names the rule", () => {
    const redacted = redact({ nonce: "deadbeef", amount_inr: 3799 }) as Record<string, unknown>;
    expect(redacted.nonce).toBe(REDACTION_MARKER);
    expect(redacted.amount_inr).toBe(3799);
  });

  it("recurses into nested objects and arrays", () => {
    const redacted = redact({
      events: [{ payload: { webhook_secret: "s3cret", state: "SUCCEEDED" } }],
    }) as { events: { payload: Record<string, unknown> }[] };
    expect(redacted.events[0]?.payload.webhook_secret).toBe(REDACTION_MARKER);
    expect(redacted.events[0]?.payload.state).toBe("SUCCEEDED");
  });

  it("leaves ordinary evidence maps untouched", () => {
    const effects = {
      payment_intents_before: 1,
      payment_intents_after: 1,
      provider_payments_before: 1,
      provider_payments_after: 1,
      blocked: true,
    };
    expect(redact(effects)).toEqual(effects);
  });

  it("terminates on deeply nested input rather than recursing without bound", () => {
    let nested: unknown = { nonce: "x" };
    for (let i = 0; i < 40; i += 1) nested = { inner: nested };
    expect(() => redact(nested)).not.toThrow();
  });
});

describe("idempotencyFingerprint", () => {
  it("never renders the whole key", () => {
    const key = "pactra-console-6f1c2b90-1111-2222-3333-444455556666";
    const shown = idempotencyFingerprint(key);
    expect(shown).not.toBe(key);
    expect(shown).toContain("…");
    expect(key).toContain(shown.split("…")[0] ?? "");
  });

  it("renders a placeholder rather than an empty string for a missing key", () => {
    expect(idempotencyFingerprint(null)).toBe("—");
  });
});
