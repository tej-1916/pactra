import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Navbar } from "@/components/shell/Navbar";
import { PRIMARY_NAV, SECONDARY_NAV } from "@/components/shell/nav";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

describe("Navbar (Phase 2 App Shell)", () => {
  beforeEach(() => {
    mockPathname = "/";
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
  });

  it("1. renders primary navigation items in exact order: Overview, Live Commerce, Attack Lab, Audit", () => {
    render(<Navbar />);
    const expectedOrder = ["Overview", "Live Commerce", "Attack Lab", "Audit"];
    const navItems = PRIMARY_NAV.map((item) => item.label);
    expect(navItems).toEqual(expectedOrder);
  });

  it("2. assigns correct primary hrefs: /, /commerce, /attack-lab, /audit", () => {
    render(<Navbar />);
    expect(screen.getByRole("link", { name: /Overview/i })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: /Live Commerce/i })).toHaveAttribute("href", "/commerce");
    expect(screen.getByRole("link", { name: /Attack Lab/i })).toHaveAttribute("href", "/attack-lab");
    expect(screen.getByRole("link", { name: /Audit/i })).toHaveAttribute("href", "/audit");
  });

  it("3. Overview is active ONLY on root path '/' and NOT on non-root paths", () => {
    mockPathname = "/";
    const { unmount } = render(<Navbar />);
    expect(screen.getByRole("link", { name: /Overview/i })).toHaveAttribute("aria-current", "page");
    unmount();

    mockPathname = "/commerce";
    render(<Navbar />);
    expect(screen.getByRole("link", { name: /Overview/i })).not.toHaveAttribute("aria-current");
  });

  it("4. Live Commerce is active on /commerce", () => {
    mockPathname = "/commerce";
    render(<Navbar />);
    expect(screen.getByRole("link", { name: /Live Commerce/i })).toHaveAttribute("aria-current", "page");
  });

  it("5. Attack Lab is active on /attack-lab", () => {
    mockPathname = "/attack-lab";
    render(<Navbar />);
    expect(screen.getByRole("link", { name: /Attack Lab/i })).toHaveAttribute("aria-current", "page");
  });

  it("6. Audit is active on /audit", () => {
    mockPathname = "/audit";
    render(<Navbar />);
    expect(screen.getByRole("link", { name: /Audit/i })).toHaveAttribute("aria-current", "page");
  });

  it("7. Risk, Adapters, System remain secondary in More dropdown", () => {
    render(<Navbar />);
    const expectedSecondary = ["Risk", "Adapters", "System"];
    expect(SECONDARY_NAV.map((item) => item.label)).toEqual(expectedSecondary);

    const moreBtn = screen.getByRole("button", { name: /Secondary navigation options/i });
    fireEvent.click(moreBtn);

    expect(screen.getByRole("menuitem", { name: /Risk/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /Adapters/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: /System/i })).toBeInTheDocument();
  });

  it("8. Risk carries ADVISORY badge semantics", () => {
    render(<Navbar />);
    const moreBtn = screen.getByRole("button", { name: /Secondary navigation options/i });
    fireEvent.click(moreBtn);

    expect(screen.getByText(/ADVISORY/i)).toBeInTheDocument();
  });

  it("9. Mobile menu expands and collapses when toggled", () => {
    render(<Navbar />);
    const toggleBtn = screen.getByRole("button", { name: /Toggle navigation menu/i });
    expect(document.querySelector("#pactra-mobile-nav")).toBeNull();

    fireEvent.click(toggleBtn);
    expect(document.querySelector("#pactra-mobile-nav")).not.toBeNull();

    fireEvent.click(toggleBtn);
    expect(document.querySelector("#pactra-mobile-nav")).toBeNull();
  });

  it("10. Mobile menu exposes primary navigation section before secondary supporting surfaces", () => {
    render(<Navbar />);
    const toggleBtn = screen.getByRole("button", { name: /Toggle navigation menu/i });
    fireEvent.click(toggleBtn);

    const mobileNav = document.querySelector("#pactra-mobile-nav");
    expect(mobileNav).not.toBeNull();
    const textContent = mobileNav?.textContent || "";

    const primaryIdx = textContent.indexOf("Primary Navigation");
    const secondaryIdx = textContent.indexOf("Supporting Surfaces");

    expect(primaryIdx).toBeGreaterThan(-1);
    expect(secondaryIdx).toBeGreaterThan(-1);
    expect(primaryIdx).toBeLessThan(secondaryIdx);
  });

  it("11. ThemeToggle remains available in header and mobile drawer", () => {
    render(<Navbar />);
    expect(screen.getByRole("radiogroup", { name: /Colour theme/i })).toBeInTheDocument();
  });

  it("12. More trigger has correct expanded and popup aria attributes", () => {
    render(<Navbar />);
    const moreBtn = screen.getByRole("button", { name: /Secondary navigation options/i });

    expect(moreBtn).toHaveAttribute("aria-expanded", "false");
    expect(moreBtn).toHaveAttribute("aria-haspopup", "true");

    fireEvent.click(moreBtn);
    expect(moreBtn).toHaveAttribute("aria-expanded", "true");
  });

  it("13. Keyboard interactions: menu items close when clicked", () => {
    render(<Navbar />);
    const moreBtn = screen.getByRole("button", { name: /Secondary navigation options/i });
    fireEvent.click(moreBtn);

    const riskLink = screen.getByRole("menuitem", { name: /Risk/i });
    fireEvent.click(riskLink);

    expect(screen.queryByRole("menuitem", { name: /Risk/i })).toBeNull();
  });

  it("14. Contains no fake global system or provider status claims (e.g. 99.9% uptime, Razorpay connected)", () => {
    render(<Navbar />);
    const text = document.body.textContent || "";
    expect(text).not.toContain("99.9% uptime");
    expect(text).not.toContain("Razorpay Connected");
    expect(text).not.toContain("Live Settlement");
    expect(text).not.toContain("System Healthy");
  });

  it("15. ApiStatus is NOT mounted in Navbar or mobile drawer", () => {
    render(<Navbar />);
    const toggleBtn = screen.getByRole("button", { name: /Toggle navigation menu/i });
    fireEvent.click(toggleBtn);

    const text = document.body.textContent || "";
    expect(text).not.toContain("API Status");
    expect(document.querySelector("#api-status")).toBeNull();
  });
});
