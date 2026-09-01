import type {
  ApprovalScheme,
  DecisionNextAction,
  PaymentIntentState,
  PolicyOutcome,
  DecisionVerdict,
  DecisionTraceEntry,
} from "@/lib/types/pactra";

export type ScenarioId = "BENIGN_PURCHASE" | "USER_APPROVAL" | "PROVIDER_LOST" | "LIVE_RUNTIME";

export interface DemoScenario {
  id: ScenarioId;
  label: string;
  badge: string;
  description: string;
  sourceMode: "DEMO SCENARIO";
  aiBuyer: {
    missionQuery: string;
    constraints: { label: string; val: string }[];
    candidateId: string;
    rationale: string;
  };
  merchantOffer: {
    merchantName: string;
    productId: string;
    productTitle: string;
    quotedAmountInr: number;
    currency: string;
    offerVersion: string;
  };
  authoritativePayee: {
    registeredPayeeId: string;
    registeredPayeeName: string;
    lookupStatus: string;
  };
  admit: {
    verdict: DecisionVerdict;
    policyOutcome: PolicyOutcome;
    nextAction: DecisionNextAction;
    checks: { name: string; status: "PASSED" | "FAILED" }[];
  };
  bind: {
    bindingVersion: string;
    canonicalDigest: string;
    expiryAt: string;
    boundAmountInr: number;
    boundCurrency: string;
    boundQuantity: number;
  };
  authorization: {
    scheme: ApprovalScheme;
    verdict: DecisionVerdict;
    policyOutcome: PolicyOutcome;
    nextAction: DecisionNextAction;
    signingKeyId?: string;
  };
  execute: {
    paymentState: PaymentIntentState;
    idempotencyKey: string;
    nextAction: DecisionNextAction;
    providerEvidence?: string;
  };
  decisionTrace: DecisionTraceEntry[];
}

