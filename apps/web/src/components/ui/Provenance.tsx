import type { ReactNode } from "react";
import { AlertTriangle, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/format";
import { RESERVED_AUTHORITATIVE_HEADINGS, sanitizeDisplayString } from "@/lib/tainted";

/**
 * The two ways a value may appear on this console, and they must never be
 * confused for one another.
 *
 *   `Authoritative`  a machine value the kernel computed or the registry owns.
 *                    It may sit under TOTAL, PAYEE, POLICY, AUTHORIZATION or
 *                    PAYMENT STATE. Set in the mono face, at full ink.
 *   `TaintedText`    merchant-supplied or registry DISPLAY data. Sanitized,
 *                    bidi-isolated, marked, and never given one of those
 *                    headings.
 *
 * The visual separation is carried by four independent signals, not one: the
 * typeface (mono vs. text), the ink weight, an explicit marker, and a dotted
 * left rule in the taint colour. Colour alone would fail for a reader who
 * cannot see it, which on this screen is a security failure and not merely an
 * accessibility one.
 */

export function Authoritative({
  children,
  className,
  title,
  mono = true,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
  mono?: boolean;
}) {
  return (
    <span
      data-provenance="authoritative"
      title={title}
      className={cn(
        "text-[color:var(--color-ink)]",
        mono && "num",
        className,
      )}
    >
      {children}
    </span>
  );
}

/**
 * An authoritative value under a reserved heading.
 *
 * The heading is constrained to the reserved set precisely so this component
 * cannot be reached for by accident when the value is merchant text. There is
 * deliberately no `TaintedField` counterpart that accepts one.
 */
export function AuthoritativeField({
  heading,
  value,
  source,
  className,
}: {
  heading: (typeof RESERVED_AUTHORITATIVE_HEADINGS)[number];
  value: ReactNode;
  /** Where the value came from. Always stated; never guessed. */
  source: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2.5",
        className,
      )}
    >
      <div className="flex items-center gap-1.5">
        <ShieldCheck aria-hidden className="size-3 text-[color:var(--color-secure)]" />
        <span className="label-xs text-[color:var(--color-ink-3)]">{heading}</span>
      </div>
      <div className="num mt-1.5 text-[15px] leading-tight font-semibold text-[color:var(--color-ink)]">
        {value}
      </div>
      <p className="mt-1 text-[10.5px] leading-snug text-[color:var(--color-ink-4)]">{source}</p>
    </div>
  );
}

/**
 * A merchant-controlled string, rendered so it cannot pretend to be anything
 * else.
 *
 * `<bdi>` with an explicit `dir` is the load-bearing part: it isolates the
 * string's bidirectional context so that even a payload this component failed
 * to fully sanitize cannot reorder the text around it. The sanitizer removes
 * the formatting characters; the isolation contains whatever it missed.
 *
 * Anything the sanitizer found is SHOWN. A silently cleaned string is a string
 * whose attack nobody ever saw, so the marker changes and the findings are
 * available on the element itself.
 */
export function TaintedText({
  value,
  label = "Merchant text",
  className,
  showMarker = true,
}: {
  value: string | null | undefined;
  /** What this string is. Never a reserved authoritative heading. */
  label?: string;
  className?: string;
  showMarker?: boolean;
}) {
  const sanitized = sanitizeDisplayString(value);

  if (value === null || value === undefined || sanitized.originalLength === 0) {
    return (
      <span className="text-[color:var(--color-ink-4)]" data-provenance="tainted">
        —
      </span>
    );
  }

  const findingSummary = sanitized.findings.map((finding) => finding.detail).join(" ");

  return (
    <span
      data-provenance="tainted"
      data-suspicious={sanitized.suspicious ? "true" : "false"}
      className={cn(
        "inline-flex max-w-full min-w-0 items-baseline gap-1.5 border-l-2 border-dotted pl-2",
        sanitized.suspicious
          ? "border-[color:var(--color-critical)]"
          : "border-[color:var(--color-taint)]",
        className,
      )}
    >
      {showMarker ? (
        <span
          className={cn(
            "label-xs shrink-0 translate-y-[-1px]",
            sanitized.suspicious
              ? "text-[color:var(--color-critical)]"
              : "text-[color:var(--color-taint)]",
          )}
          title={`${label} — merchant-controlled display data. Not authoritative for amount, payee, policy, authorization or payment state.`}
        >
          {sanitized.suspicious ? (
            <AlertTriangle aria-hidden className="inline size-3 align-[-1px]" />
          ) : null}{" "}
          {label}
        </span>
      ) : null}
      {/* Isolated so a formatting character this sanitizer did not know about
          still cannot reorder the fields beside it. */}
      <bdi dir="ltr" className="min-w-0 truncate text-[color:var(--color-ink-2)]">
        {sanitized.text ||
          "(nothing displayable — the value was entirely formatting characters)"}
      </bdi>
      {sanitized.suspicious ? (
        <span className="sr-only">
          Warning: {findingSummary}
        </span>
      ) : null}
    </span>
  );
}

/** The findings themselves, when a surface has room to state them in full. */
export function TaintFindings({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  const { findings } = sanitizeDisplayString(value);
  if (findings.length === 0) return null;
  return (
    <ul className={cn("mt-1.5 space-y-1", className)}>
      {findings.map((finding) => (
        <li
          key={finding.code}
          className="flex items-start gap-1.5 text-[11px] leading-snug text-[color:var(--color-critical)]"
        >
          <AlertTriangle aria-hidden className="mt-[2px] size-3 shrink-0" />
          <span>
            <code className="num">{finding.code}</code> — {finding.detail}
          </span>
        </li>
      ))}
    </ul>
  );
}
