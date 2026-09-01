import { render, screen } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { Hero } from "@/components/hero/Hero";
import { PactraBootReveal } from "@/components/motion/PactraBootReveal";

describe("Phase 1 Preservation & Integration", () => {
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
  it("19. PactraBootReveal remains mounted on initial load", () => {
    sessionStorage.clear();
    const { container } = render(<PactraBootReveal />);
    expect(container).toBeInTheDocument();
  });

  it("20. Phase-1 Hero headline semantics remain unchanged ('Make AI commerce trustworthy.')", () => {
    render(<Hero />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/Make AI commerce trustworthy\./i);
    expect(screen.getByText(/TRUST INFRASTRUCTURE FOR AGENTIC COMMERCE/i)).toBeInTheDocument();
  });
});
