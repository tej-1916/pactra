import type { ReactNode } from "react";
import { cn } from "@/lib/format";

/**
 * PACTRA Glassmorphism Component Primitives — Phase 1 Design Foundation
 *
 * Glass surface rules:
 * - Use backdrop-filter: blur(12px) with translucent background
 * - Soft highlight border (rgba(255,255,255,0.72) light / rgba(255,255,255,0.08) dark)
 * - Subtle elevation shadow
 * - Reserved for structural hierarchy emphasis (hero containers, active pipeline rail, floating control bars).
 */

export function GlassPanel({
  children,
  className,
  elevated = false,
}: {
  children: ReactNode;
  className?: string;
  elevated?: boolean;
}) {
  return (
    <div
      className={cn(
        "relative rounded-xl border border-[color:var(--color-line)] bg-[color:var(--pactra-surface)] p-6 backdrop-blur-md transition-all duration-200",
        "supports-[backdrop-filter]:bg-[color:var(--color-surface)]/80",
        elevated
          ? "shadow-[0_12px_32px_-16px_rgba(12,18,32,0.15)] dark:shadow-[0_12px_32px_-16px_rgba(0,0,0,0.5)]"
          : "shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function GlassCard({
  children,
  className,
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface)]/90 p-4 backdrop-blur-sm transition-all duration-150",
        interactive &&
          "hover:border-[color:var(--color-accent)]/50 hover:bg-[color:var(--color-surface)] hover:shadow-md",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function GlassBadge({
  children,
  className,
  variant = "neutral",
}: {
  children: ReactNode;
  className?: string;
  variant?: "neutral" | "accent" | "secure" | "critical" | "advisory";
}) {
  const variantStyles = {
    neutral:
      "bg-[color:var(--color-surface-2)]/80 text-[color:var(--color-ink-2)] border-[color:var(--color-line)]",
    accent:
      "bg-[color:var(--color-accent-dim)]/80 text-[color:var(--color-accent)] border-[color:var(--color-accent)]/30",
    secure:
      "bg-[color:var(--color-secure)]/10 text-[color:var(--color-secure)] border-[color:var(--color-secure)]/30",
    critical:
      "bg-[color:var(--color-critical)]/10 text-[color:var(--color-critical)] border-[color:var(--color-critical)]/30",
    advisory:
      "bg-[color:var(--color-advisory)]/10 text-[color:var(--color-advisory)] border-[color:var(--color-advisory)]/30",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium backdrop-blur-xs",
        variantStyles[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
