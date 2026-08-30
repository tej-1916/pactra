import type { ReactNode } from "react";
import { AlertTriangle, Inbox, PlugZap } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * Four states, kept visually distinct because they are four different facts.
 *
 *   LoadingSkeleton  — we are still asking.
 *   EmptyState       — we asked, and nothing exists yet.
 *   UnavailableState — we could not ask. NOT the same as "zero".
 *   ErrorState       — we asked and were refused, with a reason code.
 *
 * Collapsing "unavailable" into "empty" is the specific failure this file
 * exists to prevent: a stopped backend must never render as `0 transactions`.
 */

export function LoadingSkeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          aria-hidden
          className="h-9 rounded border border-[color:var(--color-line)] bg-[linear-gradient(90deg,var(--color-surface-2)_0%,var(--color-surface-3)_50%,var(--color-surface-2)_100%)] bg-[length:420px_100%] [animation:pactra-shimmer_1.4s_linear_infinite]"
        />
      ))}
    </div>
  );
}

interface StateProps {
  title: string;
  detail: ReactNode;
  action?: ReactNode;
  className?: string;
}

function Frame({
  icon,
  title,
  detail,
  action,
  tone,
  className,
}: StateProps & { icon: ReactNode; tone: string }) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-2 rounded border border-dashed px-4 py-5",
        tone,
        className,
      )}
    >
      <div className="flex items-center gap-2">
        {icon}
        <p className="text-[13px] font-semibold">{title}</p>
      </div>
      <div className="max-w-[78ch] text-[12px] leading-relaxed text-[color:var(--color-ink-3)]">
        {detail}
      </div>
      {action}
    </div>
  );
}

export function EmptyState(props: StateProps) {
  return (
    <Frame
      {...props}
      tone="border-[color:var(--color-line)] bg-[color:var(--color-surface-2)]/40 text-[color:var(--color-ink-2)]"
      icon={<Inbox aria-hidden className="size-4 text-[color:var(--color-ink-3)]" />}
    />
  );
}

export function UnavailableState(props: StateProps) {
  return (
    <Frame
      {...props}
      tone="border-[color:var(--color-advisory)]/35 bg-[color:var(--color-advisory)]/[0.05] text-[color:var(--color-advisory)]"
      icon={<PlugZap aria-hidden className="size-4" />}
    />
  );
}

export function ErrorState(props: StateProps) {
  return (
    <Frame
      {...props}
      tone="border-[color:var(--color-critical)]/35 bg-[color:var(--color-critical)]/[0.05] text-[color:var(--color-critical)]"
      icon={<AlertTriangle aria-hidden className="size-4" />}
    />
  );
}
