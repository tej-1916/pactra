import type { ReactNode } from "react";

import { cn } from "@/lib/format";

interface PanelProps {
  children: ReactNode;
  className?: string;
  /** Renders as a `<section>` with an accessible name when a title is given. */
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Removes body padding — use when the body is a full-bleed table. */
  flush?: boolean;
  id?: string;
}

export function Panel({ children, className, title, subtitle, actions, flush, id }: PanelProps) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={title ? headingId : undefined}
      className={cn(
        "panel overflow-hidden bg-[color:var(--color-surface)]",
        "shadow-[0_1px_0_0_rgba(255,255,255,0.02)_inset,0_18px_36px_-28px_rgba(0,0,0,0.9)]",
        className,
      )}
    >
      {title ? (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--color-line)] px-4 py-3">
          <div className="min-w-0">
            <h2 id={headingId} className="text-[13px] font-semibold tracking-tight text-[color:var(--color-ink)]">
              {title}
            </h2>
            {subtitle ? (
              <p className="mt-1 max-w-[70ch] text-[12px] leading-relaxed text-[color:var(--color-ink-3)]">
                {subtitle}
              </p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn(!flush && "p-4")}>{children}</div>
    </section>
  );
}
