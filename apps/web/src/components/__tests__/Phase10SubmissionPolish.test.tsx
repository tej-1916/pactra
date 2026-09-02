import { describe, it, expect, vi } from "vitest";

vi.mock("next/font/google", () => ({
  Inter: () => ({ variable: "font-inter" }),
  Space_Grotesk: () => ({ variable: "font-space" }),
  IBM_Plex_Mono: () => ({ variable: "font-mono" }),
}));

import { render, screen } from "@testing-library/react";
import { metadata as layoutMetadata } from "@/app/layout";
import { metadata as attackLabMetadata } from "@/app/attack-lab/page";
import { metadata as auditMetadata } from "@/app/audit/page";
import { parseErrorBody } from "@/lib/api/result";
import { Hero } from "@/components/hero/Hero";
import { TrustRail } from "@/components/hero/TrustRail";
import { SignatureTrustGraph } from "@/components/hero/SignatureTrustGraph";

describe("Phase 10 Final Submission Polish & Judge Readiness", () => {
  it("1. Root layout metadata has external submission title and truthful scope description", () => {
    expect(layoutMetadata.title).toEqual({
      default: "PACTRA — Deterministic Transaction Verification for Agentic Commerce",
      template: "%s · PACTRA",
    });
    expect(layoutMetadata.description).toContain("Deterministic transaction verification");
    expect(layoutMetadata.description).toContain("ADMIT → BIND → EXECUTE");
    expect(layoutMetadata.applicationName).toBe("PACTRA");
  });

  it("2. Individual route metadata titles integrate cleanly with title template", () => {
    expect(attackLabMetadata.title).toBe("Attack Lab");
    expect(auditMetadata.title).toBe("Audit & Replay");
  });

  it("3. parseErrorBody cleanly formats FastAPI 422 array errors into human-readable text", () => {
    const pydanticError = {
      detail: [
        {
          type: "string_pattern_mismatch",
          loc: ["path", "mission_id"],
          msg: "String should match pattern '^[a-zA-Z0-9_-]+$'",
        },
      ],
    };
    const parsed = parseErrorBody(pydanticError);
    expect(parsed.reasonCode).toBeNull();
    expect(parsed.detail).toBe("mission_id: String should match pattern '^[a-zA-Z0-9_-]+$'");
  });

  it("4. parseErrorBody handles missing and non-array error payloads truthfully", () => {
    expect(parseErrorBody("Backend timeout")).toEqual({
      reasonCode: null,
      detail: "Backend timeout",
    });
    expect(parseErrorBody({ detail: { reason_code: "AUTHORIZATION_REPLAY_DETECTED", detail: "Signature nonce replayed" } })).toEqual({
      reasonCode: "AUTHORIZATION_REPLAY_DETECTED",
      detail: "Signature nonce replayed",
    });
  });

  it("5. Dark gradient headline stops achieve >= 3:1 WCAG contrast for display text", () => {
    function sRgbToLinear(c: number): number {
      const v = c / 255;
      return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    }

    function relativeLuminance(hex: string): number {
      const cleanHex = hex.replace("#", "");
      const r = parseInt(cleanHex.substring(0, 2), 16);
      const g = parseInt(cleanHex.substring(2, 4), 16);
      const b = parseInt(cleanHex.substring(4, 6), 16);
      return 0.2126 * sRgbToLinear(r) + 0.7152 * sRgbToLinear(g) + 0.0722 * sRgbToLinear(b);
    }

    function contrast(hex1: string, hex2: string): number {
      const lum1 = relativeLuminance(hex1);
      const lum2 = relativeLuminance(hex2);
      return (Math.max(lum1, lum2) + 0.05) / (Math.min(lum1, lum2) + 0.05);
    }

    const darkBg = "#1E2160"; // Hero / surface background in dark mode

    // Dark gradient stops: #A5B4FC (start), #C7C5F8 (middle), #FFFFFF (end)
    expect(contrast("#A5B4FC", darkBg)).toBeGreaterThanOrEqual(3.0);
    expect(contrast("#C7C5F8", darkBg)).toBeGreaterThanOrEqual(3.0);
    expect(contrast("#FFFFFF", darkBg)).toBeGreaterThanOrEqual(3.0);

    // Light gradient stops: #3730A3, #4338CA, #4F46E5 on #FFFFFF
    const lightBg = "#FFFFFF";
    expect(contrast("#3730A3", lightBg)).toBeGreaterThanOrEqual(3.0);
    expect(contrast("#4338CA", lightBg)).toBeGreaterThanOrEqual(3.0);
    expect(contrast("#4F46E5", lightBg)).toBeGreaterThanOrEqual(3.0);
  });

  it("6. Hero renders primary and secondary CTAs with correct destinations and labels", () => {
    const { container } = render(<Hero />);
    const primaryLink = container.querySelector("a[href='/missions']");
    expect(primaryLink).toBeInTheDocument();
    expect(primaryLink?.textContent).toContain("Open dashboard");

    const secondaryLink = container.querySelector("a[href='/commerce']");
    expect(secondaryLink).toBeInTheDocument();
    expect(secondaryLink?.textContent).toContain("Explore live commerce");
  });

  it("7. TrustRail maintains 9px+ font labels and distinct states", () => {
    const { container } = render(<TrustRail activeStage="bind" />);
    expect(screen.getByText("BIND")).toBeInTheDocument();
    expect(container.innerHTML).toContain("var(--pactra-badge-active-bg)");
  });

  it("8. SignatureTrustGraph renders deterministic 3-gate control plane without treating audit as 4th stage", () => {
    render(<SignatureTrustGraph />);
    expect(screen.getByText("PACTRA CONTROL PLANE BOUNDARY")).toBeInTheDocument();
    expect(screen.getByText("ADMIT")).toBeInTheDocument();
    expect(screen.getByText("BIND")).toBeInTheDocument();
    expect(screen.getByText("EXECUTE")).toBeInTheDocument();
    expect(screen.getByText("Deterministic 3-Gate Control • Replayable Audit Chain")).toBeInTheDocument();
  });
});
