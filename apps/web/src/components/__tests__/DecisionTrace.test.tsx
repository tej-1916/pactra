import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DecisionTrace } from "@/components/trace/DecisionTrace";
import {
  reachedExecuteTrace,
  refusedAtBindTrace,
  traceEntry,
} from "@/lib/__tests__/fixtures/decision-trace";

function stagesOf(): string[] {
  return screen
    .getAllByTestId("decision-trace-entry")
    .map((element) => element.dataset.stage as string);
}

describe("Decision Trace rendering", () => {
  it("renders every entry with its machine event type and verdict verbatim", () => {
    render(<DecisionTrace entries={reachedExecuteTrace()} />);

    expect(screen.getAllByTestId("decision-trace-entry")).toHaveLength(6);
    expect(screen.getByText("PAYMENT_INTENT_CREATED")).toBeInTheDocument();
    expect(screen.getByText("AUTHORIZATION_CONSUMED")).toBeInTheDocument();
    // The verdict word itself, not a friendlier synonym.
    expect(screen.getAllByText("ACCEPTED").length).toBeGreaterThan(0);
  });

  it("orders entries ADMIT then BIND then EXECUTE even when handed them shuffled", () => {
    const shuffled = [...reachedExecuteTrace()].reverse();
    render(<DecisionTrace entries={shuffled} />);

    const stages = stagesOf();
    expect(stages).toEqual([
      "ADMIT",
      "ADMIT",
      "BIND",
      "BIND",
      "EXECUTE",
      "EXECUTE",
    ]);
    // And within the render, sequence still ascends.
    const sequences = screen
      .getAllByTestId("decision-trace-entry")
      .map((element) => Number(element.dataset.sequence));
    expect(sequences).toEqual([...sequences].sort((a, b) => a - b));
  });

  it("draws all three stages, including one the mission never reached", () => {
    render(<DecisionTrace entries={refusedAtBindTrace()} />);

    expect(screen.getByRole("region", { name: "EXECUTE stage" })).toBeInTheDocument();
    expect(
      screen.getByText(/This mission recorded no EXECUTE event/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/No EXECUTE entry was recorded for this mission/i)).toBeInTheDocument();
  });

  it("states what can happen next from the LAST recorded decision", () => {
    render(<DecisionTrace entries={reachedExecuteTrace()} />);

    const banner = screen.getByText(
      /What can happen next, as of the last recorded decision/i,
    ).parentElement!;
    expect(within(banner).getByText("AWAIT_PROVIDER")).toBeInTheDocument();
  });
});

describe("refused BIND", () => {
  it("renders the refusal with its reason code and invariant id, once expanded", async () => {
    const user = userEvent.setup();
    render(<DecisionTrace entries={refusedAtBindTrace()} />);

    const refused = screen
      .getAllByTestId("decision-trace-entry")
      .find((element) => element.dataset.verdict === "REFUSED")!;
    expect(refused.dataset.stage).toBe("BIND");

    await user.click(within(refused).getByRole("button"));

    expect(within(refused).getByText("BIND_REFUSED_OFFER_CHANGED")).toBeInTheDocument();
    expect(
      within(refused).getByText(
        "binding.selected_offer_version_matches_authoritative_record",
      ),
    ).toBeInTheDocument();
  });

  it("marks the BIND stage as carrying a refusal", () => {
    render(<DecisionTrace entries={refusedAtBindTrace()} />);

    expect(screen.getByText("1 REFUSED")).toBeInTheDocument();
  });
});

describe("advisory risk", () => {
  it("renders RISK_ASSESSED as ADVISORY and never as a decision", async () => {
    const user = userEvent.setup();
    render(<DecisionTrace entries={refusedAtBindTrace()} />);

    const advisory = screen
      .getAllByTestId("decision-trace-entry")
      .find((element) => element.dataset.verdict === "ADVISORY")!;

    expect(within(advisory).getByText("RISK_ASSESSED")).toBeInTheDocument();
    // The word appears twice by design: once as the verdict, once as the
    // standalone marker that says advisory evidence grants no authority.
    expect(within(advisory).getAllByText("ADVISORY")).toHaveLength(2);

    await user.click(within(advisory).getByRole("button"));
    // Once in the collapsed row's chip, once in the expanded "what next".
    expect(within(advisory).getAllByText("NONE").length).toBeGreaterThan(0);
    expect(
      within(advisory).getByText(/grants no authority and changes no policy/i),
    ).toBeInTheDocument();
  });
});

describe("what the trace never shows", () => {
  it("renders no signature, nonce, private key or raw payload", async () => {
    const user = userEvent.setup();
    const { container } = render(<DecisionTrace entries={reachedExecuteTrace()} />);

    for (const button of screen.getAllByRole("button", { expanded: false })) {
      await user.click(button);
    }

    const text = container.textContent ?? "";

    // The words DO appear — in the two disclosures that say the trace carries
    // none of them. So the assertion is that every mention is a denial, which
    // is stronger than banning the vocabulary and then having no way to state
    // the guarantee.
    const mentions = [...text.matchAll(/signature|private key|nonce|key material/gi)];
    expect(mentions.length).toBeGreaterThan(0);
    for (const mention of mentions) {
      const preceding = text.slice(Math.max(0, (mention.index ?? 0) - 60), mention.index);
      expect(preceding, `"${mention[0]}" was not stated as absent`).toMatch(
        /carries no|exposes no|\bno\b/i,
      );
    }

    // And nothing shaped like key material or a signature is rendered at all.
    expect(text).not.toMatch(/[A-Fa-f0-9]{40,}/);
    expect(text).not.toMatch(/-----BEGIN/);
    expect(screen.getAllByText("NOT YET PROVIDED").length).toBeGreaterThan(0);
  });

  it("says the source event recorded nothing, rather than inventing a why", async () => {
    const user = userEvent.setup();
    render(
      <DecisionTrace
        entries={[traceEntry({ event_type: "DISCOVERY_STARTED", evidence: { event_id: "e", sequence: 0, actor: "orchestrator" } })]}
      />,
    );

    await user.click(screen.getByRole("button", { expanded: false }));

    expect(
      screen.getByText(/recorded no reason code, invariant ID, policy outcome or approval scheme/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Nothing is inferred to fill the gap/i)).toBeInTheDocument();
  });
});

describe("empty trace", () => {
  it("explains that empty is an answer, not a mission with no history", () => {
    render(<DecisionTrace entries={[]} />);

    expect(screen.getByText("No decision trace")).toBeInTheDocument();
    expect(screen.getByText(/only after the hash chain verifies/i)).toBeInTheDocument();
    expect(screen.queryAllByTestId("decision-trace-entry")).toHaveLength(0);
  });
});
