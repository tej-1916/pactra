import { ArrowDown, CircleHelp, ShieldCheck } from "lucide-react";

import { Panel } from "@/components/ui/Panel";
import { cn } from "@/lib/format";

const STEPS = [
  {
    label: "Provider creates payment P123",
    note: "The provider does its work. The money side of the call may well have succeeded.",
    tone: "neutral" as const,
  },
  {
    label: "The response is lost",
    note: "A timeout is not evidence about whether a payment was created. It is the absence of evidence.",
    tone: "critical" as const,
  },
  {
    label: "PACTRA becomes UNCERTAIN",
    note: "PROVIDER_PENDING is one state, not two. There is no observation that distinguishes 'timeout before create' from 'timeout after create', so encoding a guess as a state would be encoding a lie.",
    tone: "advisory" as const,
  },
  {
    label: "Lookup / reconciliation",
    note: "The payment the provider may hold is findable by the idempotency key PACTRA already has — the same key it sent. That correlation is what makes a lost response recoverable.",
    tone: "accent" as const,
  },
  {
    label: "The original P123 is recovered",
    note: "The held intent is reconciled against the provider's own record. Nothing new is created.",
    tone: "secure" as const,
  },
  {
    label: "NO DUPLICATE PAYMENT",
    note: "Re-creating blindly would risk charging twice. FAILED_RETRYABLE is reachable from the uncertain state through exactly one route: a provider that positively reports holding no payment for the key.",
    tone: "secure" as const,
  },
];

/**
 * The timeout-after-create story, told as a sequence.
 *
 * This is the strongest engineering claim in the payment layer and it is easy to
 * state badly, so it is drawn as what actually happens rather than summarized as
 * "we handle retries". The honest boundary is stated at the bottom: this rests on
 * the provider answering truthfully (KL-06), and a provider that creates a
 * payment and then denies holding it can induce a duplicate. That is a boundary
 * of what any client-side protocol can guarantee, not a defect PACTRA can close.
 */
export function TimeoutAfterCreate() {
  return (
    <Panel
      title="Provider timeout after create"
      subtitle="What happens when PACTRA asks a provider to move money and never learns whether it did."
    >
      <ol className="space-y-0">
        {STEPS.map((step, index) => (
          <li key={step.label} className="relative flex gap-3 pb-3 last:pb-0">
            {index < STEPS.length - 1 ? (
              <span
                aria-hidden
                className="absolute top-7 bottom-0 left-[13px] w-[1.5px] bg-[color:var(--color-line)]"
              />
            ) : null}
            <span
              className={cn(
                "relative z-10 mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold",
                step.tone === "secure" &&
                  "border-[color:var(--color-secure)]/45 bg-[color:var(--color-secure)]/10 text-[color:var(--color-secure)]",
                step.tone === "advisory" &&
                  "border-[color:var(--color-advisory)]/45 bg-[color:var(--color-advisory)]/10 text-[color:var(--color-advisory)]",
                step.tone === "critical" &&
                  "border-[color:var(--color-critical)]/45 bg-[color:var(--color-critical)]/10 text-[color:var(--color-critical)]",
                step.tone === "accent" &&
                  "border-[color:var(--color-accent)]/45 bg-[color:var(--color-accent)]/10 text-[color:var(--color-accent)]",
                step.tone === "neutral" &&
                  "border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] text-[color:var(--color-ink-3)]",
              )}
            >
              {step.tone === "advisory" ? (
                <CircleHelp aria-hidden className="size-3.5" />
              ) : step.label.startsWith("NO DUPLICATE") ? (
                <ShieldCheck aria-hidden className="size-3.5" />
              ) : (
                index + 1
              )}
            </span>
            <div className="min-w-0 pb-1">
              <p
                className={cn(
                  "text-[12.5px] font-semibold tracking-tight",
                  step.tone === "secure"
                    ? "text-[color:var(--color-secure)]"
                    : "text-[color:var(--color-ink)]",
                )}
              >
                {step.label}
              </p>
              <p className="mt-1 max-w-[86ch] text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
                {step.note}
              </p>
            </div>
          </li>
        ))}
      </ol>

      <p className="mt-3 flex gap-2 border-t border-[color:var(--color-line)] pt-3 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
        <ArrowDown aria-hidden className="mt-[2px] size-3 shrink-0" />
        <span>
          <strong className="text-[color:var(--color-advisory)]">KL-06, stated rather than omitted:</strong>{" "}
          this rests on the provider answering truthfully. A provider that creates a payment and then
          denies holding it can induce a duplicate — measured directly in the attack lab with a lying
          provider substituted. That is a boundary of what any client-side protocol can guarantee.
        </span>
      </p>
    </Panel>
  );
}
