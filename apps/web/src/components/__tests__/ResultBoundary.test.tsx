import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ResultBoundary } from "@/components/ui/ResultBoundary";
import { NotProvided, PartialDataState, RefusalState } from "@/components/ui/States";
import type { ApiResult } from "@/lib/api/result";

function boundary(result: ApiResult<{ value: string }> | undefined, isLoading = false) {
  return render(
    <ResultBoundary result={result} isLoading={isLoading} what="payment intent">
      {(data) => <p>{data.value}</p>}
    </ResultBoundary>,
  );
}

/**
 * These five outcomes look alike on a lazy screen and are five different facts.
 * The failure this file guards against is the one the phase brief names: a
 * stopped backend rendering as "0", and a security refusal rendering as a
 * crash.
 */
describe("loading", () => {
  it("says it is still asking, and says so to a screen reader", () => {
    boundary(undefined, true);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("treats an undefined result as loading rather than as empty", () => {
    boundary(undefined, false);

    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("backend unavailable", () => {
  it("never renders an unreachable backend as empty or as zero", () => {
    boundary({ kind: "unavailable", detail: "connect ECONNREFUSED 127.0.0.1:8000" });

    expect(screen.getByText("PACTRA API unavailable")).toBeInTheDocument();
    expect(screen.getByText(/connect ECONNREFUSED/)).toBeInTheDocument();
    expect(screen.getByText(/not the same as there being nothing to show/i)).toBeInTheDocument();
    expect(screen.queryByText(/^No payment intent yet$/)).toBeNull();
  });
});

describe("empty", () => {
  it("renders a 404 as nothing-exists-yet, with the reason code verbatim", () => {
    boundary({
      kind: "failed",
      status: 404,
      reasonCode: "PAYMENT_INTENT_NOT_FOUND",
      detail: "not found",
    });

    expect(screen.getByText("No payment intent yet")).toBeInTheDocument();
    expect(screen.getByText("PAYMENT_INTENT_NOT_FOUND")).toBeInTheDocument();
    expect(screen.getByText(/No payment intent exists for this mission/i)).toBeInTheDocument();
  });
});

describe("security refusal", () => {
  it("renders a 409 as a refusal, not as an error", () => {
    boundary({
      kind: "failed",
      status: 409,
      reasonCode: "AUTHORIZATION_REPLAY_DETECTED",
      detail: "already consumed",
    });

    expect(screen.getByText("PACTRA refused this request")).toBeInTheDocument();
    expect(screen.getByText("AUTHORIZATION_REPLAY_DETECTED")).toBeInTheDocument();
    expect(screen.getByText(/already consumed and cannot authorize another payment/i)).toBeInTheDocument();
    expect(screen.getByText(/A refusal is an answer, not a malfunction/i)).toBeInTheDocument();
    expect(screen.queryByText(/Could not read/i)).toBeNull();
  });

  it("treats 401 and 403 as refusals too", () => {
    for (const status of [401, 403] as const) {
      const { unmount } = boundary({
        kind: "failed",
        status,
        reasonCode: "CAPABILITY_DENIED",
        detail: "denied",
      });
      expect(screen.getByText("PACTRA refused this request")).toBeInTheDocument();
      unmount();
    }
  });
});

describe("error", () => {
  it("renders a 500 as an error, with whatever detail came back", () => {
    boundary({ kind: "failed", status: 500, reasonCode: null, detail: "internal server error" });

    expect(screen.getByText("Could not read the payment intent")).toBeInTheDocument();
    expect(screen.getByText(/HTTP 500\. internal server error/)).toBeInTheDocument();
  });
});

describe("success", () => {
  it("renders the children with the data and nothing else", () => {
    boundary({ kind: "ok", status: 200, data: { value: "QUEUED" } });

    expect(screen.getByText("QUEUED")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("partial data and unsupported fields", () => {
  it("names what arrived and what did not", () => {
    render(
      <PartialDataState
        title="No trusted trace"
        detail="Replay returned trusted: false."
      />,
    );

    expect(screen.getByText("No trusted trace")).toBeInTheDocument();
    expect(screen.getByText(/Replay returned trusted: false/)).toBeInTheDocument();
  });

  it("distinguishes an unsupported field from an empty one", () => {
    render(<NotProvided what="provider_order_id" since="C2" />);

    const slot = screen.getByText("NOT YET PROVIDED").closest("span")!;
    expect(slot.getAttribute("title")).toMatch(/not part of the current backend read contract/i);
    expect(slot.getAttribute("title")).toMatch(/Expected from C2/i);
    expect(slot.getAttribute("title")).toMatch(/Nothing is inferred or filled in for it/i);
  });

  it("renders a refusal in the secure tone rather than the critical one", () => {
    const { container } = render(
      <RefusalState title="Refused" detail="A control refused the action." />,
    );

    const frame = container.firstElementChild!;
    expect(frame.className).toContain("--color-secure");
    expect(frame.className).not.toContain("--color-critical");
  });
});
