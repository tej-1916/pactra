import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { TabPanel, Tabs } from "@/components/ui/Tabs";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "offers", label: "Offers" },
  { id: "audit", label: "Audit" },
];

function Harness() {
  const [active, setActive] = useState("overview");
  return (
    <>
      <Tabs tabs={TABS} active={active} onChange={setActive} label="Mission views" />
      <TabPanel id="overview" active={active}>
        overview panel
      </TabPanel>
      <TabPanel id="offers" active={active}>
        offers panel
      </TabPanel>
      <TabPanel id="audit" active={active}>
        audit panel
      </TabPanel>
    </>
  );
}

/**
 * A security console an operator drives from the keyboard should not require a
 * pointer to change view.
 */
describe("Tabs", () => {
  it("exposes a real tablist with an accessible name", () => {
    render(<Harness />);
    expect(screen.getByRole("tablist", { name: "Mission views" })).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });

  it("marks exactly one tab selected and shows only its panel", () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("overview panel")).toBeInTheDocument();
    expect(screen.queryByText("offers panel")).toBeNull();
  });

  it("switches panels on click", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("tab", { name: "Offers" }));
    expect(screen.getByText("offers panel")).toBeInTheDocument();
    expect(screen.queryByText("overview panel")).toBeNull();
  });

  it("moves between tabs with arrow keys", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("tab", { name: "Overview" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Offers" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  });

  it("wraps at the ends and supports Home/End", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    screen.getByRole("tab", { name: "Overview" }).focus();
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Audit" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Audit" })).toHaveAttribute("aria-selected", "true");
  });

  it("keeps only the selected tab in the tab order", () => {
    render(<Harness />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Offers" })).toHaveAttribute("tabindex", "-1");
  });
});
