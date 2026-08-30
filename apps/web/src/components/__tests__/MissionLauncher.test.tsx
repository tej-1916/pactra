import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MissionLauncher } from "@/components/mission/MissionLauncher";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const fetchMock = vi.fn();

beforeEach(() => {
  push.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

describe("MissionLauncher", () => {
  it("sends only fields MissionConstraints accepts, and adds none of its own", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(
      jsonResponse(201, {
        id: "mission-1",
        state: "AWAITING_APPROVAL",
        raw_query: "Find wireless earbuds under 4000, min rating 4.2",
        quantity: 1,
        offers: [],
        policy_decision: null,
        created_at: "2026-08-28T00:00:00Z",
      }),
    );

    render(<MissionLauncher />);
    await user.click(screen.getByRole("button", { name: /run mission/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body)) as {
      constraints: Record<string, unknown>;
      quantity: number;
    };

    expect(Object.keys(body).sort()).toEqual(["constraints", "quantity", "raw_query"]);
    expect(Object.keys(body.constraints).sort()).toEqual([
      "category",
      "currency",
      "hard_limit_inr",
      "min_rating",
      "soft_budget_inr",
    ]);
    expect(body.constraints.currency).toBe("INR");
  });

  it("navigates to the created mission and remembers it locally", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(
      jsonResponse(201, {
        id: "mission-42",
        state: "AWAITING_APPROVAL",
        raw_query: "q",
        quantity: 1,
        offers: [],
        policy_decision: null,
        created_at: "2026-08-28T00:00:00Z",
      }),
    );

    render(<MissionLauncher />);
    await user.click(screen.getByRole("button", { name: /run mission/i }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/missions/mission-42"));
    const stored = window.localStorage.getItem("pactra.mission-register.v1");
    expect(stored).toContain("mission-42");
    // The idempotency key is minted once per mission and reused on retry.
    expect(stored).toContain("pactra-console-mission-42");
  });

  it("shows the reason code verbatim when the API refuses", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(
      jsonResponse(409, {
        detail: { reason_code: "HARD_LIMIT_EXCEEDED", detail: "amount exceeds the ceiling" },
      }),
    );

    render(<MissionLauncher />);
    await user.click(screen.getByRole("button", { name: /run mission/i }));

    expect(await screen.findByText("HARD_LIMIT_EXCEEDED")).toBeInTheDocument();
    expect(screen.getByText(/absolute ceiling/i)).toBeInTheDocument();
  });

  it("reports an unreachable API as unavailable rather than as a refusal", async () => {
    const user = userEvent.setup();
    fetchMock.mockRejectedValue(new Error("connection refused"));

    render(<MissionLauncher />);
    await user.click(screen.getByRole("button", { name: /run mission/i }));

    expect(await screen.findByText("PACTRA API unavailable")).toBeInTheDocument();
  });

  it("refuses to send a budget ordering MissionConstraints would reject", async () => {
    const user = userEvent.setup();
    render(<MissionLauncher />);

    const hardLimit = screen.getByLabelText(/hard limit/i);
    await user.clear(hardLimit);
    await user.type(hardLimit, "100");

    expect(screen.getByText(/cannot exceed the hard limit/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /run mission/i }));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
