import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BenchmarkProvenance } from "@/components/benchmark/BenchmarkHeader";
import { DataTierBadge } from "@/components/ui/DataTier";
import { MetricCard } from "@/components/ui/MetricCard";

/**
 * Runtime state and development evidence must stay distinguishable on screen.
 * These tests hold the labelling that keeps them apart.
 */
describe("DataTierBadge", () => {
  it("labels a benchmark as a development benchmark, never as live", () => {
    render(<DataTierBadge tier="benchmark" />);
    const badge = screen.getByText(/LAST VERIFIED DEVELOPMENT BENCHMARK/);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", expect.stringContaining("not runtime system health"));
  });

  it("labels generated reference data as a declaration, not a measurement", () => {
    render(<DataTierBadge tier="generated" />);
    expect(screen.getByText(/GENERATED FROM SOURCE/)).toHaveAttribute(
      "title",
      expect.stringContaining("not a measurement"),
    );
  });

  it("labels live data as read from the API", () => {
    render(<DataTierBadge tier="live" />);
    expect(screen.getByText(/LIVE RUNTIME/)).toBeInTheDocument();
  });
});

describe("BenchmarkProvenance", () => {
  it("carries the run identity with the numbers it describes", () => {
    render(
      <BenchmarkProvenance
        runId="attack-run-33b353e0-034d"
        harnessVersion="pactra-attack-lab-v1"
        startedAt="2026-08-28T06:50:47Z"
        scenarios={63}
        iterations={10}
        sourceFile="run-10x.json"
      />,
    );
    expect(screen.getByText(/LAST VERIFIED DEVELOPMENT BENCHMARK/)).toBeInTheDocument();
    expect(screen.getByText("pactra-attack-lab-v1")).toBeInTheDocument();
    expect(screen.getByText("63")).toBeInTheDocument();
    expect(screen.getByText("×10")).toBeInTheDocument();
    expect(screen.getByText("run-10x.json")).toBeInTheDocument();
  });
});

describe("MetricCard", () => {
  it("prints the denominator beside the rate", () => {
    render(
      <MetricCard label="Attack block rate" value="100.0%" denominator="36 / 36 decisive hostile runs" />,
    );
    expect(screen.getByText("100.0%")).toBeInTheDocument();
    expect(screen.getByText("36 / 36 decisive hostile runs")).toBeInTheDocument();
  });

  it("can render n/a where nothing was measured", () => {
    render(<MetricCard label="Reason-code match" value="n/a" denominator="0 runs with an expectation" />);
    expect(screen.getByText("n/a")).toBeInTheDocument();
  });
});
