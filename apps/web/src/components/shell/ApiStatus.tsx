"use client";

import { useCallback, useEffect, useState } from "react";
import { CircleDot, Loader2, PlugZap } from "lucide-react";

import { cn } from "@/lib/format";
import type { HealthResponse } from "@/lib/types/pactra";

type State =
  | { kind: "checking" }
  | { kind: "up"; health: HealthResponse }
  | { kind: "down"; detail: string };

/**
 * Live API state in the sidebar footer.
 *
 * It polls `/health` because an operator needs to know that the thing they are
 * reading is current. When it is down the label says so in words — the console
 * must never let a stopped backend read as a quiet system.
 *
 * `payment_test_mode` is surfaced here rather than hardcoded: the assertion
 * "TEST MODE" is only worth making if it comes from the process that would
 * otherwise be moving money.
 */
export function ApiStatus() {
  const [state, setState] = useState<State>({ kind: "checking" });

  const check = useCallback(async () => {
    try {
      const response = await fetch("/api/pactra/health", { cache: "no-store" });
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { detail?: string } | null;
        setState({ kind: "down", detail: body?.detail ?? `HTTP ${response.status}` });
        return;
      }
      setState({ kind: "up", health: (await response.json()) as HealthResponse });
    } catch (error) {
      setState({
        kind: "down",
        detail: error instanceof Error ? error.message : "unreachable",
      });
    }
  }, []);

  useEffect(() => {
    // `check` awaits the fetch before it touches state, so nothing is set
    // synchronously here — this is the "subscribe to an external system" case
    // effects exist for. The compiler rule cannot see past the async boundary.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void check();
    const timer = window.setInterval(() => void check(), 15_000);
    return () => window.clearInterval(timer);
  }, [check]);

  return (
    <div className="space-y-2 border-t border-[color:var(--color-line)] px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="label-xs text-[color:var(--color-ink-4)]">PACTRA API</span>
        {state.kind === "checking" ? (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-[color:var(--color-ink-3)]">
            <Loader2 aria-hidden className="size-3 animate-spin" />
            checking
          </span>
        ) : state.kind === "up" ? (
          <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[color:var(--color-secure)]">
            <CircleDot aria-hidden className="size-3" />
            {state.health.status.toUpperCase()}
          </span>
        ) : (
          <span
            className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-[color:var(--color-advisory)]"
            title={state.detail}
          >
            <PlugZap aria-hidden className="size-3" />
            UNAVAILABLE
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <EnvChip
          label="ENV"
          value={state.kind === "up" ? state.health.app_env : "unknown"}
          tone={state.kind === "up" ? "neutral" : "muted"}
        />
        <EnvChip
          label="RAZORPAY"
          value={
            state.kind === "up" ? (state.health.payment_test_mode ? "TEST MODE" : "NOT TEST MODE") : "unknown"
          }
          tone={
            state.kind !== "up" ? "muted" : state.health.payment_test_mode ? "secure" : "critical"
          }
        />
      </div>

      <p className="text-[10.5px] leading-relaxed text-[color:var(--color-ink-4)]">
        {state.kind === "down"
          ? "The console cannot reach the API. Values on this page that require it are marked unavailable, not zero."
          : "No real-money execution. Payments run against the fake provider or Razorpay test mode only."}
      </p>
    </div>
  );
}

function EnvChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "secure" | "critical" | "neutral" | "muted";
}) {
  return (
    <span
      className={cn(
        "num inline-flex items-center gap-1 rounded border px-1.5 py-[2px] text-[10px] font-semibold",
        tone === "secure" &&
          "border-[color:var(--color-secure)]/40 bg-[color:var(--color-secure)]/10 text-[color:var(--color-secure)]",
        tone === "critical" &&
          "border-[color:var(--color-critical)]/40 bg-[color:var(--color-critical)]/10 text-[color:var(--color-critical)]",
        tone === "neutral" &&
          "border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] text-[color:var(--color-ink-2)]",
        tone === "muted" && "border-[color:var(--color-line)] text-[color:var(--color-ink-4)]",
      )}
    >
      <span className="opacity-60">{label}</span>
      {value}
    </span>
  );
}
