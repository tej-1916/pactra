import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { PactraBootReveal, BOOT_SESSION_KEY } from "@/components/motion/PactraBootReveal";

describe("PactraBootReveal", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.useFakeTimers();
  });

  it("renders aria-hidden overlay on initial unseen load", () => {
    render(<PactraBootReveal />);
    const overlay = document.querySelector('[aria-hidden="true"]');
    expect(overlay).not.toBeNull();
    expect(overlay).toHaveClass("fixed");
  });

  it("sets session storage key to prevent repeated full intros", () => {
    render(<PactraBootReveal />);
    expect(sessionStorage.getItem(BOOT_SESSION_KEY)).toBe("true");
  });

  it("skips overlay if session key is already set", () => {
    sessionStorage.setItem(BOOT_SESSION_KEY, "true");
    const { container } = render(<PactraBootReveal />);
    expect(container.firstChild).toBeNull();
  });

  it("unmounts after timeline duration", () => {
    render(<PactraBootReveal />);
    expect(document.querySelector('[aria-hidden="true"]')).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(1200);
    });

    expect(document.querySelector('[aria-hidden="true"]')).toBeNull();
  });

  it("does not render fake LIVE, SETTLED, or PAID states", () => {
    render(<PactraBootReveal />);
    const textContent = document.body.textContent || "";
    expect(textContent).not.toContain("● LIVE");
    expect(textContent).not.toContain("SETTLED");
    expect(textContent).not.toContain("PAID");
    expect(textContent).not.toContain("CAPTURED");
  });

  it("renders simplified architectural wireframe stages", () => {
    render(<PactraBootReveal />);
    expect(screen.getByText(/PACTRA CONTROL PLANE ARCHITECTURE/i)).toBeInTheDocument();
    expect(screen.getByText(/ADMIT/i)).toBeInTheDocument();
    expect(screen.getByText(/BIND/i)).toBeInTheDocument();
    expect(screen.getByText(/EXECUTE/i)).toBeInTheDocument();
  });
});
