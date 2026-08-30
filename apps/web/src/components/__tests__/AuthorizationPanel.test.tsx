import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthorizationPanel } from "@/components/mission/AuthorizationPanel";
import { SignedApprovalPanel } from "@/components/mission/SignedApprovalPanel";
import type { ApprovalChallenge, ApprovalScheme, Authorization } from "@/lib/types/pactra";

/**
 * The distinction these tests protect is the whole point of the scheme field:
 * a deterministic policy ALLOW must never be presented as a person approving
 * something. A console that blurred the two would misreport the security
 * property in exactly the direction that flatters the system.
 */

function authorization(
  approval_scheme: ApprovalScheme,
  overrides: Partial<Authorization> = {},
): Authorization {
  return {
    authorization_id: "11111111-1111-4111-8111-111111111111",
    mission_id: "22222222-2222-4222-8222-222222222222",
    status: "ACTIVE",
    transaction_digest: "a".repeat(64),
    binding_version: "binding-v1",
    policy_version: "policy-v1",
    offer_version: "offer-v1",
    approval_scheme,
    signing_key_id: null,
    issued_at: "2026-08-30T10:00:00Z",
    expires_at: "2026-08-30T10:15:00Z",
    consumed_at: null,
    bound_merchant_id: "merchant_a",
    bound_product_id: "P1",
    bound_quantity: 1,
    bound_amount_inr: 3799,
    bound_currency: "INR",
    ...overrides,
  };
}

describe("AuthorizationPanel activation origin", () => {
  it("never describes POLICY_AUTO as human or signed approval", () => {
    render(<AuthorizationPanel authorization={authorization("POLICY_AUTO")} />);

    expect(screen.getByText("POLICY_AUTO")).toBeInTheDocument();
    expect(screen.getByText(/Deterministic policy ALLOW — not human approval/i)).toBeInTheDocument();
    expect(screen.getByText("NO USER SIGNATURE")).toBeInTheDocument();
    expect(screen.queryByText(/USER-SIGNED ACTIVATION/i)).toBeNull();
    expect(screen.queryByText(/approved by a human/i)).toBeNull();
  });

  it("labels USER_ED25519 as a cryptographic proof and shows the signing key id", () => {
    render(
      <AuthorizationPanel
        authorization={authorization("USER_ED25519", { signing_key_id: "demo-user-ed25519-v1" })}
      />,
    );

    expect(screen.getByText("USER_ED25519")).toBeInTheDocument();
    expect(screen.getByText("USER-SIGNED ACTIVATION")).toBeInTheDocument();
    expect(screen.getByText("demo-user-ed25519-v1")).toBeInTheDocument();
  });

  it("keeps the demo-key scoping visible rather than claiming production identity", () => {
    render(
      <AuthorizationPanel
        authorization={authorization("USER_ED25519", { signing_key_id: "demo-user-ed25519-v1" })}
      />,
    );

    // Stated twice on purpose: once beside the scheme, once in the KL-04
    // footer. Neither placement is allowed to be the only one.
    expect(screen.getAllByText(/not production identity/i)).toHaveLength(2);
    expect(screen.getAllByText(/non-repudiation/i)).toHaveLength(2);
  });

  it("marks a migration-only LEGACY_SERVER row as failing closed", () => {
    render(<AuthorizationPanel authorization={authorization("LEGACY_SERVER")} />);

    expect(screen.getByText("LEGACY_SERVER")).toBeInTheDocument();
    expect(screen.getByText(/fails closed for payment/i)).toBeInTheDocument();
    expect(screen.queryByText("USER-SIGNED ACTIVATION")).toBeNull();
  });

  it("shows an unknown scheme verbatim instead of normalising it into a known label", () => {
    render(
      <AuthorizationPanel
        authorization={authorization("SOMETHING_ELSE" as ApprovalScheme)}
      />,
    );

    expect(screen.getByText("SOMETHING_ELSE")).toBeInTheDocument();
    expect(screen.getByText(/Unrecognised activation origin/i)).toBeInTheDocument();
  });
});

describe("SignedApprovalPanel", () => {
  const challenge: ApprovalChallenge = {
    authorization_id: "11111111-1111-4111-8111-111111111111",
    mission_id: "22222222-2222-4222-8222-222222222222",
    binding_version: "binding-v1",
    transaction_digest: "b".repeat(64),
    signing_key_id: "demo-user-ed25519-v1",
    approval_scheme: "USER_ED25519",
    approval_message_hex: "c".repeat(120),
    transaction: {
      merchant: "merchant_a",
      product: "P1",
      quantity: 2,
      amount: 4200,
      currency: "INR",
      expiry: "2026-08-30T10:15:00Z",
    },
  };

  it("offers no way to supply a private key to the browser", () => {
    const { container } = render(
      <SignedApprovalPanel challenge={challenge} onApprove={() => {}} />,
    );

    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(container.querySelector('input[type="file"]')).toBeNull();
    // Exactly one free-text field, and it takes the SIGNATURE — never a key.
    const fields = container.querySelectorAll("textarea, input");
    expect(fields).toHaveLength(1);
    expect(screen.getByLabelText(/Signature from the external signer/i)).toBeInTheDocument();
  });

  it("shows the transaction the signature will commit to", () => {
    render(<SignedApprovalPanel challenge={challenge} onApprove={() => {}} />);

    expect(screen.getByText("merchant_a")).toBeInTheDocument();
    expect(screen.getByText("P1")).toBeInTheDocument();
    expect(screen.getByText(/What the signature will commit to/i)).toBeInTheDocument();
  });

  it("keeps submission disabled until the signature is well formed", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(<SignedApprovalPanel challenge={challenge} onApprove={() => {}} />);

    const submit = screen.getByRole("button", { name: /Submit approval proof/i });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText(/Signature from the external signer/i), "nothex");
    expect(submit).toBeDisabled();
    expect(screen.getByText(/128 lowercase hexadecimal characters; got 6/i)).toBeInTheDocument();
  });

  it("submits the signature together with the server-chosen signing key id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    const submissions: { signing_key_id: string; signature: string }[] = [];
    render(
      <SignedApprovalPanel
        challenge={challenge}
        onApprove={(submission) => submissions.push(submission)}
      />,
    );

    const signature = "d".repeat(128);
    await user.type(screen.getByLabelText(/Signature from the external signer/i), signature);
    await user.click(screen.getByRole("button", { name: /Submit approval proof/i }));

    expect(submissions).toEqual([
      { signing_key_id: "demo-user-ed25519-v1", signature },
    ]);
  });
});
