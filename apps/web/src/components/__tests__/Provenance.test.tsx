import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Authoritative,
  AuthoritativeField,
  TaintedText,
  TaintFindings,
} from "@/components/ui/Provenance";

const RLO = "\u202E"; // U+202E right-to-left override
const CYRILLIC_A = "\u0410"; // U+0410, visually identical to Latin A

/**
 * The rule under test is the C1 trust contract's presentation requirement: no
 * merchant string may visually masquerade as TOTAL, PAYEE, POLICY,
 * AUTHORIZATION or PAYMENT STATE. These assertions check the machine-readable
 * side of that — the provenance marking a screen reader and a reviewer can both
 * follow — rather than pixels.
 */
describe("authoritative values", () => {
  it("marks itself as authoritative and renders the value verbatim", () => {
    render(<Authoritative>MERCH_042</Authoritative>);

    const element = screen.getByText("MERCH_042");
    expect(element.dataset.provenance).toBe("authoritative");
  });

  it("states its source beside a reserved heading, never leaving it unattributed", () => {
    render(
      <AuthoritativeField
        heading="TOTAL"
        value="4999 INR"
        source="Bound machine amount from the reloaded authoritative offer row."
      />,
    );

    expect(screen.getByText("TOTAL")).toBeInTheDocument();
    expect(screen.getByText("4999 INR")).toBeInTheDocument();
    expect(screen.getByText(/reloaded authoritative offer row/i)).toBeInTheDocument();
  });
});

describe("merchant display data", () => {
  it("marks itself as tainted and labels what the string is", () => {
    render(<TaintedText value="Premium Headphones" label="Product title" />);

    const wrapper = screen.getByText("Premium Headphones").closest("[data-provenance]")!;
    expect(wrapper.getAttribute("data-provenance")).toBe("tainted");
    expect(wrapper.getAttribute("data-suspicious")).toBe("false");
    expect(screen.getByText("Product title")).toBeInTheDocument();
  });

  it("isolates the string's bidi context with a bdi element", () => {
    const { container } = render(<TaintedText value="Premium Headphones" />);

    const bdi = container.querySelector("bdi");
    expect(bdi).not.toBeNull();
    expect(bdi?.getAttribute("dir")).toBe("ltr");
    expect(bdi?.textContent).toBe("Premium Headphones");
  });

  it("strips a bidi override and flags the string as suspicious", () => {
    const { container } = render(<TaintedText value={`Headphones ${RLO}999`} />);

    expect(container.textContent).not.toContain(RLO);
    const wrapper = container.querySelector("[data-provenance='tainted']")!;
    expect(wrapper.getAttribute("data-suspicious")).toBe("true");
  });

  it("announces the finding to a screen reader rather than cleaning silently", () => {
    render(<TaintedText value={`Headphones ${RLO}999`} />);

    expect(
      screen.getByText(/bidirectional formatting characters/i),
    ).toBeInTheDocument();
  });

  it("renders an em dash for a null value, and no marker", () => {
    render(<TaintedText value={null} label="Product title" />);

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("Product title")).toBeNull();
  });

  it("lists every finding in full when the surface has room", () => {
    render(<TaintFindings value={`${CYRILLIC_A}pple ${RLO}Store`} />);

    expect(screen.getByText("BIDI_CONTROL_REMOVED")).toBeInTheDocument();
    expect(screen.getByText("MIXED_SCRIPT")).toBeInTheDocument();
  });

  it("renders nothing when there is nothing to report", () => {
    const { container } = render(<TaintFindings value="Premium Headphones" />);

    expect(container).toBeEmptyDOMElement();
  });
});

describe("the two never collide", () => {
  it("gives a merchant string a different provenance marker than an authoritative one", () => {
    const { container } = render(
      <>
        <Authoritative>MERCH_042</Authoritative>
        <TaintedText value="Definitely The Real Merchant" label="Display name" />
      </>,
    );

    const markers = [...container.querySelectorAll("[data-provenance]")].map(
      (element) => element.getAttribute("data-provenance"),
    );
    expect(markers).toEqual(["authoritative", "tainted"]);
  });
});
