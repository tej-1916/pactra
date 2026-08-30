import type { ReactNode } from "react";

import { cn } from "@/lib/format";
import { TONES, type Tone } from "@/lib/semantics";

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  /**
   * `solid` for a RESULT, `outline` for a SEVERITY or classification.
   *
   * This is the one prop that keeps "SEVERITY: CRITICAL" from reading as
   * "RESULT: FAILED" — see `lib/semantics.ts`.
   */
  variant?: "solid" | "outline";
  icon?: ReactNode;
  className?: string;
  title?: string;
  mono?: boolean;
}

export function Badge({
  children,
  tone = "neutral",
  variant = "solid",
  icon,
  className,
  title,
  mono = false,
}: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded border px-2 py-[3px] text-[11px] font-semibold whitespace-nowrap",
        mono && "num tracking-tight",
        TONES[tone][variant],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}
