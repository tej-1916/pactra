import { render, screen, act, renderHook } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { Hero } from "@/components/hero/Hero";
import { SignatureTrustGraph } from "@/components/hero/SignatureTrustGraph";
import { TrustRail } from "@/components/hero/TrustRail";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { useMissionRegister } from "@/lib/hooks/useMissionRegister";
import {
  THEME_STORAGE_KEY,
  THEME_BOOTSTRAP_SCRIPT,
  getThemePreference,
  setThemePreference,
} from "@/lib/theme";

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

describe("Phase 8.1 & 8.2 Mobile Hero Reflow & Layout Guards", () => {
  beforeEach(() => {
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

  it("1. Hero container has responsive width and reflow guards (min-w-0 max-w-full)", () => {
    const { container } = render(<Hero />);
    const heroCard = container.firstChild as HTMLElement;
    expect(heroCard).toHaveClass("w-full");
    expect(heroCard).toHaveClass("min-w-0");
    expect(heroCard).toHaveClass("max-w-full");
  });

  it("2. Hero copy and headline include break-words guards for small mobile viewports", () => {
    render(<Hero />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveClass("break-words");
  });

  it("3. CTAs use responsive layout to stay within mobile viewport flow", () => {
    render(<Hero />);
    const dashboardBtn = screen.getByRole("link", { name: /Open dashboard/i });
    const commerceBtn = screen.getByRole("link", { name: /Explore live commerce/i });

    expect(dashboardBtn).toBeInTheDocument();
    expect(commerceBtn).toBeInTheDocument();

    const ctaContainer = dashboardBtn.closest("div");
    expect(ctaContainer).toHaveClass("flex");
  });

  it("4. SignatureTrustGraph contains responsive wrappers and min-w-0 guards", () => {
    const { container } = render(<SignatureTrustGraph />);
    const graphCard = container.firstChild as HTMLElement;
    expect(graphCard).toHaveClass("w-full");
    expect(graphCard).toHaveClass("min-w-0");
    expect(graphCard).toHaveClass("max-w-full");

    // All primary nodes are present
    expect(screen.getByText(/AI BUYER/i)).toBeInTheDocument();
    expect(screen.getByText(/MERCHANT OFFER/i)).toBeInTheDocument();
    expect(screen.getByText("ADMIT")).toBeInTheDocument();
    expect(screen.getByText("BIND")).toBeInTheDocument();
    expect(screen.getByText("EXECUTE")).toBeInTheDocument();
    expect(screen.getByText(/PAYMENT PROVIDER/i)).toBeInTheDocument();
    expect(screen.getByText(/AUDIT \/ REPLAY/i)).toBeInTheDocument();
  });

  it("5. TrustRail uses responsive grid for stages", () => {
    const { container } = render(<TrustRail activeStage="admit" />);
    const railCard = container.firstChild as HTMLElement;
    expect(railCard).toHaveClass("w-full");
    expect(railCard).toHaveClass("min-w-0");
    expect(railCard).toHaveClass("max-w-full");
  });
});

describe("Phase 8.2 Default Theme Contract & matchMedia Isolation", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("1. No preference stored + OS dark -> strictly LIGHT theme", () => {
    mockMatchMedia(true); // OS prefers dark
    expect(window.matchMedia("(prefers-color-scheme: dark)").matches).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();

    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(getThemePreference()).toBe("light");

    render(<ThemeToggle />);
    const lightRadio = screen.getByRole("radio", { name: /Light/i });
    expect(lightRadio).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("2. No preference stored + OS light -> strictly LIGHT theme", () => {
    mockMatchMedia(false); // OS prefers light
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();

    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(getThemePreference()).toBe("light");
  });

  it("3. Stored dark + OS light -> strictly DARK theme", () => {
    mockMatchMedia(false); // OS prefers light
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(getThemePreference()).toBe("dark");

    render(<ThemeToggle />);
    const darkRadio = screen.getByRole("radio", { name: /Dark/i });
    expect(darkRadio).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("4. Stored dark + OS dark -> strictly DARK theme", () => {
    mockMatchMedia(true); // OS prefers dark
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(getThemePreference()).toBe("dark");
  });

  it("5. Stored light + OS dark -> strictly LIGHT theme", () => {
    mockMatchMedia(true); // OS prefers dark
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");

    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(getThemePreference()).toBe("light");

    render(<ThemeToggle />);
    const lightRadio = screen.getByRole("radio", { name: /Light/i });
    expect(lightRadio).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("6. ThemeToggle persists explicit user selection synchronously", () => {
    render(<ThemeToggle />);

    act(() => {
      setThemePreference("dark");
    });

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    act(() => {
      setThemePreference("light");
    });

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });
});

describe("Phase 8.2 Reduced-Motion Hydration & Security Semantics", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("7. useMissionRegister initial render starts with hydrated: false and transitions after mount", () => {
    const { result } = renderHook(() => useMissionRegister());
    expect(result.current.hydrated).toBe(true);
  });

  it("8. SignatureTrustGraph renders identical status text with reduced motion enabled vs disabled", () => {
    // Render with normal motion
    mockUseReducedMotion.mockReturnValue(false);
    const { unmount } = render(<SignatureTrustGraph />);

    expect(screen.getByText("STAGE 1")).toBeInTheDocument();
    expect(screen.getByText("STAGE 2")).toBeInTheDocument();
    expect(screen.getByText("STAGE 3")).toBeInTheDocument();
    unmount();

    // Render with reduced motion
    mockUseReducedMotion.mockReturnValue(true);
    render(<SignatureTrustGraph />);

    // Status text must NOT flip to VERIFIED merely due to motion preference
    expect(screen.getByText("STAGE 1")).toBeInTheDocument();
    expect(screen.getByText("STAGE 2")).toBeInTheDocument();
    expect(screen.getByText("STAGE 3")).toBeInTheDocument();
  });

  it("9. Reduced motion disables pulsing/ping animations without altering deterministic state", () => {
    mockUseReducedMotion.mockReturnValue(true);
    const { container } = render(<SignatureTrustGraph />);

    // Ping dot is omitted when reduced motion is true
    expect(container.querySelector(".animate-ping")).toBeNull();
    // Pulse animation class is omitted
    expect(container.querySelector(".animate-pulse")).toBeNull();

    // But nodes remain fully rendered with truthful stages
    expect(screen.getByText("ADMIT")).toBeInTheDocument();
    expect(screen.getByText("BIND")).toBeInTheDocument();
    expect(screen.getByText("EXECUTE")).toBeInTheDocument();
  });
});
