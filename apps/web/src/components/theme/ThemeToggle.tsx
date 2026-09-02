"use client";

import { useEffect, useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import { cn } from "@/lib/format";
import {
  getServerThemePreference,
  getThemePreference,
  setThemePreference,
  subscribeToThemePreference,
  type ThemePreference,
} from "@/lib/theme";

const OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/**
 * A three-state control, not a two-state switch.
 *
 * "Follow the OS" is a real preference and collapsing it into a boolean loses
 * it, so `system` is a selectable value here rather than an implicit initial
 * state that the first click destroys.
 *
 * The stored preference is read through `useSyncExternalStore` — see
 * `lib/theme.ts` for why `localStorage` is treated as the external store it is.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const preference = useSyncExternalStore(
    subscribeToThemePreference,
    getThemePreference,
    getServerThemePreference,
  );

  // Keep following the OS while `system` is selected, rather than only at load.
  // This is the genuine "subscribe to an external system" case: the callback
  // writes to the DOM, not to React state.
  useEffect(() => {
    if (preference !== "system") return;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () =>
      document.documentElement.setAttribute("data-theme", query.matches ? "dark" : "light");
    query.addEventListener?.("change", sync);
    return () => query.removeEventListener?.("change", sync);
  }, [preference]);

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-0.5",
        className,
      )}
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const selected = preference === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={`${label} theme`}
            onClick={() => setThemePreference(value)}
            className={cn(
              "inline-flex size-6 items-center justify-center rounded transition-colors",
              selected
                ? "raised bg-[color:var(--color-surface)] text-[color:var(--color-ink)]"
                : "text-[color:var(--color-ink-4)] hover:text-[color:var(--color-ink-2)]",
            )}
          >
            <Icon aria-hidden className="size-3.5" />
          </button>
        );
      })}
    </div>
  );
}
