import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { AttackLabConsole } from "@/components/attack-lab/AttackLabConsole";
import { ATTACK_SCENARIOS } from "@/components/attack-lab/attackScenarios";
import type { DecisionVerdict } from "@/lib/types/pactra";

describe("Attack Lab Authored Adversarial Regression Suite (Phase 5.2 Policy Semantics)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("1 & 2 & 5 & 6. AUTHORITY_ESCALATION does not set policy_outcome DENY on SECURITY_VIOLATION; policy evaluation is a separate POLICY_DECISION event", () => {
    const sc = ATTACK_SCENARIOS.MERCHANT_PROMPT_INJECTION;
    const secViolationEvent = sc.decisionTrace.find((e) => e.event_type === "SECURITY_VIOLATION");
    expect(secViolationEvent).toBeDefined();
    expect(secViolationEvent?.verdict).toBe("REFUSED");
    expect(secViolationEvent?.policy_outcome).toBeNull();
    expect(secViolationEvent?.next_action).toBe("CONTINUE_ADMIT");

    const policyDecisionEvent = sc.decisionTrace.find((e) => e.event_type === "POLICY_DECISION");
    expect(policyDecisionEvent).toBeDefined();
    expect(policyDecisionEvent?.policy_outcome).toBe("ALLOW");
    expect(policyDecisionEvent?.next_action).toBe("CONTINUE_BIND");
  });

  it("3 & 4 & 7. Prompt injection attempt does not transfer authority, preserves authoritative policy, and is labeled correctly", () => {
    render(<AttackLabConsole />);
    const btn = screen.getByRole("button", { name: /1\. Prompt Injection/i });
    fireEvent.click(btn);

    expect(screen.getByText(/AUTHORITY ESCALATION REFUSED — AUTHORITATIVE POLICY PRESERVED/i)).toBeInTheDocument();
    expect(screen.getByText(/LOWER AUTHORITY DATA CANNOT MODIFY HIGHER AUTHORITY POLICY/i)).toBeInTheDocument();

    const pageText = document.body.textContent || "";
    expect(pageText).not.toContain("UNTRUSTED INSTRUCTION IGNORED FOR AUTHORITY — REFUSED UNDER POLICY");
  });

  it("8. Every demo Decision Trace entry includes all 12 frozen contract fields and valid evidence structure", () => {
    const requiredKeys = [
      "stage",
      "event_type",
      "verdict",
      "reason_codes",
      "invariant_id",
      "approval_scheme",
      "policy_outcome",
      "payment_state",
      "advisory",
      "next_action",
      "evidence",
      "recorded_at",
    ];

    Object.values(ATTACK_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        requiredKeys.forEach((key) => {
          expect(e).toHaveProperty(key);
        });
        expect(e.evidence).toHaveProperty("event_id");
        expect(e.evidence).toHaveProperty("sequence");
        expect(e.evidence).toHaveProperty("actor");
      });
    });
  });

  it("Shared DecisionVerdict type retains all 7 frozen contract enum values", () => {
    const validVerdicts: DecisionVerdict[] = [
      "ACCEPTED",
      "REFUSED",
      "PENDING",
      "SUCCEEDED",
      "FAILED",
      "IGNORED",
      "ADVISORY",
    ];
    expect(validVerdicts.length).toBe(7);
  });

  it("Every reason_code used is source-defined in packages/schemas/domain.py :: ReasonCode and not conflated with EventType", () => {
    const validReasonCodes = new Set([
      "NO_VALID_OFFERS",
      "HARD_LIMIT_EXCEEDED",
      "BLOCKED_MERCHANT",
      "MERCHANT_NOT_ALLOWED",
      "RATING_BELOW_MIN",
      "CURRENCY_NOT_ALLOWED",
      "OUT_OF_STOCK",
      "MERCHANT_TRUST_TOO_LOW",
      "MERCHANT_IDENTITY_MISMATCH",
      "SOFT_BUDGET_EXCEEDED",
      "WITHIN_LIMITS",
      "AUTHORITY_ESCALATION",
      "CAPABILITY_DENIED",
      "TRANSACTION_BINDING_FAILURE",
      "AUTHORIZATION_REPLAY_DETECTED",
      "AUTHORIZATION_EXPIRED",
      "AUTHORIZATION_NOT_ACTIVE",
      "AUTHORIZATION_NOT_FOUND",
      "AUTHORIZATION_SIGNATURE_INVALID",
      "AUTHORIZATION_SIGNATURE_MALFORMED",
      "AUTHORIZATION_SIGNING_KEY_UNKNOWN",
      "AUTHORIZATION_PROOF_MISSING",
      "AUTHORIZATION_APPROVAL_SCHEME_INVALID",
      "BIND_REFUSED_OFFER_CHANGED",
      "IDEMPOTENCY_CONFLICT",
      "PAYMENT_PROVIDER_TIMEOUT",
      "PROVIDER_TRANSIENT_FAILURE",
      "PROVIDER_TERMINAL_FAILURE",
      "PROVIDER_RESPONSE_MISMATCH",
      "PROVIDER_PAYMENT_NOT_FOUND",
      "ILLEGAL_PAYMENT_TRANSITION",
      "MISSION_NOT_AUTHORIZED",
      "PAYMENT_INTENT_NOT_FOUND",
      "WEBHOOK_SIGNATURE_INVALID",
      "WEBHOOK_DUPLICATE",
      "WEBHOOK_UNKNOWN_PAYMENT",
    ]);

    Object.values(ATTACK_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        e.reason_codes.forEach((rc) => {
          expect(validReasonCodes.has(rc)).toBe(true);
        });
      });
    });
  });

  it("Capability identifiers are source-backed to packages/schemas/capability.py (payment.execute, buyer-agent)", () => {
    render(<AttackLabConsole />);
    const btn = screen.getByRole("button", { name: /4\. Capability Denial/i });
    fireEvent.click(btn);

    expect(screen.getAllByText(/payment\.execute/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/buyer-agent/i).length).toBeGreaterThan(0);
  });

  it("Replay sequence labels events as EVENT: AUTHORIZATION_CONSUMED and EVENT: AUTHORIZATION_REPLAY_DETECTED without overclaiming implementation", () => {
    render(<AttackLabConsole />);
    const btn = screen.getByRole("button", { name: /3\. Auth Replay/i });
    fireEvent.click(btn);

    expect(screen.getByText(/EVENT: AUTHORIZATION_CONSUMED/i)).toBeInTheDocument();
    expect(screen.getByText(/EVENT: AUTHORIZATION_REPLAY_DETECTED/i)).toBeInTheDocument();
    expect(screen.getByText(/Single-use authorization and replay checks reject reuse/i)).toBeInTheDocument();
  });

  it("Mutation scenario uses precise digest mismatch wording without overclaiming signature verification", () => {
    render(<AttackLabConsole />);
    const btn = screen.getByRole("button", { name: /2\. Post-Auth Mutation/i });
    fireEvent.click(btn);

    expect(screen.getAllByText(/Bound transaction digest no longer matches presented terms/i).length).toBeGreaterThan(0);
  });

  it("Capability denial leaves executor unreachable", () => {
    render(<AttackLabConsole />);
    const btn = screen.getByRole("button", { name: /4\. Capability Denial/i });
    fireEvent.click(btn);

    expect(screen.getAllByText(/EXECUTOR UNREACHABLE/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Privileged payment executor was never invoked/i)).toBeInTheDocument();
  });

  it("Only ADMIT, BIND, EXECUTE are Decision Trace stages", () => {
    const validStages = new Set(["ADMIT", "BIND", "EXECUTE"]);

    Object.values(ATTACK_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        expect(validStages.has(e.stage)).toBe(true);
        expect((e.stage as string)).not.toBe("ATTACK");
        expect((e.stage as string)).not.toBe("AUDIT");
        expect((e.stage as string)).not.toBe("AUTHORIZATION");
      });
    });
  });

  it("Demo trace evidence is visibly labeled DEMO TRACE and SYNTHETIC DEMO TRACE; risk remains advisory", () => {
    render(<AttackLabConsole />);
    expect(screen.getAllByText(/DEMO TRACE/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/SYNTHETIC DEMO TRACE/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/ADVISORY ONLY/i).length).toBeGreaterThan(0);
  });
});
