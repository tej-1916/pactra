import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Whole-rupee amounts, as PACTRA stores them. No fractional paise anywhere. */
export function inr(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "—";
  return `₹${amount.toLocaleString("en-IN")}`;
}

/**
 * A rate, or `n/a` when there was no denominator.
 *
 * `null` from the harness means nothing was measured. Formatting that as 0.0%
 * or 100.0% would turn an absence of evidence into a claim, which is the one
 * thing the reporting layer is built to prevent.
 */
export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

export function ms(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "n/a";
  return `${value.toFixed(digits)} ms`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN");
}

export function timestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

/** Middle-elided hash, for a table cell. The full value stays copyable. */
export function truncateHash(hash: string | null | undefined, head = 10, tail = 6): string {
  if (!hash) return "—";
  if (hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

export function shortId(id: string | null | undefined, head = 8): string {
  if (!id) return "—";
  return id.length <= head ? id : `${id.slice(0, head)}…`;
}

/** Turn `AUTHORIZATION_REPLAY_DETECTED` into `Authorization replay detected`. */
export function humanizeCode(code: string): string {
  const lower = code.toLowerCase().replace(/_/g, " ");
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
