import { Panel } from "@/components/ui/Panel";
import { cn, count, percent } from "@/lib/format";
import type { CategoryMetric } from "@/lib/types/benchmark";

/**
 * Per-category results.
 *
 * `BENIGN_CONTROL` and `KNOWN_LIMITATION` deliberately do NOT get a block-rate
 * bar. A control's block rate of 0% is a pass, and drawing it on the same axis
 * as a hostile category's 100% would put the best possible outcome and the worst
 * possible outcome at opposite ends of the same scale.
 */
export function CategoryBreakdown({ categories }: { categories: CategoryMetric[] }) {
  return (
    <Panel
      title="Adversarial coverage by category"
      subtitle="Hostile categories are scored by block rate; controls and documented limitations are scored differently and are shown as counts."
      flush
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-left">
          <thead>
            <tr className="border-b border-[color:var(--color-line)]">
              <Th className="pl-4">Category</Th>
              <Th className="text-right">Runs</Th>
              <Th className="text-right">Blocked</Th>
              <Th className="text-right">Not blocked</Th>
              <Th className="text-right">Err / Inc</Th>
              <Th className="w-[210px] pr-4">Outcome</Th>
            </tr>
          </thead>
          <tbody>
            {categories.map((row) => {
              const scored = row.category !== "BENIGN_CONTROL" && row.category !== "KNOWN_LIMITATION";
              const healthy = scored ? row.not_blocked === 0 : row.blocked === 0;
              return (
                <tr
                  key={row.category}
                  className="border-b border-[color:var(--color-line)]/60 last:border-b-0"
                >
                  <td className="num py-2 pl-4 text-[12px] font-medium text-[color:var(--color-ink)]">
                    {row.category}
                  </td>
                  <Td>{count(row.runs)}</Td>
                  <Td>{count(row.blocked)}</Td>
                  <Td
                    className={
                      scored && row.not_blocked > 0 ? "text-[color:var(--color-critical)]" : undefined
                    }
                  >
                    {count(row.not_blocked)}
                  </Td>
                  <Td
                    className={
                      row.errors > 0 ? "text-[color:var(--color-critical)]" : undefined
                    }
                  >
                    {count(row.errors)} / {count(row.inconclusive)}
                  </Td>
                  <td className="py-2 pr-4">
                    {scored ? (
                      <div className="flex items-center gap-2">
                        <div
                          className="h-1.5 min-w-[90px] flex-1 overflow-hidden rounded-full bg-[color:var(--color-surface-3)]"
                          role="img"
                          aria-label={`Block rate ${percent(row.block_rate)}`}
                        >
                          <div
                            className={cn(
                              "h-full rounded-full",
                              healthy
                                ? "bg-[color:var(--color-secure)]"
                                : "bg-[color:var(--color-critical)]",
                            )}
                            style={{ width: `${Math.round((row.block_rate ?? 0) * 100)}%` }}
                          />
                        </div>
                        <span
                          className={cn(
                            "num w-[52px] shrink-0 text-right text-[11.5px] font-semibold",
                            healthy
                              ? "text-[color:var(--color-secure)]"
                              : "text-[color:var(--color-critical)]",
                          )}
                        >
                          {percent(row.block_rate, 0)}
                        </span>
                      </div>
                    ) : (
                      <span className="text-[11.5px] text-[color:var(--color-ink-4)]">
                        {row.category === "BENIGN_CONTROL"
                          ? healthy
                            ? "all controls allowed — as required"
                            : "a control was refused"
                          : "demonstrated boundary — not scored"}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th scope="col" className={cn("label-xs py-2 pr-3 text-[color:var(--color-ink-4)]", className)}>
      {children}
    </th>
  );
}

function Td({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <td className={cn("num py-2 pr-3 text-right text-[12px] text-[color:var(--color-ink-2)]", className)}>
      {children}
    </td>
  );
}
