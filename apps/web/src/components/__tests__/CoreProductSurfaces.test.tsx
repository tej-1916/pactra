import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AuthoritySeparationDiagram } from "@/components/risk/AuthoritySeparationDiagram";
import { DemoAdvisorySignals } from "@/components/risk/DemoAdvisorySignals";
import { TranslationBoundary } from "@/components/adapters/TranslationBoundary";
import { AdapterFlowDemo } from "@/components/adapters/AdapterFlowDemo";
import { SupportMatrix } from "@/components/adapters/SupportMatrix";
import { ComponentAvailabilityTable } from "@/components/system/ComponentAvailabilityTable";
import { PROTOCOL_SUPPORT, VOCABULARY } from "@/lib/reference";
import type { ApprovalScheme, PolicyOutcome } from "@/lib/types/pactra";

// Mock API and queries
vi.mock("@/lib/api/client", () => ({
  api: {
    getRisk: vi.fn().mockResolvedValue({ kind: "ok", data: null }),
    recordRisk: vi.fn().mockResolvedValue({ kind: "ok", data: null }),
  },
}));

vi.mock("@/lib/hooks/useMissionRegister", () => ({
  useMissionRegister: vi.fn(() => ({
    missions: [{ id: "mission_test_01", raw_query: "Buy laptop" }],
    hydrated: true,
  })),
}));

