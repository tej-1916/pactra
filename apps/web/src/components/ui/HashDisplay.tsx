"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

import { cn, truncateHash } from "@/lib/format";

/**
 * A hash, elided for the eye and complete for the clipboard.
 *
 * Chain verification is about comparing exact 64-hex values, so the full string
 * must always be recoverable — truncation is a display concern and must never
 * become a data-loss one. The full value also lives in `title` so it is
 * reachable without a clipboard API.
 */
export function HashDisplay({
  value,
  head = 10,
  tail = 6,
  label,
  className,
  tone = "neutral",
}: {
  value: string | null | undefined;
  head?: number;
  tail?: number;
  label?: string;
  className?: string;
  tone?: "neutral" | "secure" | "critical";
}) {
  const [copied, setCopied] = useState(false);

  if (!value) {
    return <span className={cn("num text-[12px] text-[color:var(--color-ink-4)]", className)}>—</span>;
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(value ?? "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard access can be denied. The full value is in `title` regardless,
      // so failing silently here costs the reader nothing.
    }
  }

  const toneClass =
    tone === "secure"
      ? "text-[color:var(--color-secure)]"
      : tone === "critical"
        ? "text-[color:var(--color-critical)]"
        : "text-[color:var(--color-ink-2)]";

  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      {label ? (
        <span className="label-xs text-[color:var(--color-ink-4)]">{label}</span>
      ) : null}
      <code className={cn("num text-[11.5px]", toneClass)} title={value}>
        {truncateHash(value, head, tail)}
      </code>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Copied to clipboard" : `Copy ${label ?? "value"} to clipboard`}
        className="rounded p-0.5 text-[color:var(--color-ink-4)] transition-colors hover:text-[color:var(--color-ink)]"
      >
        {copied ? (
          <Check aria-hidden className="size-3 text-[color:var(--color-secure)]" />
        ) : (
          <Copy aria-hidden className="size-3" />
        )}
      </button>
    </span>
  );
}
