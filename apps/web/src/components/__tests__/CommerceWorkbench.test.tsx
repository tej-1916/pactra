import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { CommerceConsole } from "@/components/commerce/CommerceConsole";
import { AiBuyerPanel } from "@/components/commerce/AiBuyerPanel";
import { MerchantOfferPanel } from "@/components/commerce/MerchantOfferPanel";
import { TransactionJourney } from "@/components/commerce/TransactionJourney";
import { AuthoritativeEvidencePanel } from "@/components/commerce/AuthoritativeEvidencePanel";
import { CommerceTraceTimeline } from "@/components/commerce/CommerceTraceTimeline";
import { DEMO_SCENARIOS } from "@/components/commerce/demoScenarios";
import { useMission } from "@/lib/hooks/queries";

// Mock Query hooks for live runtime mode
vi.mock("@/lib/hooks/queries", () => ({
  useMission: vi.fn().mockReturnValue({ isPending: false, data: null }),
  useAuthorization: vi.fn().mockReturnValue({ isPending: false, data: null }),
  usePayment: vi.fn().mockReturnValue({ isPending: false, data: null }),
  useReplay: vi.fn().mockReturnValue({ isPending: false, data: null }),
}));

describe("Live Commerce Workbench Stage-Enum Audit (Phase 4.2)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    Object.defineProperty(window, "IntersectionObserver", {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        observe: vi.fn(),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
      })),
    });
  });

  it("1 & 2 & 8. Only ADMIT, BIND, EXECUTE are Decision Trace stages; no stage: AUTHORIZATION or AUDIT stage exists", () => {
    render(<CommerceTraceTimeline entries={DEMO_SCENARIOS.BENIGN_PURCHASE.decisionTrace} isDemo={true} />);
    expect(screen.getByText(/DEMO TRACE/i)).toBeInTheDocument();

    const validStages = new Set(["ADMIT", "BIND", "EXECUTE"]);

    Object.values(DEMO_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        expect(validStages.has(e.stage)).toBe(true);
        expect((e.stage as string)).not.toBe("AUTHORIZATION");
        expect((e.stage as string)).not.toBe("AUDIT");
      });
    });
  });

  it("3. AUTHORIZATION exists only as a visual sub-gate / section within BIND", () => {
    render(<TransactionJourney scenario={DEMO_SCENARIOS.BENIGN_PURCHASE} />);
    expect(screen.getByText(/AUTHORIZATION GATE \(BIND SUB-GATE\)/i)).toBeInTheDocument();
  });

  it("4 & 5. APPROVAL_REQUESTED and AUTHORIZATION_CREATED events use stage BIND", () => {
    const userSc = DEMO_SCENARIOS.USER_APPROVAL;
    const approvalReqEvent = userSc.decisionTrace.find((e) => e.event_type === "APPROVAL_REQUESTED");
    expect(approvalReqEvent).toBeDefined();
    expect(approvalReqEvent?.stage).toBe("BIND");

    const benignSc = DEMO_SCENARIOS.BENIGN_PURCHASE;
    const authCreatedEvent = benignSc.decisionTrace.find((e) => e.event_type === "AUTHORIZATION_CREATED");
    expect(authCreatedEvent).toBeDefined();
    expect(authCreatedEvent?.stage).toBe("BIND");
  });

  it("6 & 7. USER_ED25519 waiting uses verdict PENDING, policy_outcome REQUIRE_APPROVAL, next_action AWAIT_USER_SIGNATURE at stage BIND; EXECUTE stage trace is absent until approved", () => {
    const sc = DEMO_SCENARIOS.USER_APPROVAL;
    const pendingEvent = sc.decisionTrace.find((e) => e.event_type === "APPROVAL_REQUESTED");
    expect(pendingEvent).toBeDefined();
    expect(pendingEvent?.stage).toBe("BIND");
    expect(pendingEvent?.verdict).toBe("PENDING");
    expect(pendingEvent?.policy_outcome).toBe("REQUIRE_APPROVAL");
    expect(pendingEvent?.next_action).toBe("AWAIT_USER_SIGNATURE");

    const executeEvents = sc.decisionTrace.filter((e) => e.stage === "EXECUTE");
    expect(executeEvents.length).toBe(0);
  });

  it("Authoritative payee is NOT rendered inside untrusted merchant region; merchant strings remain TaintedText", () => {
    render(
      <AiBuyerPanel
        missionQuery="Buy USB-C dock"
        constraints={[{ label: "Budget", val: "₹4,000" }]}
        candidateId="off_dock_882"
        rationale="Selected dock"
      />
    );
    expect(screen.getByText(/AI output is proposal data, not transaction authority/i)).toBeInTheDocument();

    render(
      <MerchantOfferPanel
        merchantName="TechCorp"
        productId="prod_01"
        productTitle="USB-C Hub"
        quotedAmountInr={3499}
        currency="INR"
        offerVersion="v1.0"
        isDemo={true}
      />
    );
    expect(screen.getAllByText(/UNTRUSTED INPUT/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Merchant-controlled strings are untrusted input/i)).toBeInTheDocument();
    const panelText = document.body.textContent || "";
    expect(panelText).not.toContain("merch_techcorp_01");
  });

  it("Demo authority values are visibly labeled demo, binding version is labeled DEMO BINDING", () => {
    render(<AuthoritativeEvidencePanel scenario={DEMO_SCENARIOS.BENIGN_PURCHASE} />);
    expect(screen.getByText(/REGISTERED PAYEE \(AUTHORITATIVE LOOKUP\)/i)).toBeInTheDocument();
    expect(screen.getByText(/merch_techcorp_01/i)).toBeInTheDocument();
    expect(screen.getAllByText(/DEMO BINDING/i).length).toBeGreaterThan(0);
  });

  it("Source-state machine handles runtime evidence states correctly", () => {
    const { rerender } = render(<CommerceConsole />);
    expect(screen.getAllByText(/DEMO SCENARIO/i)[0]).toBeInTheDocument();

    (useMission as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      isPending: true,
      data: null,
    });
    rerender(<CommerceConsole />);
    const liveApiBtn = screen.getByRole("button", { name: /4\. Live Runtime/i });
    fireEvent.click(liveApiBtn);

    expect(screen.getAllByText(/AWAITING RUNTIME EVIDENCE/i).length).toBeGreaterThan(0);

    (useMission as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      isPending: false,
      data: { kind: "unavailable", detail: "Network error" },
    });
    rerender(<CommerceConsole />);
    expect(screen.getAllByText(/RUNTIME EVIDENCE UNAVAILABLE/i).length).toBeGreaterThan(0);

    (useMission as unknown as ReturnType<typeof vi.fn>).mockReturnValue({
      isPending: false,
      data: {
        kind: "ok",
        data: {
          id: "miss_123",
          state: "COMPLETED",
          raw_query: "Buy dock",
          quantity: 1,
          created_at: "2026-09-01T15:00:00Z",
          offers: [],
        },
      },
    });
    rerender(<CommerceConsole />);
    expect(screen.getAllByText(/RUNTIME EVIDENCE/i).length).toBeGreaterThan(0);
  });

  it("Synthetic SUCCEEDED is explicitly labeled DEMO payment_state", () => {
    render(<TransactionJourney scenario={DEMO_SCENARIOS.BENIGN_PURCHASE} />);
    expect(screen.getByText(/DEMO payment_state: SUCCEEDED/i)).toBeInTheDocument();
    render(<AuthoritativeEvidencePanel scenario={DEMO_SCENARIOS.BENIGN_PURCHASE} />);
    expect(screen.getByText(/Synthetic scenario state — not provider runtime evidence/i)).toBeInTheDocument();
  });

  it("Every event_type in demoScenarios is an exact frozen EventType", () => {
    const validEventTypes = new Set([
      "MISSION_CREATED", "INTENT_PARSED", "DISCOVERY_STARTED", "OFFERS_RECEIVED",
      "OFFERS_NORMALIZED", "OFFERS_RANKED", "POLICY_DECISION", "APPROVAL_REQUESTED",
      "MISSION_DENIED", "SECURITY_VIOLATION", "AUTHORIZATION_CREATED", "AUTHORIZATION_ACTIVATED",
      "AUTHORIZATION_CONSUMED", "AUTHORIZATION_EXPIRED", "AUTHORIZATION_REVOKED",
      "AUTHORIZATION_REPLAY_DETECTED", "TRANSACTION_BINDING_FAILURE", "PAYMENT_INTENT_CREATED",
      "PAYMENT_QUEUED", "PAYMENT_ATTEMPTED", "PAYMENT_PROVIDER_TIMEOUT", "PAYMENT_PROVIDER_UNCERTAIN",
      "PAYMENT_RETRY_SCHEDULED", "PAYMENT_RECONCILED", "PAYMENT_SUCCEEDED", "PAYMENT_FAILED",
      "PAYMENT_INTENT_REUSED", "IDEMPOTENCY_CONFLICT", "OUTBOX_EVENT_DEAD_LETTERED",
      "WEBHOOK_VERIFIED", "WEBHOOK_REJECTED", "DUPLICATE_WEBHOOK_IGNORED", "WEBHOOK_OUT_OF_ORDER_IGNORED",
      "RISK_ASSESSED"
    ]);

    Object.values(DEMO_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        expect(validEventTypes.has(e.event_type)).toBe(true);
      });
    });
  });

  it("No invented invariant_id remains in demo trace entries", () => {
    Object.values(DEMO_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        expect(e.invariant_id).toBeNull();
      });
    });
  });
});
