import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunnerNotConnected } from "@/components/benchmark/BenchmarkHeader";
import { EmptyState, ErrorState, UnavailableState } from "@/components/ui/States";

/**
 * The rule these guard: an unreachable backend must render as "PACTRA API
 * unavailable", never as zeroes. Empty is not the same as failure, and a
 * console that collapses them teaches an operator to read an outage as calm.
 */
describe("state components", () => {
  it("renders an unavailable backend as unavailable, with no fabricated count", () => {
    render(
      <UnavailableState
        title="PACTRA API unavailable"
        detail="Nothing is being reported as zero."
      />,
    );
    expect(screen.getByText("PACTRA API unavailable")).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("renders emptiness as a fact about the data, not about the connection", () => {
    render(<EmptyState title="No missions yet" detail="Run one from the workbench." />);
    expect(screen.getByText("No missions yet")).toBeInTheDocument();
    expect(screen.queryByText(/unavailable/i)).toBeNull();
  });

  it("renders a refusal distinctly from an outage", () => {
    render(<ErrorState title="The kernel refused this request" detail="HTTP 409" />);
    expect(screen.getByText("The kernel refused this request")).toBeInTheDocument();
  });
});

describe("RunnerNotConnected", () => {
  it("says the runner is not connected rather than showing an empty benchmark", () => {
    render(<RunnerNotConnected detail="No report in reports/attack-lab." />);
    expect(screen.getByText(/RUNNER NOT CONNECTED/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is fabricated/)).toBeInTheDocument();
    expect(screen.getByText(/An empty benchmark is not a passing one/)).toBeInTheDocument();
  });

  it("explains that the absence of an HTTP surface is deliberate", () => {
    render(<RunnerNotConnected detail="none found" />);
    expect(screen.getByText(/no HTTP surface/i)).toBeInTheDocument();
    expect(screen.getByText(/unauthenticated front door/i)).toBeInTheDocument();
  });
});
