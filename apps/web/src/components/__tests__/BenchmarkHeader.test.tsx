import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BenchmarkProvenance, RunnerNotConnected } from "@/components/benchmark/BenchmarkHeader";

/**
 * The Attack Lab reads from a recorded harness run. The claim it must never
 * make is that the run constitutes independent validation — the scenarios were
 * written by the same project they test, so a high pass rate measures internal
 * regression coverage and nothing more. That disclosure travels with the
 * numbers rather than living in an appendix, and this is what keeps it there.
 */
describe("benchmark provenance", () => {
  function renderBanner() {
    return render(
      <BenchmarkProvenance
        runId="attack-run-20260830T120000Z"
        harnessVersion="attack-lab-v3"
        startedAt="2026-08-30T12:00:00Z"
        scenarios={130}
        iterations={4}
        sourceFile="reports/attack/latest.json"
      />,
    );
  }

  it("refuses the certification reading in the banner itself", () => {
    renderBanner();

    expect(screen.getByText(/AUTHORED SYNTHETIC/)).toBeInTheDocument();
    expect(screen.getByText(/not independent red-team\s+validation/i)).toBeInTheDocument();
    expect(screen.getByText(/not certification, and not an external audit/i)).toBeInTheDocument();
  });

  it("keeps the run's identity beside its numbers", () => {
    renderBanner();

    expect(screen.getByText("attack-lab-v3")).toBeInTheDocument();
    expect(screen.getByText("130")).toBeInTheDocument();
    expect(screen.getByText("reports/attack/latest.json")).toBeInTheDocument();
    expect(screen.getByText("LAST VERIFIED DEVELOPMENT BENCHMARK")).toBeInTheDocument();
  });
});

describe("no recorded run", () => {
  it("says nothing was measured, rather than showing zeroes", () => {
    render(<RunnerNotConnected detail="no file under reports/attack" />);

    expect(screen.getByText(/RUNNER NOT CONNECTED/)).toBeInTheDocument();
    expect(screen.getByText("no file under reports/attack")).toBeInTheDocument();
    expect(screen.getByText(/An empty benchmark is not a passing one/i)).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
  });
});
