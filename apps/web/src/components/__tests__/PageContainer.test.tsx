import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PageContainer } from "@/components/ui/PageContainer";

describe("PageContainer (Phase 2 App Shell)", () => {
  it("16. renders standard variant with max-w-[1280px]", () => {
    render(
      <PageContainer variant="standard">
        <div>Standard Content</div>
      </PageContainer>
    );

    const container = screen.getByText("Standard Content").parentElement;
    expect(container).toHaveClass("max-w-[1280px]");
    expect(container).toHaveClass("px-4");
    expect(container).toHaveClass("sm:px-6");
    expect(container).toHaveClass("lg:px-8");
  });

  it("17. renders wide variant with max-w-[1480px]", () => {
    render(
      <PageContainer variant="wide">
        <div>Wide Content</div>
      </PageContainer>
    );

    const container = screen.getByText("Wide Content").parentElement;
    expect(container).toHaveClass("max-w-[1480px]");
    expect(container).toHaveClass("px-4");
    expect(container).toHaveClass("sm:px-6");
    expect(container).toHaveClass("lg:px-8");
  });
});
