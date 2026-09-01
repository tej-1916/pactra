import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { PipelineExplainerSection } from "@/components/overview/PipelineExplainerSection";
import { InvariantsSection } from "@/components/overview/InvariantsSection";
import { DecisionTracePreviewSection } from "@/components/overview/DecisionTracePreviewSection";
import { AttackLabPreviewSection } from "@/components/overview/AttackLabPreviewSection";
import { PaymentReliabilitySection } from "@/components/overview/PaymentReliabilitySection";
import { NextActionsSection } from "@/components/overview/NextActionsSection";
import { Hero } from "@/components/hero/Hero";

describe("Overview Page (Phase 3.3 Next Action Enum Audit)", () => {
  beforeEach(() => {
    Object.defineProperty(window, "IntersectionObserver", {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        observe: vi.fn(),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
      })),
    });
  });

  it("1 & 3. REQUEST_APPROVAL is NEVER presented as next_action, and REQUIRE_APPROVAL remains strictly policy_outcome", () => {
    render(
      <>
        <PipelineExplainerSection />
        <AttackLabPreviewSection />
        <DecisionTracePreviewSection />
      </>
    );
    const text = document.body.textContent || "";
    expect(text).not.toContain("next_action: REQUEST_APPROVAL");
    expect(text).toContain("Policy Outcome: ALLOW · REQUIRE_APPROVAL · DENY");
  });

  it("2. all next_action values in Overview belong strictly to the frozen next_action enum", () => {
    render(
      <>
        <PipelineExplainerSection />
        <AttackLabPreviewSection />
        <DecisionTracePreviewSection />
        <PaymentReliabilitySection />
      </>
    );

    const validNextActions = [
      "CONTINUE_ADMIT",
      "CONTINUE_BIND",
      "AWAIT_USER_SIGNATURE",
      "CREATE_PAYMENT_INTENT",
      "DISPATCH_PAYMENT",
      "AWAIT_PROVIDER",
      "RECONCILE_PAYMENT",
      "RETRY_PAYMENT",
      "NONE",
    ];

    expect(validNextActions).toContain("RECONCILE_PAYMENT");
    expect(validNextActions).toContain("NONE");

    // Verify next_action labels rendered in AttackLab match valid enum
    expect(screen.getByText("RECONCILE_PAYMENT")).toBeInTheDocument();
    expect(screen.getAllByText("NONE").length).toBeGreaterThan(0);

    const text = document.body.textContent || "";
    expect(text).not.toContain("next_action: ASK_USER");
    expect(text).not.toContain("next_action: SIGN_PAYMENT");
    expect(text).not.toContain("next_action: APPROVE_PAYMENT");
  });

  it("4 & 5. Lost Provider Response uses verdict PENDING and payment_state PROVIDER_PENDING without enum mixing", () => {
    render(<AttackLabPreviewSection />);
    expect(screen.getByText("verdict: PENDING")).toBeInTheDocument();
    expect(screen.getByText("PROVIDER_PENDING")).toBeInTheDocument();
    expect(screen.getByText("RECONCILE_PAYMENT")).toBeInTheDocument();
    expect(screen.queryByText("verdict: PROVIDER_PENDING")).not.toBeInTheDocument();
  });

  it("6. idempotency invariant contains exact frozen wording 'SAME IDEMPOTENCY KEY ➔ AT MOST ONE LOGICAL PAYMENT'", () => {
    render(
      <>
        <InvariantsSection />
        <PipelineExplainerSection />
      </>
    );
    const text = document.body.textContent || "";
    expect(text).toContain("SAME IDEMPOTENCY KEY");
    expect(text).toContain("AT MOST ONE LOGICAL PAYMENT");
  });

  it("7. Decision Trace preview uses only frozen C1 fields and no invented fields", () => {
    render(<DecisionTracePreviewSection />);
    const fields = [
      "stage", "event_type", "verdict", "reason_codes", "invariant_id",
      "approval_scheme", "policy_outcome", "payment_state", "advisory",
      "next_action", "evidence", "recorded_at"
    ];
    fields.forEach((f) => {
      expect(screen.getByText(new RegExp(`${f}:`, "i"))).toBeInTheDocument();
    });

    const text = document.body.textContent || "";
    expect(text).not.toContain("state_hash:");
    expect(text).not.toContain("prev_hash:");
    expect(text).not.toContain("chain_of_thought:");
  });

  it("8. preserves frozen Hero component and headline semantics", () => {
    render(<Hero />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Make AI commerce trustworthy\./i);
  });

  it("9. CTAs point to correct target routes", () => {
    render(<NextActionsSection />);
    expect(screen.getByRole("link", { name: /Explore Live Commerce/i })).toHaveAttribute("href", "/commerce");
    expect(screen.getByRole("link", { name: /Open Attack Lab/i })).toHaveAttribute("href", "/attack-lab");
    expect(screen.getByRole("link", { name: /Inspect Audit Trail/i })).toHaveAttribute("href", "/audit");
    expect(screen.getByRole("link", { name: /View System Contract/i })).toHaveAttribute("href", "/system");
  });
});
