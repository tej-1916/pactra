import type { ReactNode } from "react";

import { cn } from "@/lib/format";
import { TONES, type Tone } from "@/lib/semantics";

/**
 * One number, with the thing it was divided by beside it.
 *
 * `denominator` is not decoration: a block rate over three runs must not look
 * like one over four hundred and seventy, and the only way to stop that is to
 * print the counts next to the rate every time.
 */
export function MetricCard({
  label,
  value,
  denominator,
  tone = "neutral",
  hint,
  icon,
  className,
}: {
  label: string;
  value: ReactNode;
  denominator?: ReactNode;
  tone?: Tone;
  hint?: string;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "panel flex min-w-0 flex-col gap-1 px-3.5 py-3",
        "bg-[color:var(--color-surface)]",
        className,
      )}
      title={hint}
    >
      <div className="flex items-center gap-1.5">
        {icon ? <span className={TONES[tone].text}>{icon}</span> : null}
        <span className="label-xs text-[color:var(--color-ink-4)]">{label}</span>
      </div>
      <div className={cn("num text-[22px] leading-none font-semibold tracking-tight", TONES[tone].text)}>
        {value}
      </div>
      {denominator ? (
        <div className="num text-[11px] text-[color:var(--color-ink-4)]">{denominator}</div>
      ) : null}
    </div>
  );
}
