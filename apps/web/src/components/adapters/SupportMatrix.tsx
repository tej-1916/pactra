import { BookOpen, Check, X } from "lucide-react";

import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { ProtocolStatusBadge } from "@/components/ui/StatusBadges";
import type { ProtocolSupportEntry } from "@/lib/reference";

/**
 * The protocol support matrix, rendered from the exported source of truth.
 *
 * Every row shows what IS supported and what is NOT, side by side and at equal
 * weight. The gaps column is not a footnote: it is the half a reader is most
 * likely to assume away, and the backend keeps it mandatory on every row —
 * including the IMPLEMENTED ones — for exactly that reason.
 *
 * There is no `SUPPORTED` status in this vocabulary. It is the word that lets a
 * claim mean whatever the reader hopes.
 */
export function SupportMatrix({ entries }: { entries: ProtocolSupportEntry[] }) {
  return (
    <Panel
      title="Protocol support matrix"
      subtitle="Exported from services/adapters/support.py, which two backend tests hold the registry and the README to. Code cannot claim more than it holds, and documentation cannot claim more than the code."
      flush
    >
      <div className="divide-y divide-[color:var(--color-line)]">
        {entries.map((entry) => (
          <article key={entry.protocol} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="num text-[13.5px] font-semibold tracking-tight text-[color:var(--color-ink)]">
                  {entry.protocol}
                </h3>
                <p className="mt-1 max-w-[80ch] text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
                  {entry.actualRole}
                </p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <ProtocolStatusBadge status={entry.status} />
                {entry.family ? (
                  <Badge tone="neutral" variant="outline" mono>
                    {entry.family}
                  </Badge>
                ) : (
                  <Badge
                    tone="neutral"
                    variant="outline"
                    title="The family itself is unassigned. Guessing one would be a claim about what this protocol is, made from no source in this repository."
                  >
                    FAMILY UNASSIGNED
                  </Badge>
                )}
                {entry.adapterId ? (
                  <code className="num rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] px-1.5 py-[2px] text-[10.5px] text-[color:var(--color-ink-2)]">
                    {entry.adapterId}
                  </code>
                ) : null}
              </div>
            </div>

            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <div className="rounded border border-[color:var(--color-secure)]/25 bg-[color:var(--color-secure)]/[0.04] p-3">
                <p className="label-xs mb-1.5 flex items-center gap-1.5 text-[color:var(--color-secure)]">
                  <Check aria-hidden className="size-3" />
                  Supported
                </p>
                <p className="text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">
                  {entry.supported}
                </p>
              </div>
              <div className="rounded border border-[color:var(--color-critical)]/25 bg-[color:var(--color-critical)]/[0.04] p-3">
                <p className="label-xs mb-1.5 flex items-center gap-1.5 text-[color:var(--color-critical)]">
                  <X aria-hidden className="size-3" />
                  Not supported
                </p>
                <p className="text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">
                  {entry.notSupported}
                </p>
              </div>
            </div>

            <p className="mt-2.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-4)]">
              <span className="label-xs mr-1.5">Why this status</span>
              {entry.reason}
            </p>

            {entry.specificationSources.length > 0 ? (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="label-xs flex items-center gap-1 text-[color:var(--color-ink-4)]">
                  <BookOpen aria-hidden className="size-3" />
                  Specification read
                </span>
                {entry.specificationSources.map((source) => (
                  <a
                    key={source}
                    href={source}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="num text-[10.5px] text-[color:var(--color-accent)] hover:underline"
                  >
                    {source.replace("https://", "")}
                  </a>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </Panel>
  );
}
