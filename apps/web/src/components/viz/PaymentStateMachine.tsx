import { ArrowRight, CircleDot, Lock } from "lucide-react";

import { cn } from "@/lib/format";
import { PAYMENT_STATE_MEANING, paymentStateTone } from "@/lib/semantics";
import { PAYMENT_STATE_MACHINE } from "@/lib/reference";
import { TONES } from "@/lib/semantics";

/**
 * The real PaymentIntent transition table, drawn.
 *
 * States and edges come from `paymentStateMachine.generated.json`, exported from
 * `ALLOWED_PAYMENT_TRANSITIONS`. No state is invented and no edge is drawn that
 * the state machine does not permit — including the ones whose ABSENCE is the
 * security property: the terminal states have no outgoing transitions at all,
 * which is what stops a delayed webhook from regressing a settled payment.
 */
export function PaymentStateMachineView({ current }: { current?: string | null }) {
  const { states, transitions, terminal, uncertain } = PAYMENT_STATE_MACHINE;

  return (
    <div className="space-y-3">
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {states.map((state) => {
          const tone = paymentStateTone(state);
          const active = current === state;
          const isTerminal = terminal.includes(state);
          const isUncertain = uncertain.includes(state);
          const outgoing = transitions[state] ?? [];

          return (
            <li
              key={state}
              className={cn(
                "relative flex min-w-0 flex-col gap-1.5 rounded-lg border px-3 py-2.5",
                active
                  ? cn(TONES[tone].solid, "ring-1 ring-current/40")
                  : "border-[color:var(--color-line)] bg-[color:var(--color-surface-2)]",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                {active ? <CircleDot aria-hidden className="size-3.5" /> : null}
                <span
                  className={cn(
                    "num text-[11.5px] font-semibold",
                    active ? "" : TONES[tone].text,
                  )}
                >
                  {state}
                </span>
                {isTerminal ? (
                  <span className="inline-flex items-center gap-1 rounded border border-[color:var(--color-line-strong)] px-1 py-[1px] text-[9px] font-semibold text-[color:var(--color-ink-4)]">
                    <Lock aria-hidden className="size-2.5" />
                    TERMINAL
                  </span>
                ) : null}
                {isUncertain ? (
                  <span className="rounded border border-[color:var(--color-advisory)]/40 px-1 py-[1px] text-[9px] font-semibold text-[color:var(--color-advisory)]">
                    UNCERTAIN
                  </span>
                ) : null}
                {active ? (
                  <span className="label-xs ml-auto opacity-80">CURRENT</span>
                ) : null}
              </div>

              <p
                className={cn(
                  "text-[11px] leading-relaxed",
                  active ? "opacity-90" : "text-[color:var(--color-ink-4)]",
                )}
              >
                {PAYMENT_STATE_MEANING[state]}
              </p>

              <div className="flex flex-wrap items-center gap-1 pt-0.5">
                {outgoing.length === 0 ? (
                  <span className="text-[10px] text-[color:var(--color-ink-4)]">
                    no outgoing transitions — absorbing by construction
                  </span>
                ) : (
                  outgoing.map((target) => (
                    <span
                      key={target}
                      className="num inline-flex items-center gap-0.5 text-[10px] text-[color:var(--color-ink-4)]"
                    >
                      <ArrowRight aria-hidden className="size-2.5" />
                      {target}
                    </span>
                  ))
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <p className="text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
        Transitions are read from{" "}
        <code className="num">services/payment_executor/state_machine.py</code>. Two properties are
        structural rather than incidental: a delayed webhook cannot regress a settled payment
        because terminal states have no outgoing edge, and an out-of-order webhook cannot drive an
        illegal transition because the table — not the arrival order and not the provider&apos;s own
        opinion — decides what is reachable.
      </p>
    </div>
  );
}
