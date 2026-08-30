import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthorizationSchemeCard } from "@/components/authorization/AuthorizationScheme";
import { PaymentReadModel } from "@/components/payment/PaymentReadModel";
import type { PaymentIntent } from "@/lib/types/pactra";

/** A TEST FIXTURE. Hand-written for this file; nothing here is backend data. */
function paymentIntent(overrides: Partial<PaymentIntent> = {}): PaymentIntent {
  return {
    payment_intent_id: "33333333-3333-4333-8333-333333333333",
    mission_id: "22222222-2222-4222-8222-222222222222",
    authorization_id: "11111111-1111-4111-8111-111111111111",
    state: "QUEUED",
    idempotency_key: "pactra-console-test-fixture-key",
    amount_inr: 4999,
    currency: "INR",
    merchant_id: "merchant_a",
    provider: "fake",
    provider_payment_id: null,
    attempts: 0,
    last_reason_code: null,
    created_at: "2026-08-30T12:44:54Z",
    ...overrides,
  };
}

describe("payment state rendering", () => {
  it("prints the machine state verbatim with its meaning beside it", () => {
    render(<PaymentReadModel intent={paymentIntent({ state: "PROVIDER_PENDING" })} />);

    expect(screen.getAllByText("PROVIDER_PENDING").length).toBeGreaterThan(0);
    expect(screen.getByText(/only way out is reconciliation/i)).toBeInTheDocument();
  });

  it("renders the PACTRA intent id and provider separately", () => {
    render(<PaymentReadModel intent={paymentIntent()} />);

    expect(screen.getByText("33333333-3333-4333-8333-333333333333")).toBeInTheDocument();
    expect(screen.getByText("fake")).toBeInTheDocument();
  });

  it("shows NOT YET PROVIDED for fields the C1 contract does not expose", () => {
    render(<PaymentReadModel intent={paymentIntent()} />);

    const slots = screen.getAllByText("NOT YET PROVIDED");
    expect(slots).toHaveLength(3); // provider order id, reconciliation state, updated at

    for (const slot of slots) {
      expect(slot.closest("span")?.getAttribute("title")).toMatch(/Nothing is inferred/i);
    }
    expect(screen.getByText(/Provider order ID/i)).toBeInTheDocument();
    expect(screen.getByText(/Reconciliation state/i)).toBeInTheDocument();
  });

  it("distinguishes a null provider payment id from an unavailable field", () => {
    render(<PaymentReadModel intent={paymentIntent()} />);

    expect(
      screen.getByText(/null — no provider payment has been reported/i),
    ).toBeInTheDocument();
  });

  it("explains a null reason code as a cleared reason rather than as nothing", () => {
    render(<PaymentReadModel intent={paymentIntent()} />);

    expect(screen.getByText(/cleared reason and an absent one are different facts/i)).toBeInTheDocument();
  });

  it("prints a real reason code verbatim with its description", () => {
    render(
      <PaymentReadModel
        intent={paymentIntent({
          state: "FAILED_RETRYABLE",
          last_reason_code: "PROVIDER_TRANSIENT_FAILURE",
        })}
      />,
    );

    expect(screen.getByText("PROVIDER_TRANSIENT_FAILURE")).toBeInTheDocument();
    expect(screen.getByText(/may succeed on retry/i)).toBeInTheDocument();
  });

  it("shows the idempotency key as a prefix, never in full", () => {
    render(<PaymentReadModel intent={paymentIntent()} />);

    expect(screen.queryByText("pactra-console-test-fixture-key")).toBeNull();
    // Head and tail, with the middle elided: enough to correlate two views of
    // one payment, not enough to lift from a screenshot and reuse.
    expect(screen.getByText("pactra-c…-key")).toBeInTheDocument();
  });

  it("offers no control that could change state", () => {
    render(<PaymentReadModel intent={paymentIntent()} />);

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText("READ-ONLY")).toBeInTheDocument();
  });
});

describe("authorization scheme card", () => {
  it("never presents POLICY_AUTO as a person approving anything", () => {
    render(<AuthorizationSchemeCard scheme="POLICY_AUTO" />);

    const card = screen.getByTestId("authorization-scheme");
    expect(card.dataset.scheme).toBe("POLICY_AUTO");
    expect(within(card).getByText("POLICY_AUTO")).toBeInTheDocument();
    expect(within(card).getByText(/not by a person/i)).toBeInTheDocument();
    expect(within(card).getByText(/No person approved this/i)).toBeInTheDocument();

    const humanApproved = within(card).getByText("Human approved").parentElement!;
    expect(within(humanApproved).getByText("NO")).toBeInTheDocument();
  });

  it("shows no signing key row for a scheme with no cryptographic proof", () => {
    render(<AuthorizationSchemeCard scheme="POLICY_AUTO" signingKeyId={null} />);

    expect(screen.queryByText("Signing key ID")).toBeNull();
  });

  it("describes USER_ED25519 as a verified proof and states its limits", () => {
    render(
      <AuthorizationSchemeCard scheme="USER_ED25519" signingKeyId="demo-user-ed25519-v1" />,
    );

    const card = screen.getByTestId("authorization-scheme");
    expect(within(card).getByText(/Ed25519 approval proof/i)).toBeInTheDocument();
    expect(within(card).getByText("demo-user-ed25519-v1")).toBeInTheDocument();
    expect(within(card).getByText(/does not establish a verified identity/i)).toBeInTheDocument();
    expect(within(card).getByText(/no WebAuthn and no passkeys/i)).toBeInTheDocument();
  });

  it("renders the key ID only — never a signature or key material", () => {
    const { container } = render(
      <AuthorizationSchemeCard scheme="USER_ED25519" signingKeyId="demo-user-ed25519-v1" />,
    );

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[A-Fa-f0-9]{40,}/);
    expect(text).not.toMatch(/-----BEGIN/);
    expect(text).toMatch(/Key material is never sent to this console|private key lives outside/i);
  });

  it("marks LEGACY_SERVER as failing closed for payment", () => {
    render(<AuthorizationSchemeCard scheme="LEGACY_SERVER" />);

    expect(screen.getByText("FAILS CLOSED FOR PAYMENT")).toBeInTheDocument();
    expect(screen.getByText(/Not a valid authorization for payment/i)).toBeInTheDocument();
  });

  it("says nothing is authorized when no scheme was recorded", () => {
    render(<AuthorizationSchemeCard scheme={null} />);

    expect(screen.getByText(/No approval scheme recorded/i)).toBeInTheDocument();
    expect(screen.queryByTestId("authorization-scheme")).toBeNull();
  });
});
