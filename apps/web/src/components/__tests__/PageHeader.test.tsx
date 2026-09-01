import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PageHeader } from "@/components/shell/PageHeader";

describe("PageHeader (Phase 2 App Shell)", () => {
  it("18. renders eyebrow, title, description, and action content correctly", () => {
    render(
      <PageHeader
        eyebrow="OVERVIEW"
        title="Trust infrastructure at a glance"
        description="ADMIT → BIND → EXECUTE system status and evidence."
        actions={<button type="button">Run Audit</button>}
      />
    );

    expect(screen.getByText("OVERVIEW")).toBeInTheDocument();
    expect(screen.getByText("Trust infrastructure at a glance")).toBeInTheDocument();
    expect(screen.getByText("ADMIT → BIND → EXECUTE system status and evidence.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Audit" })).toBeInTheDocument();
  });
});
