import { render, screen, fireEvent } from "@testing-library/react";
import { beforeAll, describe, it, expect } from "vitest";

import { DarkProductSection } from "@/components/hero/DarkProductSection";

/**
 * The panel's animated background observes its own visibility to pause the
 * canvas loop off-screen. jsdom ships neither observer, and the component is
 * right to use them, so the test environment supplies inert ones rather than
 * the component growing a branch that exists only for tests. They never fire:
 * nothing here asserts on animation, only on the text the panel renders.
 */
beforeAll(() => {
  class InertObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  globalThis.IntersectionObserver ??= InertObserver as unknown as typeof IntersectionObserver;
  globalThis.ResizeObserver ??= InertObserver as unknown as typeof ResizeObserver;
});

/**
 * The homepage panel is a conceptual explainer, and this file is the guard that
 * keeps it one.
 *
 * It exists because the panel is the first thing a reader sees and the only
 * surface on the overview page with no API behind it — every string in it is
 * hand-authored, so nothing else would notice if a fabricated metric, a
 * provider-success state or an invented status badge were added back. The
 * project's numbers come from an executed harness run or from a live API read;
 * a marketing panel is neither, so it states qualitative design properties and
 * nothing more.
 *
 * Assertions run across ALL FOUR TABS, because the prohibited content lived in
 * per-tab data rather than in the shared frame.
 */

/** Every tab's content, concatenated. The panel renders one tab at a time. */
function textAcrossAllTabs(container: HTMLElement): string {
  const tabs = screen.getAllByRole("button");
  expect(tabs).toHaveLength(4);

  let combined = container.textContent ?? "";
  for (const tab of tabs) {
    fireEvent.click(tab);
    combined += `\n${container.textContent ?? ""}`;
  }
  return combined;
}

describe("DarkProductSection public-claim safety", () => {
  it("never states a provider-success payment result", () => {
    const { container } = render(<DarkProductSection />);
    const text = textAcrossAllTabs(container);

    // The exact pairing that read as "a Razorpay payment succeeded".
    expect(text).not.toMatch(/evidence_status/i);
    expect(text).not.toMatch(/EXECUTE_VERIFIED/);

    // An Order is not a Payment: the panel may never assert any of these.
    expect(text).not.toMatch(/\bpaid\b/i);
    expect(text).not.toMatch(/\bcaptured\b/i);
    expect(text).not.toMatch(/\bsettled\b/i);
    expect(text).not.toMatch(/\bcheckout\b/i);
  });

  it("shows no fabricated performance or pass-rate metric", () => {
    const { container } = render(<DarkProductSection />);
    const text = textAcrossAllTabs(container);

    expect(text).not.toMatch(/1\.2\s*ms/i);
    expect(text).not.toMatch(/\d+\s*ms\b/i);
    expect(text).not.toMatch(/\d+(\.\d+)?\s*%/);
    expect(text).not.toMatch(/0 FAILS/i);

    // Design properties are allowed; they are labelled as such.
    expect(screen.getByText(/DESIGN PROPERTIES · NOT MEASUREMENTS/i)).toBeInTheDocument();
  });

  it("claims no certification, verdict or runtime evidence in its status chrome", () => {
    const { container } = render(<DarkProductSection />);
    const text = textAcrossAllTabs(container);

    expect(text).not.toMatch(/VERIFIED_LEGAL/i);
    expect(text).not.toMatch(/certif/i);
    expect(text).not.toMatch(/\baudited\b/i);

    // States plainly what it is not — in the status chrome and again in prose,
    // which is why this matches more than one node.
    expect(screen.getAllByText(/NOT RUNTIME EVIDENCE/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/not runtime evidence, not a measurement/i)).toBeInTheDocument();
  });

  it("labels its code blocks illustrative and names no file the repository lacks", () => {
    const { container } = render(<DarkProductSection />);
    const text = textAcrossAllTabs(container);

    // There is no Rust in this repository; the panel must not imply otherwise.
    expect(text).not.toMatch(/pactra_kernel\.rs/i);
    expect(text).not.toMatch(/\.rs\b/);

    // Every tab's snippet carries the label, not just the one that had it.
    const tabs = screen.getAllByRole("button");
    for (const tab of tabs) {
      fireEvent.click(tab);
      expect(container.textContent).toMatch(/ILLUSTRATIVE SCHEMA EXAMPLE/i);
    }
  });

  it("uses INR semantics wherever it shows an amount", () => {
    const { container } = render(<DarkProductSection />);
    const text = textAcrossAllTabs(container);

    // The project is INR/paise end to end; a dollars-and-cents example was wrong.
    expect(text).not.toMatch(/in cents/i);
    expect(text).not.toMatch(/\$\d/);
    expect(text).toMatch(/paise/i);
    expect(text).toMatch(/₹/);
  });
});
