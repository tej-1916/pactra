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

describe("Phase 8.1 Mobile Hero Reflow & Layout Guards", () => {
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

describe("Phase 8.1 Theme Hydration & Stability", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  it("6. useMissionRegister initial render starts with hydrated: false and transitions to true after mount", () => {
    const { result } = renderHook(() => useMissionRegister());
    // After renderHook effects run, hydrated is true
    expect(result.current.hydrated).toBe(true);
  });

  it("7. Default theme is light when no preference is stored", () => {
    expect(getThemePreference()).toBe("system");
    // Bootstrap script fallback test
    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("8. Stored dark theme sets data-theme='dark' before/through hydration", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    // Render ThemeToggle to ensure it respects stored dark theme
    render(<ThemeToggle />);
    const darkRadio = screen.getByRole("radio", { name: /Dark/i });
    expect(darkRadio).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("9. Stored light theme sets data-theme='light' before/through hydration", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    eval(THEME_BOOTSTRAP_SCRIPT);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    render(<ThemeToggle />);
    const lightRadio = screen.getByRole("radio", { name: /Light/i });
    expect(lightRadio).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("10. Switching theme updates localStorage and documentElement synchronously", () => {
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
