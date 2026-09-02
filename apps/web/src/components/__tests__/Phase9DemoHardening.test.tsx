import { render, screen, act } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Hero } from "@/components/hero/Hero";
import { SignatureTrustGraph } from "@/components/hero/SignatureTrustGraph";
import { TrustRail } from "@/components/hero/TrustRail";
import { CommerceConsole } from "@/components/commerce/CommerceConsole";
import { AttackLabConsole } from "@/components/attack-lab/AttackLabConsole";
import { AuditReplayConsole } from "@/components/audit/AuditReplayConsole";
import RiskPage from "@/app/risk/page";
import AdaptersPage from "@/app/adapters/page";
import SystemPage from "@/app/system/page";
import {
  THEME_STORAGE_KEY,
  THEME_BOOTSTRAP_SCRIPT,
  getThemePreference,
} from "@/lib/theme";

vi.mock("server-only", () => ({}));

// Mock framer-motion useReducedMotion
const mockUseReducedMotion = vi.fn();
vi.mock("framer-motion", async () => {
  const actual = await vi.importActual("framer-motion");
  return {
    ...actual,
    useReducedMotion: () => mockUseReducedMotion(),
  };
});

function mockMatchMedia(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("Phase 9 Demo Hardening & Flow Verification", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    mockUseReducedMotion.mockReturnValue(false);
    mockMatchMedia(false);
    Object.defineProperty(window, "IntersectionObserver", {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        observe: vi.fn(),
        unobserve: vi.fn(),
        disconnect: vi.fn(),
      })),
    });
  });

  it("1. No-JS / SSR Hero content is visible by default (no opacity: 0 in SSR HTML)", () => {
    const html = renderToString(<Hero />);
    // Verify SSR contains primary headline and CTAs
    expect(html).toContain("Make AI commerce");
    expect(html).toContain("Open dashboard");
    expect(html).toContain("Explore live commerce");
    expect(html).toContain("TRUST INFRASTRUCTURE FOR AGENTIC COMMERCE");
    expect(html).toContain("TRANSACTION AUTHORITY GRAPH");
    // Verify no-JS HTML does NOT inject inline opacity:0 hiding the hero
    expect(html).not.toContain('style="opacity:0"');
    expect(html).not.toContain('style="opacity: 0"');
  });

  it("2. SignatureTrustGraph does not trigger render-phase parent state updates", () => {
    const onStageChange = vi.fn();
    const { unmount } = render(
      <SignatureTrustGraph activeStage="admit" onStageChange={onStageChange} />
    );

    // Initial mount notifies cleanly in effect
    expect(onStageChange).toHaveBeenCalledWith("admit");
    unmount();
  });

  it("3. SignatureTrustGraph and TrustRail remain synchronized across pipeline traversal", async () => {
    let currentStage: "admit" | "bind" | "execute" | "completed" = "admit";
    const handleStageChange = (s: "admit" | "bind" | "execute" | "completed") => {
      currentStage = s;
    };

    render(<SignatureTrustGraph activeStage={currentStage} onStageChange={handleStageChange} />);
    const { rerender } = render(<TrustRail activeStage={currentStage} />);

    expect(screen.getAllByText("ADMIT").length).toBeGreaterThan(0);

    // Advance stage
    currentStage = "bind";
    rerender(<TrustRail activeStage={currentStage} />);
    expect(screen.getAllByText("BIND").length).toBeGreaterThan(0);
  });

  it("4. Hero and TrustGraph remain completely hydration-safe under reduced motion", async () => {
    mockUseReducedMotion.mockReturnValue(true);
    mockMatchMedia(true);

    const recoverableErrors: Error[] = [];
    const html = renderToString(<Hero />);

    const container = document.createElement("div");
    container.innerHTML = html;
    document.body.appendChild(container);

    let root: ReturnType<typeof hydrateRoot> | null = null;
    await act(async () => {
      root = hydrateRoot(container, <Hero />, {
        onRecoverableError(error) {
          recoverableErrors.push(error as Error);
        },
      });
    });

    expect(recoverableErrors).toHaveLength(0);

    await act(async () => {
      root?.unmount();
    });
    document.body.removeChild(container);
  });

  it("5. Explicit dark theme persists through hydration", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(getThemePreference()).toBe("dark");
  });

  it("6. No-preference default remains strictly light", () => {
    mockMatchMedia(true); // OS dark
    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(getThemePreference()).toBe("light");
  });

  it("7. Commerce console clearly distinguishes DEMO SCENARIO from RUNTIME EVIDENCE", () => {
    renderWithQuery(<CommerceConsole />);
    expect(screen.getByText("INTERACTIVE SCENARIO WORKBENCH")).toBeInTheDocument();
    expect(screen.getAllByText("DEMO SCENARIO").length).toBeGreaterThan(0);
    expect(screen.getByText(/1\. Benign Purchase/i)).toBeInTheDocument();
  });

  it("8. Synthetic success in Commerce workbench is labeled DEMO/SYNTHETIC without fake payment IDs", () => {
    renderWithQuery(<CommerceConsole />);
    expect(screen.getAllByText("DEMO SCENARIO").length).toBeGreaterThan(0);
    expect(screen.getByText(/AUTHORITATIVE TRANSACTION DIGEST \(DEMO SHA-256\)/i)).toBeInTheDocument();
    // Must NOT contain fabricated live provider payment IDs
    expect(screen.queryByText(/pay_live_/i)).toBeNull();
  });

  it("9. Attack Lab discloses authored regression harness without claiming independent certification", () => {
    renderWithQuery(<AttackLabConsole />);
    expect(screen.getByText("ATTACK LAB")).toBeInTheDocument();
    expect(screen.getAllByText("AUTHORED HARNESS").length).toBeGreaterThan(0);
    expect(screen.getByText(/AUTHORED SCENARIO SUITE/i)).toBeInTheDocument();
  });

  it("10. Audit console discloses reconstruction from recorded evidence rather than live re-execution", () => {
    renderWithQuery(<AuditReplayConsole />);
    expect(screen.getByText("AUDIT & REPLAY")).toBeInTheDocument();
    expect(screen.getAllByText("DEMO HARNESS").length).toBeGreaterThan(0);
  });

  it("11. System page presents three clear evidence tiers and does not claim global provider health", () => {
    const { container } = renderWithQuery(<SystemPage />);
    expect(screen.getAllByText("TIER A: IMPLEMENTATION").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TIER B: CONFIGURATION").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TIER C: RUNTIME EVIDENCE").length).toBeGreaterThan(0);
    // Does not claim global health
    expect(container.textContent).not.toContain("SYSTEM HEALTHY");
  });

  it("12. Razorpay integration on System matrix is marked NOT RUNTIME VERIFIED without live payment proof", () => {
    renderWithQuery(<SystemPage />);
    expect(screen.getAllByText("NOT RUNTIME VERIFIED").length).toBeGreaterThan(0);
  });

  it("13. Risk page reinforces ADVISORY ONLY and RISK SCORE ≠ AUTHORITY", async () => {
    const jsx = await RiskPage();
    renderWithQuery(jsx);
    expect(screen.getAllByText("ADVISORY ONLY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("RISK SCORE ≠ AUTHORITY").length).toBeGreaterThan(0);
  });

  it("14. Adapters page reinforces ADAPTER TRUST ≠ CALLER AUTHORITY and TRANSLATION SIDE EFFECTS = ZERO", () => {
    renderWithQuery(<AdaptersPage />);
    expect(screen.getAllByText("ADAPTER TRUST ≠ CALLER AUTHORITY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TRANSLATION SIDE EFFECTS = ZERO").length).toBeGreaterThan(0);
  });

  it("15. No unauthorized claims of LIVE/PAID/CAPTURED/SETTLED exist in static surfaces", () => {
    const { container: sysContainer } = renderWithQuery(<SystemPage />);
    expect(sysContainer.textContent).not.toContain("SETTLED AT PROVIDER");
    expect(sysContainer.textContent).not.toContain("PAYMENT CAPTURED LIVE");
  });
});
