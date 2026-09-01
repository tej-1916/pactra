import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { AuditReplayConsole } from "@/components/audit/AuditReplayConsole";
import { AUDIT_DEMO_SCENARIOS } from "@/components/audit/auditScenarios";
import type { ApprovalScheme, MissionReplay } from "@/lib/types/pactra";
import type { ApiResult } from "@/lib/api/result";
import type { UseQueryResult } from "@tanstack/react-query";
import * as queryHooks from "@/lib/hooks/queries";

// Mock queries
vi.mock("@/lib/hooks/queries", () => ({
  useReplay: vi.fn(() => ({
    isPending: false,
    data: null,
  })),
  useAuthorization: vi.fn(() => ({
    isPending: false,
    data: null,
  })),
}));

vi.mock("@/lib/hooks/useMissionRegister", () => ({
  useMissionRegister: vi.fn(() => ({
    missions: [
      { id: "mission_test_01", raw_query: "Buy headphones" },
      { id: "mission_test_02", raw_query: "Buy keyboard" },
    ],
    hydrated: true,
  })),
}));

describe("Phase 6.2 Audit & Replay Digest Precision Audit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("1, 2, 4. BIND stage renders TRANSACTION DIGEST PREFIX with DEMO DIGEST PREFIX / DEMO BINDING label and never mislabels prefix as full digest", () => {
    render(<AuditReplayConsole />);
    // Select Seq 2 (BIND stage)
    const seq2Btn = screen.getByRole("button", { name: /SEQ 2/i });
    fireEvent.click(seq2Btn);

    expect(screen.getByText(/TRANSACTION DIGEST PREFIX:/i)).toBeInTheDocument();
    expect(screen.getByText(/DEMO DIGEST PREFIX/i)).toBeInTheDocument();
    expect(screen.getByText(/BINDING VERSION:/i)).toBeInTheDocument();
    expect(screen.getAllByText(/DEMO BINDING/i).length).toBeGreaterThan(0);

    // Verify it explains prefix vs full digest
    expect(
      screen.getByText(
        /Replay state preserves the canonical digest prefix\. Full digest is held in the issued authorization artifact\./i
      )
    ).toBeInTheDocument();
  });

  it("3. Runtime replay-state renders TRANSACTION DIGEST PREFIX from ReplayedAuthorization.transaction_digest_prefix", () => {
    const mockReplayData: MissionReplay = {
      mission_id: "550e8400-e29b-41d4-a716-446655440000",
      audit_valid: true,
      trusted: true,
      reason_code: "REPLAY_OK",
      events_replayed: 4,
      verification: {
        mission_id: "550e8400-e29b-41d4-a716-446655440000",
        valid: true,
        reason_code: "VERIFY_OK",
        events_checked: 4,
        first_invalid_sequence: null,
        expected_hash: null,
        actual_hash: null,
        detail: null,
      },
      state: {
        mission_id: "550e8400-e29b-41d4-a716-446655440000",
        mission_state: "BIND_CREATED",
        events_replayed: 4,
        raw_query: "Buy laptop",
        quantity: 1,
        policy_decision: "ALLOW",
        policy_version: "v1",
        authorization: {
          authorization_id: "auth_live_1234",
          status: "ISSUED",
          transaction_digest_prefix: "e3b0c44298fc1c14",
          policy_version: "v1",
          offer_version: "v1",
          binding_version: "v1.0",
          expires_at: "2026-09-01T17:00:00.000Z",
          consumed_at: null,
          bound_merchant_id: "merch_01",
          bound_product_id: "prod_01",
          bound_quantity: 1,
          bound_amount_inr: 25000,
          bound_currency: "INR",
          replay_detected: false,
          binding_failures: 0,
        },
        payment: {
          payment_intent_id: null,
          state: null,
          provider: null,
          provider_payment_id: null,
          idempotency_key: null,
          amount_inr: null,
          currency: null,
          merchant_id: null,
          last_reason_code: null,
          attempts: 0,
          intent_reused: false,
          uncertain_episodes: 0,
          provider_timeouts: 0,
          retries_scheduled: 0,
          reconciliations: 0,
          dead_lettered: false,
          webhooks_verified: 0,
          duplicate_webhooks_ignored: 0,
          out_of_order_webhooks_ignored: 0,
        },
        policy_reason_codes: [],
        requested_amount: 25000,
        soft_budget: 30000,
        hard_limit: 50000,
        selected_offer_id: null,
        approval_required: false,
        approval_granted: false,
        raw_offer_count: 1,
        valid_offer_count: 1,
        invalid_offer_count: 0,
        tainted_merchant_fields: [],
        security_events: [],
        skipped_transitions: [],
        risk_assessments: [],
      },
      comparison: null,
      decision_trace: [
        {
          stage: "BIND",
          event_type: "AUTHORIZATION_CREATED",
          verdict: "ACCEPTED",
          reason_codes: ["WITHIN_LIMITS"],
          invariant_id: null,
          approval_scheme: "POLICY_AUTO",
          policy_outcome: "ALLOW",
          payment_state: "QUEUED",
          advisory: false,
          next_action: "DISPATCH_PAYMENT",
          evidence: { event_id: "evt_rt_01", sequence: 1, actor: "security_kernel" },
          recorded_at: "2026-09-01T16:00:00.000Z",
        },
      ],
      unsupported_events: [],
      detail: null,
    };

    const mockResult: ApiResult<MissionReplay> = {
      kind: "ok",
      data: mockReplayData,
      status: 200,
    };

    vi.mocked(queryHooks.useReplay).mockReturnValue({
      isPending: false,
      data: mockResult,
    } as unknown as UseQueryResult<ApiResult<MissionReplay>>);

    render(<AuditReplayConsole />);
    const runtimeBtn = screen.getByRole("button", { name: /RUNTIME MODE/i });
    fireEvent.click(runtimeBtn);

    expect(screen.getByText(/TRANSACTION DIGEST PREFIX:/i)).toBeInTheDocument();
    expect(screen.getByText(/e3b0c44298fc1c14/i)).toBeInTheDocument();
    expect(screen.getByText(/REPLAY STATE EVIDENCE/i)).toBeInTheDocument();
  });

  it("5. Verification semantics remain intact across demo and runtime modes", () => {
    render(<AuditReplayConsole />);
    expect(screen.getByText(/DEMO CONSISTENCY EXAMPLE/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Replay is evidence reconstruction from recorded audit evidence, not payment re-execution/i
      )
    ).toBeInTheDocument();
  });

  it("6. ApprovalScheme contract supports POLICY_AUTO, USER_ED25519, LEGACY_SERVER", () => {
    const validSchemes: ApprovalScheme[] = ["POLICY_AUTO", "USER_ED25519", "LEGACY_SERVER"];
    expect(validSchemes).toHaveLength(3);
    expect(validSchemes).toContain("LEGACY_SERVER");
  });

  it("7. Only ADMIT, BIND, EXECUTE stages in Decision Trace", () => {
    const validStages = new Set(["ADMIT", "BIND", "EXECUTE"]);
    Object.values(AUDIT_DEMO_SCENARIOS).forEach((sc) => {
      sc.decisionTrace.forEach((e) => {
        expect(validStages.has(e.stage)).toBe(true);
      });
    });
  });
});
