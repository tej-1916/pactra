import type { ReactNode } from "react";

import { cn } from "@/lib/format";

export function KeyValueGrid({
  children,
  columns = 2,
  className,
}: {
  children: ReactNode;
  columns?: 1 | 2 | 3;
  className?: string;
}) {
  return (
    <dl
      className={cn(
        "grid gap-x-6 gap-y-3",
        columns === 1 && "grid-cols-1",
        columns === 2 && "grid-cols-1 sm:grid-cols-2",
        columns === 3 && "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3",
        className,
      )}
    >
      {children}
    </dl>
  );
}

export function KeyValue({
  label,
  children,
  hint,
  className,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="label-xs text-[color:var(--color-ink-4)]" title={hint}>
        {label}
      </dt>
      <dd className="mt-1 min-w-0 text-[12.5px] break-words text-[color:var(--color-ink)]">
        {children}
      </dd>
    </div>
  );
}
