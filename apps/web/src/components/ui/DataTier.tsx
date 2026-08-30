import type { ReactNode } from "react";
import { Database, FlaskConical, Radio } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * Says where a number came from, on the surface that renders it.
 *
 * The console draws on three sources that must never be confused, and the whole
 * of this file exists to keep them apart on screen:
 *
 *   LIVE RUNTIME     read from the PACTRA API just now. Real system state.
 *   GENERATED        derived from backend SOURCE by `export_reference.py`.
 *                    A declaration — what the system says about itself.
 *   DEV BENCHMARK    a recorded harness run. Evidence about a past measurement,
 *                    NOT runtime health. `1272 tests` and `130/130 blocked`
 *                    belong here and nowhere else.
 */

export type DataTier = "live" | "generated" | "benchmark";

const TIER_META: Record<
  DataTier,
  { label: string; icon: ReactNode; className: string; hint: string }
> = {
  live: {
    label: "LIVE RUNTIME",
    icon: <Radio aria-hidden className="size-3" />,
    className:
      "border-[color:var(--color-secure)]/35 bg-[color:var(--color-secure)]/[0.07] text-[color:var(--color-secure)]",
    hint: "Read from the PACTRA API for this request. Real system state.",
  },
  generated: {
    label: "GENERATED FROM SOURCE",
    icon: <Database aria-hidden className="size-3" />,
    className:
      "border-[color:var(--color-accent)]/35 bg-[color:var(--color-accent)]/[0.07] text-[color:var(--color-accent)]",
    hint: "Exported from backend source by apps/web/scripts/export_reference.py. A declaration, not a measurement.",
  },
  benchmark: {
    label: "LAST VERIFIED DEVELOPMENT BENCHMARK",
    icon: <FlaskConical aria-hidden className="size-3" />,
    className:
      "border-[color:var(--color-advisory)]/35 bg-[color:var(--color-advisory)]/[0.07] text-[color:var(--color-advisory)]",
    hint: "A recorded harness run from development. Evidence about a past measurement — not runtime system health.",
  },
};

export function DataTierBadge({
  tier,
  detail,
  className,
}: {
  tier: DataTier;
  detail?: ReactNode;
  className?: string;
}) {
  const meta = TIER_META[tier];
  return (
    <span
      title={meta.hint}
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-[3px] text-[10px] font-semibold tracking-[0.08em] uppercase",
        meta.className,
        className,
      )}
    >
      {meta.icon}
      {meta.label}
      {detail ? (
        <span className="num font-normal normal-case tracking-normal opacity-80">· {detail}</span>
      ) : null}
    </span>
  );
}
