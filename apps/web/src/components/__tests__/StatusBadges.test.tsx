import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReasonCode } from "@/components/ui/ReasonCode";
import {
  ProtocolStatusBadge,
  RiskBadge,
  SecurityStatusBadge,
  SeverityChip,
  TaintBadge,
  VerificationBadge,
} from "@/components/ui/StatusBadges";

describe("SecurityStatusBadge", () => {
  it("labels a blocked attack BLOCKED and explains why that is a success", () => {
    render(<SecurityStatusBadge status="BLOCKED" expectedStatus="BLOCKED" category="TRANSACTION" />);
    const badge = screen.getByText("BLOCKED");
    expect(badge).toBeInTheDocument();
    expect(badge.closest("span")).toHaveAttribute("title", expect.stringContaining("refused"));
  });

  it("never renders ERROR as BLOCKED", () => {
    render(<SecurityStatusBadge status="ERROR" expectedStatus="BLOCKED" category="AUDIT" />);
    expect(screen.getByText("ERROR")).toBeInTheDocument();
    expect(screen.queryByText("BLOCKED")).toBeNull();
  });

  it("labels a refused benign control as a false positive rather than a success", () => {
    render(
      <SecurityStatusBadge status="BLOCKED" expectedStatus="NOT_BLOCKED" category="BENIGN_CONTROL" />,
    );
    expect(screen.getByText("FALSE POSITIVE")).toBeInTheDocument();
  });

  it("gives a demonstrated limitation its own label", () => {
    render(
      <SecurityStatusBadge
        status="NOT_BLOCKED"
        expectedStatus="NOT_BLOCKED"
        category="KNOWN_LIMITATION"
      />,
    );
    expect(screen.getByText("KNOWN LIMITATION")).toBeInTheDocument();
  });

  /**
   * Status must not be communicated by colour alone. Every badge carries the
   * word, which is what makes it readable to a screen reader and to anyone who
   * cannot distinguish the two greens from the two reds.
   */
  it("communicates status in text, not only in colour", () => {
    render(
      <SecurityStatusBadge status="NOT_BLOCKED" expectedStatus="BLOCKED" category="AUTHORITY" />,
    );
    expect(screen.getByText("NOT BLOCKED")).toBeInTheDocument();
  });
});

describe("SeverityChip", () => {
  it("describes itself as attack severity and disclaims CVSS", () => {
    render(<SeverityChip severity="CRITICAL" />);
    const chip = screen.getByText("CRITICAL");
    expect(chip.closest("span")).toHaveAttribute("title", expect.stringContaining("not CVSS"));
  });
});

describe("RiskBadge", () => {
  it("states that a band is advice, not a decision", () => {
    render(<RiskBadge band="CRITICAL" />);
    const badge = screen.getByText("RISK CRITICAL");
    expect(badge.closest("span")).toHaveAttribute("title", expect.stringContaining("not a synonym for DENY"));
  });
});

describe("TaintBadge", () => {
  it("says taint is sticky", () => {
    render(<TaintBadge tainted />);
    expect(screen.getByText("TAINTED").closest("span")).toHaveAttribute(
      "title",
      expect.stringContaining("sticky"),
    );
  });

  it("distinguishes untainted without implying trust", () => {
    render(<TaintBadge tainted={false} />);
    expect(screen.getByText("NOT TAINTED")).toBeInTheDocument();
  });
});

describe("ProtocolStatusBadge", () => {
  it("prints the exact status the matrix declares", () => {
    render(<ProtocolStatusBadge status="PARTIAL" />);
    expect(screen.getByText("PARTIAL")).toBeInTheDocument();
  });
});

describe("VerificationBadge", () => {
  it("says VALID or CORRUPTED, never a hedge", () => {
    const { rerender } = render(<VerificationBadge valid />);
    expect(screen.getByText("VALID")).toBeInTheDocument();
    rerender(<VerificationBadge valid={false} />);
    expect(screen.getByText("CORRUPTED")).toBeInTheDocument();
  });
});

describe("ReasonCode", () => {
  it("prints the machine code verbatim and adds prose beside it, never instead", () => {
    render(<ReasonCode code="AUTHORIZATION_REPLAY_DETECTED" describe />);
    expect(screen.getByText("AUTHORIZATION_REPLAY_DETECTED")).toBeInTheDocument();
    expect(screen.getByText(/already consumed/)).toBeInTheDocument();
  });

  it("prints an undescribed code as itself rather than inventing an explanation", () => {
    render(<ReasonCode code="A_FUTURE_CODE" describe />);
    expect(screen.getByText("A_FUTURE_CODE")).toBeInTheDocument();
  });

  it("surfaces a reason-code mismatch instead of hiding it", () => {
    render(<ReasonCode code="HARD_LIMIT_EXCEEDED" expected="AUTHORIZATION_EXPIRED" />);
    expect(screen.getByText("HARD_LIMIT_EXCEEDED")).toBeInTheDocument();
    expect(screen.getByText(/expected AUTHORIZATION_EXPIRED/)).toBeInTheDocument();
  });

  it("says none was observed when an expectation existed but no code arrived", () => {
    render(<ReasonCode code={null} expected="WEBHOOK_SIGNATURE_INVALID" />);
    expect(screen.getByText(/none observed \(expected WEBHOOK_SIGNATURE_INVALID\)/)).toBeInTheDocument();
  });
});