export const DEMO_SCENARIOS: Record<Exclude<ScenarioId, "LIVE_RUNTIME">, DemoScenario> = {
  BENIGN_PURCHASE: {
    id: "BENIGN_PURCHASE",
    label: "Benign Purchase",
    badge: "POLICY_AUTO",
    description: "Auto-approved transaction under soft budget limits. No user signature required.",
    sourceMode: "DEMO SCENARIO",
    aiBuyer: {
      missionQuery: "Buy a USB-C dock under ₹4,000",
      constraints: [
        { label: "Max Budget", val: "₹4,000 INR" },
        { label: "Category", val: "Electronics" },
        { label: "Quantity", val: "1" },
      ],
      candidateId: "off_dock_882",
      rationale: "Selected 8-in-1 Dual Display Dock meeting budget and connector specifications.",
    },
    merchantOffer: {
      merchantName: "TechCorp Electronics",
      productId: "prod_dock_8in1",
      productTitle: "USB-C 8-in-1 Dual Display Hub & Dock",
      quotedAmountInr: 3499,
      currency: "INR",
      offerVersion: "v1.0.4",
    },
    authoritativePayee: {
      registeredPayeeId: "merch_techcorp_01",
      registeredPayeeName: "TechCorp Private Limited",
      lookupStatus: "SYNTHETIC DEMO DATA",
    },
    admit: {
      verdict: "ACCEPTED",
      policyOutcome: "ALLOW",
      nextAction: "CONTINUE_BIND",
      checks: [
        { name: "Typed Intent & Schema", status: "PASSED" },
        { name: "Provenance & Taint Isolation", status: "PASSED" },
        { name: "Merchant Capability Scope", status: "PASSED" },
        { name: "Budget Policy Bounds", status: "PASSED" },
      ],
    },
    bind: {
      bindingVersion: "v2.1",
      canonicalDigest: "0x8f3c4a2b910e47f9a1c8b32e6d5a109f2d8e7c1a5b4c3d2e1f0a9b8c7d6e5f4a",
      expiryAt: "2026-09-01T16:30:00.000Z",
      boundAmountInr: 3499,
      boundCurrency: "INR",
      boundQuantity: 1,
    },
    authorization: {
      scheme: "POLICY_AUTO",
      verdict: "SUCCEEDED",
      policyOutcome: "ALLOW",
      nextAction: "DISPATCH_PAYMENT",
    },
    execute: {
      paymentState: "SUCCEEDED",
      idempotencyKey: "idempotency_benign_01_a9f8",
      nextAction: "NONE",
      providerEvidence: undefined,
    },
    decisionTrace: [
      {
        stage: "ADMIT",
        event_type: "POLICY_DECISION",
        verdict: "ACCEPTED",
        reason_codes: ["WITHIN_LIMITS"],
        invariant_id: null,
        approval_scheme: null,
        policy_outcome: "ALLOW",
        payment_state: null,
        advisory: false,
        next_action: "CONTINUE_BIND",
        evidence: { event_id: "evt_demo_admit_01", sequence: 1, actor: "kernel" },
        recorded_at: "2026-09-01T15:00:00.000Z",
      },
      {
        stage: "BIND",
        event_type: "AUTHORIZATION_CREATED",
        verdict: "PENDING",
        reason_codes: [],
        invariant_id: null,
        approval_scheme: "POLICY_AUTO",
        policy_outcome: null,
        payment_state: null,
        advisory: false,
        next_action: "CONTINUE_BIND",
        evidence: { event_id: "evt_demo_bind_01", sequence: 2, actor: "kernel" },
        recorded_at: "2026-09-01T15:00:01.000Z",
      },
      {
        stage: "EXECUTE",
        event_type: "PAYMENT_SUCCEEDED",
        verdict: "SUCCEEDED",
        reason_codes: [],
        invariant_id: null,
        approval_scheme: null,
        policy_outcome: null,
        payment_state: "SUCCEEDED",
        advisory: false,
        next_action: "NONE",
        evidence: { event_id: "evt_demo_exec_01", sequence: 3, actor: "provider" },
        recorded_at: "2026-09-01T15:00:02.000Z",
      },
    ],
  },
  USER_APPROVAL: {
    id: "USER_APPROVAL",
    label: "User Approval Required",
    badge: "USER_ED25519",
    description: "Transaction exceeds soft budget limit. Policy outcome is REQUIRE_APPROVAL, next_action is CONTINUE_BIND at ADMIT, progressing to BIND then AWAIT_USER_SIGNATURE at Authorization.",
    sourceMode: "DEMO SCENARIO",
    aiBuyer: {
      missionQuery: "Buy high-performance developer workstation monitor",
      constraints: [
        { label: "Soft Budget", val: "₹15,000 INR" },
        { label: "Category", val: "Monitors" },
        { label: "Quantity", val: "1" },
      ],
      candidateId: "off_mon_991",
      rationale: "Selected 32-inch 4K Color-Accurate Monitor at ₹24,999 INR.",
    },
    merchantOffer: {
      merchantName: "DisplayPro Systems",
      productId: "prod_mon_32_4k",
      productTitle: "UltraSharp 32-inch 4K USB-C Monitor",
      quotedAmountInr: 24999,
      currency: "INR",
      offerVersion: "v2.1.0",
    },
    authoritativePayee: {
      registeredPayeeId: "merch_display_pro",
      registeredPayeeName: "DisplayPro Technologies Corp",
      lookupStatus: "SYNTHETIC DEMO DATA",
    },
    admit: {
      verdict: "PENDING",
      policyOutcome: "REQUIRE_APPROVAL",
      nextAction: "CONTINUE_BIND",
      checks: [
        { name: "Typed Intent & Schema", status: "PASSED" },
        { name: "Provenance & Taint Isolation", status: "PASSED" },
        { name: "Soft Budget Threshold", status: "FAILED" },
        { name: "Hard Limit Bounds (₹50,000)", status: "PASSED" },
      ],
    },
    bind: {
      bindingVersion: "v2.1",
      canonicalDigest: "0x3a91b2c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2",
      expiryAt: "2026-09-01T16:45:00.000Z",
      boundAmountInr: 24999,
      boundCurrency: "INR",
      boundQuantity: 1,
    },
    authorization: {
      scheme: "USER_ED25519",
      verdict: "PENDING",
      policyOutcome: "REQUIRE_APPROVAL",
      nextAction: "AWAIT_USER_SIGNATURE",
      signingKeyId: "key_ed25519_user_demo_01",
    },
    execute: {
      paymentState: "CREATED",
      idempotencyKey: "idempotency_user_approval_02_b71c",
      nextAction: "AWAIT_USER_SIGNATURE",
    },
    decisionTrace: [
      {
        stage: "ADMIT",
        event_type: "POLICY_DECISION",
        verdict: "PENDING",
        reason_codes: ["SOFT_BUDGET_EXCEEDED"],
        invariant_id: null,
        approval_scheme: null,
        policy_outcome: "REQUIRE_APPROVAL",
        payment_state: null,
        advisory: false,
        next_action: "CONTINUE_BIND",
        evidence: { event_id: "evt_demo_admit_02", sequence: 1, actor: "kernel" },
        recorded_at: "2026-09-01T15:05:00.000Z",
      },
      {
        stage: "BIND",
        event_type: "APPROVAL_REQUESTED",
        verdict: "PENDING",
        reason_codes: [],
        invariant_id: null,
        approval_scheme: "USER_ED25519",
        policy_outcome: null,
        payment_state: null,
        advisory: false,
        next_action: "AWAIT_USER_SIGNATURE",
        evidence: { event_id: "evt_demo_bind_02", sequence: 2, actor: "user_approval_gate" },
        recorded_at: "2026-09-01T15:05:01.000Z",
      },
    ],
  },
  PROVIDER_LOST: {
    id: "PROVIDER_LOST",
    label: "Provider Response Lost",
    badge: "PROVIDER_PENDING",
    description: "Network timeout or lost provider HTTP response. State enters PROVIDER_PENDING, next_action is RECONCILE_PAYMENT.",
    sourceMode: "DEMO SCENARIO",
    aiBuyer: {
      missionQuery: "Order replacement server backup drive",
      constraints: [
        { label: "Budget Limit", val: "₹8,000 INR" },
        { label: "Category", val: "Storage" },
        { label: "Quantity", val: "1" },
      ],
      candidateId: "off_drive_404",
      rationale: "Selected 4TB Enterprise NVMe Drive at ₹6,200 INR.",
    },
    merchantOffer: {
      merchantName: "ServerParts Direct",
      productId: "prod_nvme_4tb",
      productTitle: "Enterprise 4TB PCIe Gen4 NVMe SSD",
      quotedAmountInr: 6200,
      currency: "INR",
      offerVersion: "v1.1.2",
    },
    authoritativePayee: {
      registeredPayeeId: "merch_server_parts",
      registeredPayeeName: "ServerParts Systems Inc",
      lookupStatus: "SYNTHETIC DEMO DATA",
    },
    admit: {
      verdict: "ACCEPTED",
      policyOutcome: "ALLOW",
      nextAction: "CONTINUE_BIND",
      checks: [
        { name: "Typed Intent & Schema", status: "PASSED" },
        { name: "Provenance & Taint Isolation", status: "PASSED" },
        { name: "Merchant Capability Scope", status: "PASSED" },
        { name: "Budget Policy Bounds", status: "PASSED" },
      ],
    },
    bind: {
      bindingVersion: "v2.1",
      canonicalDigest: "0x7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d",
      expiryAt: "2026-09-01T16:50:00.000Z",
      boundAmountInr: 6200,
      boundCurrency: "INR",
      boundQuantity: 1,
    },
    authorization: {
      scheme: "POLICY_AUTO",
      verdict: "ACCEPTED",
      policyOutcome: "ALLOW",
      nextAction: "DISPATCH_PAYMENT",
    },
    execute: {
      paymentState: "PROVIDER_PENDING",
      idempotencyKey: "idempotency_lost_resp_03_c82e",
      nextAction: "RECONCILE_PAYMENT",
      providerEvidence: undefined,
    },
    decisionTrace: [
      {
        stage: "ADMIT",
        event_type: "POLICY_DECISION",
        verdict: "ACCEPTED",
        reason_codes: ["WITHIN_LIMITS"],
        invariant_id: null,
        approval_scheme: null,
        policy_outcome: "ALLOW",
        payment_state: null,
        advisory: false,
        next_action: "CONTINUE_BIND",
        evidence: { event_id: "evt_demo_admit_03", sequence: 1, actor: "kernel" },
        recorded_at: "2026-09-01T15:10:00.000Z",
      },
      {
        stage: "BIND",
        event_type: "AUTHORIZATION_CREATED",
        verdict: "PENDING",
        reason_codes: [],
        invariant_id: null,
        approval_scheme: "POLICY_AUTO",
        policy_outcome: null,
        payment_state: null,
        advisory: false,
        next_action: "CONTINUE_BIND",
        evidence: { event_id: "evt_demo_bind_03", sequence: 2, actor: "kernel" },
        recorded_at: "2026-09-01T15:10:01.000Z",
      },
      {
        stage: "EXECUTE",
        event_type: "PAYMENT_PROVIDER_TIMEOUT",
        verdict: "PENDING",
        reason_codes: ["PAYMENT_PROVIDER_TIMEOUT"],
        invariant_id: null,
        approval_scheme: null,
        policy_outcome: null,
        payment_state: "PROVIDER_PENDING",
        advisory: false,
        next_action: "RECONCILE_PAYMENT",
        evidence: { event_id: "evt_demo_exec_03", sequence: 3, actor: "payment_reconciler" },
        recorded_at: "2026-09-01T15:10:05.000Z",
      },
    ],
  },
};
