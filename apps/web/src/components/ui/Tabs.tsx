"use client";

import { useId, useRef, type ReactNode } from "react";

import { cn } from "@/lib/format";

export interface TabDefinition {
  id: string;
  label: string;
  badge?: ReactNode;
}

/**
 * A segmented control implemented as a real ARIA tablist.
 *
 * Arrow keys move between tabs and Home/End jump to the ends, because a console
 * an operator drives from the keyboard should not require a pointer to change
 * view. Panels are rendered by the caller and associated by id.
 */
export function Tabs({
  tabs,
  active,
  onChange,
  className,
  label,
}: {
  tabs: TabDefinition[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
  label: string;
}) {
  const base = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  function onKeyDown(event: React.KeyboardEvent) {
    const index = tabs.findIndex((tab) => tab.id === active);
    if (index < 0) return;
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    const target = tabs[next];
    if (!target) return;
    onChange(target.id);
    refs.current[target.id]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn(
        "flex flex-wrap items-center gap-1 rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-1",
        className,
      )}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              refs.current[tab.id] = node;
            }}
            type="button"
            role="tab"
            id={`${base}-tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`${base}-panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors",
              selected
                ? "bg-[color:var(--color-surface-3)] text-[color:var(--color-ink)] shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset]"
                : "text-[color:var(--color-ink-3)] hover:bg-[color:var(--color-surface-3)]/50 hover:text-[color:var(--color-ink-2)]",
            )}
          >
            {tab.label}
            {tab.badge}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({
  id,
  active,
  children,
}: {
  id: string;
  active: string;
  children: ReactNode;
}) {
  if (id !== active) return null;
  return <div role="tabpanel">{children}</div>;
}
