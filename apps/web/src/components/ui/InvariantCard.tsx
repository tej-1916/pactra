import { ArrowRight, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * One line of the test contract, rendered as the implication it is.
 *
 * The contract is written as `PRECONDITION → CONSEQUENCE`, and splitting on the
 * arrow keeps that shape visible rather than flattening it into a sentence. The
 * strings come from `vocabulary.generated.json`, parsed out of the README block
 * that publishes them, so this component cannot claim an invariant the project
 * does not.
 */
export function InvariantCard({
  invariant,
  className,
  compact = false,
}: {
  invariant: string;
  className?: string;
  compact?: boolean;
}) {
  const [precondition, consequence] = splitInvariant(invariant);

  return (
    <div
      className={cn(
        "panel group relative flex min-w-0 flex-col justify-center gap-1.5 overflow-hidden bg-[color:var(--color-surface)] px-3.5",
        compact ? "py-2.5" : "py-3.5",
        className,
      )}
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-0 w-[2px] bg-[color:var(--color-secure)]/60"
      />
      <div className="flex items-start gap-2">
        <ShieldCheck aria-hidden className="mt-[1px] size-3.5 shrink-0 text-[color:var(--color-secure)]" />
        <p className="num text-[11.5px] leading-snug font-semibold tracking-tight text-[color:var(--color-ink)]">
          {precondition}
        </p>
      </div>
      {consequence ? (
        <div className="flex items-start gap-2 pl-[22px]">
          <ArrowRight aria-hidden className="mt-[1px] size-3 shrink-0 text-[color:var(--color-secure)]" />
          <p className="num text-[11.5px] leading-snug font-semibold tracking-tight text-[color:var(--color-secure)]">
            {consequence}
          </p>
        </div>
      ) : null}
    </div>
  );
}

/** Handles both the `→` used in the README and the ASCII `->` used in scenarios. */
export function splitInvariant(invariant: string): [string, string | null] {
  const parts = invariant.split(/\s*(?:→|->)\s*/);
  if (parts.length < 2) return [invariant, null];
  return [parts[0] ?? invariant, parts.slice(1).join(" → ")];
}
