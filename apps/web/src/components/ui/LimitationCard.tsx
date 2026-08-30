import { BookLock } from "lucide-react";

import { Badge } from "./Badge";
import { cn } from "@/lib/format";

/**
 * A documented boundary of what the system claims. Not a defect, and styled so.
 *
 * A finding is something that should be fixed; a known limitation is something
 * the current design cannot do and does not claim to do. Rendering the two the
 * same way would make honest disclosure look like breakage — so this card is
 * calm and structural, and the security-finding surfaces are the loud ones.
 */
export function LimitationCard({
  id,
  title,
  detail,
  demonstratedBy,
  register,
  className,
}: {
  id: string;
  title: string;
  detail: string;
  demonstratedBy?: string | null;
  /** Which register this came from. The three are deliberately not merged. */
  register: "SECURITY CONTRACT" | "RISK MEASUREMENT" | "INTEGRATION SURFACE";
  className?: string;
}) {
  return (
    <article
      className={cn(
        "panel flex flex-col gap-2 bg-[color:var(--color-surface)] p-4",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="advisory" variant="outline" icon={<BookLock aria-hidden className="size-3.5" />}>
          KNOWN LIMITATION
        </Badge>
        <Badge tone="neutral" variant="outline">
          {register}
        </Badge>
        <code className="num text-[11px] text-[color:var(--color-ink-4)]">{id}</code>
      </div>
      <h3 className="text-[13px] font-semibold tracking-tight text-[color:var(--color-ink)]">
        {title}
      </h3>
      <p className="max-w-[86ch] text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
        {detail}
      </p>
      {demonstratedBy ? (
        <p className="text-[11.5px] text-[color:var(--color-ink-4)]">
          Demonstrated by scenario{" "}
          <code className="num text-[color:var(--color-ink-3)]">{demonstratedBy}</code>
        </p>
      ) : null}
    </article>
  );
}
