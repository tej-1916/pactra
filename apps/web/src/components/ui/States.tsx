import type { ReactNode } from "react";
import { AlertTriangle, Inbox, PlugZap, ShieldX, SplitSquareVertical } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * Six states, kept visually distinct because they are six different facts.
 *
 *   LoadingSkeleton  — we are still asking.
 *   EmptyState       — we asked, and nothing exists yet.
 *   UnavailableState — we could not ask. NOT the same as "zero".
 *   ErrorState       — we asked and something went wrong, with a reason code.
 *   RefusalState     — we asked and a CONTROL refused. Not an error: the kernel
 *                      working. Rendered in the secure tone for exactly the
 *                      reason a blocked attack is never red.
 *   PartialDataState — some of the answer arrived and some did not, and the
 *                      screen says which.
 *
 * Plus `NotProvided`, the inline form: this build knows the field exists and
 * the backend does not expose it yet.
 *
 * Collapsing "unavailable" into "empty" is the specific failure this file
 * exists to prevent: a stopped backend must never render as `0 transactions`.
 * Collapsing "refused" into "error" is the second: a refusal is an ANSWER.
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

/**
 * A security refusal.
 *
 * Deliberately NOT red. A refusal is a control holding — the same house rule
 * that keeps a blocked attack out of the critical palette applies here, and a
 * screen that paints every refusal as a failure teaches a reader the system
 * broke when in fact it worked.
 */
export function RefusalState(props: StateProps) {
  return (
    <Frame
      {...props}
      tone="border-[color:var(--color-secure)]/40 bg-[color:var(--color-secure)]/[0.06] text-[color:var(--color-secure)]"
      icon={<ShieldX aria-hidden className="size-4" />}
    />
  );
}

/** Some of the answer arrived and some did not. The screen names which. */
export function PartialDataState(props: StateProps) {
  return (
    <Frame
      {...props}
      tone="border-[color:var(--color-advisory)]/35 bg-[color:var(--color-advisory)]/[0.05] text-[color:var(--color-advisory)]"
      icon={<SplitSquareVertical aria-hidden className="size-4" />}
    />
  );
}

/**
 * An inline slot for a field the backend does not expose yet.
 *
 * The distinction from `—` matters and is the whole reason this exists: an
 * em-dash reads as "this is empty", while this reads as "this build knows the
 * field exists and PACTRA does not provide it at this baseline". Inventing a
 * plausible value, or quietly omitting the row, would both be worse.
 */
export function NotProvided({
  what,
  since,
  className,
}: {
  /** The field, named exactly as the eventual contract will name it. */
  what?: string;
  /** Which phase is expected to populate it, when that is known. */
  since?: string;
  className?: string;
}) {
  const title = [
    what ? `${what} is not part of the current backend read contract.` : "Not provided by the current backend read contract.",
    since ? `Expected from ${since}.` : "",
    "Nothing is inferred or filled in for it.",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span
      title={title}
      className={cn(
        "label-xs inline-flex items-center gap-1 rounded border border-dashed border-[color:var(--color-line-strong)] px-1.5 py-[2px] text-[color:var(--color-ink-4)]",
        className,
      )}
    >
      NOT YET PROVIDED
      {since ? <span className="font-normal normal-case tracking-normal">· {since}</span> : null}
    </span>
  );
}