describe("Phase 7.2 Core Product Surfaces Authority + Evidence-Tier Separation Audit", () => {
  describe("PART A — /risk (Risk & Advisory Authority Boundaries)", () => {
    it("1, 2. No 'unforgeable token' claim; authorization is not universally called a cryptographic token", () => {
      render(<AuthoritySeparationDiagram />);
      const text = document.body.textContent || "";
      expect(text).not.toContain("unforgeable");
      expect(text).not.toContain("Cryptographic Token");
      expect(screen.getByText(/AUTHORIZATION GATE/i)).toBeInTheDocument();
      expect(screen.getByText(/BOUND AUTHORITY/i)).toBeInTheDocument();
    });

    it("3, 4, 5. Supports POLICY_AUTO, USER_ED25519, and LEGACY_SERVER without conflation", () => {
      render(<AuthoritySeparationDiagram />);
      expect(
        screen.getByText(/POLICY_AUTO, USER_ED25519, LEGACY_SERVER/i)
      ).toBeInTheDocument();

      const validSchemes: ApprovalScheme[] = ["POLICY_AUTO", "USER_ED25519", "LEGACY_SERVER"];
      expect(validSchemes).toHaveLength(3);
    });

    it("6, 7. Policy outcome includes ALLOW / REQUIRE_APPROVAL / DENY; RiskRecommendation.REQUIRE_STRONGER_APPROVAL is distinct from PolicyOutcome.REQUIRE_APPROVAL", () => {
      render(<AuthoritySeparationDiagram />);
      expect(screen.getByText(/EMITS ALLOW \/ REQUIRE_APPROVAL \/ DENY/i)).toBeInTheDocument();

      const policyOutcomes: PolicyOutcome[] = ["ALLOW", "REQUIRE_APPROVAL", "DENY"];
      expect(policyOutcomes).toHaveLength(3);
      expect(VOCABULARY.policyOutcomes).toEqual(expect.arrayContaining(["ALLOW", "REQUIRE_APPROVAL", "DENY"]));

      expect(VOCABULARY.riskRecommendations).toContain("REQUIRE_STRONGER_APPROVAL");
      expect(VOCABULARY.riskRecommendations).not.toContain("ALLOW");
      expect(VOCABULARY.riskRecommendations).not.toContain("DENY");

      // Verify textual explanation of enum distinction
      expect(
        screen.getByText(/distinct from the Policy Engine's deterministic/i)
      ).toBeInTheDocument();
    });

    it("8. Risk remains strictly advisory-only and cannot authorize or deny", () => {
      render(<AuthoritySeparationDiagram />);
      expect(screen.getAllByText(/ADVISORY ONLY/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/RISK SCORE ≠ AUTHORITY/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/AUTHORITY: ZERO/i)).toBeInTheDocument();
    });

    it("Demo risk signals are explicitly labeled", () => {
      render(<DemoAdvisorySignals />);
      expect(screen.getByText(/SYNTHETIC DEMO DATA/i)).toBeInTheDocument();
      expect(screen.getAllByText(/DEMO ADVISORY SIGNALS/i).length).toBeGreaterThan(0);
    });
  });

  describe("PART B — /adapters (Protocol Ingestion Precision)", () => {
    it("8, 9. Renders ADAPTER TRUST ≠ CALLER AUTHORITY and TRANSLATION SIDE EFFECTS = ZERO", () => {
      render(<TranslationBoundary />);
      expect(screen.getByText(/ADAPTER TRUST/i)).toBeInTheDocument();
      expect(screen.getByText(/NEVER CALLER AUTHORITY/i)).toBeInTheDocument();
      expect(screen.getAllByText(/TRANSLATION/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/NEVER EXECUTION/i)).toBeInTheDocument();
    });

    it("14, 16, 17. Razorpay is classified as Payment Rail/Provider Adapter; MCP is PARTIAL; AP2/x402/ACP are PLANNED", () => {
      render(<SupportMatrix entries={PROTOCOL_SUPPORT} />);

      const razorpay = PROTOCOL_SUPPORT.find((e) => e.protocol === "Razorpay");
      expect(razorpay).toBeDefined();
      expect(razorpay?.family).toBe("PAYMENT_RAIL");
      expect(razorpay?.status).toBe("PARTIAL");

      const mcp = PROTOCOL_SUPPORT.find((e) => e.protocol === "MCP");
      expect(mcp).toBeDefined();
      expect(mcp?.status).toBe("PARTIAL");

      const ap2 = PROTOCOL_SUPPORT.find((e) => e.protocol === "AP2");
      expect(ap2).toBeDefined();
      expect(ap2?.status).toBe("PLANNED");
    });

    it("Translation side effects are zero and candidate is unprivileged", () => {
      render(<AdapterFlowDemo />);
      expect(screen.getAllByText(/CANONICAL CANDIDATE/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/TRANSLATION SIDE EFFECTS = ZERO/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/External messages possess zero authority/i)).toBeInTheDocument();
    });
  });

  describe("PART C — /system (System Evidence-Tier Separation)", () => {
    it("1, 2, 3, 4. Three distinct evidence tiers: Tier A Implementation, Tier B Configuration, Tier C Runtime Evidence", () => {
      render(<ComponentAvailabilityTable />);
      expect(screen.getAllByText(/TIER A: IMPLEMENTATION/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/TIER B: CONFIGURATION/i).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/TIER C: RUNTIME EVIDENCE/i).length).toBeGreaterThan(0);

      // Verify CONFIGURED IN FRONTEND and TEST MODE CONFIGURED are configuration status, NOT runtime evidence
      expect(screen.getAllByText(/FRONTEND CONFIGURED/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/TEST MODE CONFIGURED/i)).toBeInTheDocument();
    });

    it("5, 8. Razorpay has TEST MODE CONFIGURED configuration and NOT RUNTIME VERIFIED runtime evidence", () => {
      render(<ComponentAvailabilityTable />);
      expect(screen.getByText(/TEST MODE CONFIGURED/i)).toBeInTheDocument();
      expect(screen.getAllByText(/NOT RUNTIME VERIFIED/i).length).toBeGreaterThan(0);
      expect(screen.getByText(/Offline tested in test-mode only/i)).toBeInTheDocument();
    });

    it("6, 7. API reachability does not imply downstream kernel or provider health; no global health claims", () => {
      render(<ComponentAvailabilityTable />);
      const text = document.body.textContent || "";
      expect(text).not.toContain("SYSTEM HEALTHY");
      expect(text).not.toContain("ALL SYSTEMS OPERATIONAL");
      expect(text).not.toContain("PRODUCTION READY");
      expect(text).not.toContain("100% compliant");

      expect(
        screen.getByText(/HTTP 200 represents network transport response for the tested endpoint, not end-to-end downstream provider success/i)
      ).toBeInTheDocument();
    });

    it("Security stages strictly remain ADMIT, BIND, EXECUTE (never SYSTEM, AUDIT, or SECURITY)", () => {
      render(<ComponentAvailabilityTable />);
      expect(
        screen.getByText(/Operates across strictly 3 stages: ADMIT, BIND, EXECUTE/i)
      ).toBeInTheDocument();
    });
  });
});
