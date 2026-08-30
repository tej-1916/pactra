import type { ReactNode } from "react";

import { cn } from "@/lib/format";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {eyebrow ? (
          <p className="label-xs mb-1.5 text-[color:var(--color-accent)]">{eyebrow}</p>
        ) : null}
        <h1 className="text-[22px] leading-tight font-semibold tracking-tight text-[color:var(--color-ink)]">
          {title}
        </h1>
        {description ? (
          <div className="mt-1.5 max-w-[92ch] text-[13px] leading-relaxed text-[color:var(--color-ink-3)]">
            {description}
          </div>
        ) : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
