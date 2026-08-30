import { cn } from "@/lib/format";
import { redact } from "@/lib/redaction";

/**
 * Renders a scenario's machine-readable evidence.
 *
 * "blocked: true" with `payment_intents_after == payment_intents_before` beside
 * it is a claim with something behind it. "blocked: true" alone is not. So the
 * observed-effects map is shown in full rather than summarized, with the pairs
 * that come in `_before` / `_after` form lifted into an explicit comparison.
 *
 * Values pass through `redact` first. The harness is built to put no secret in
 * this map; this is the belt to that braces.
 */
export function EvidenceTable({
  effects,
  className,
}: {
  effects: Record<string, unknown>;
  className?: string;
}) {
  const safe = redact(effects) as Record<string, unknown>;
  const entries = Object.entries(safe);

  if (entries.length === 0) {
    return (
      <p className={cn("text-[12px] text-[color:var(--color-ink-4)]", className)}>
        This scenario recorded no machine-readable effects.
      </p>
    );
  }

  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full min-w-[320px] border-collapse text-left">
        <caption className="sr-only">Observed effects recorded by the scenario</caption>
        <thead>
          <tr className="border-b border-[color:var(--color-line)]">
            <th scope="col" className="label-xs px-3 py-2 text-[color:var(--color-ink-4)]">
              Observation
            </th>
            <th scope="col" className="label-xs px-3 py-2 text-[color:var(--color-ink-4)]">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, value]) => (
            <tr
              key={key}
              className="border-b border-[color:var(--color-line)]/60 last:border-b-0"
            >
              <th
                scope="row"
                className="num px-3 py-1.5 align-top text-[11.5px] font-normal text-[color:var(--color-ink-2)]"
              >
                {key}
              </th>
              <td className="px-3 py-1.5 align-top">
                <EvidenceValue value={value} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceValue({ value }: { value: unknown }) {
  if (typeof value === "boolean") {
    return (
      <span
        className={cn(
          "num text-[11.5px] font-semibold",
          value ? "text-[color:var(--color-secure)]" : "text-[color:var(--color-ink-3)]",
        )}
      >
        {String(value)}
      </span>
    );
  }
  if (value === null || value === undefined) {
    return <span className="num text-[11.5px] text-[color:var(--color-ink-4)]">null</span>;
  }
  if (Array.isArray(value)) {
    return (
      <span className="num block max-w-[46ch] text-[11.5px] break-all text-[color:var(--color-ink)]">
        {value.length === 0 ? "[]" : JSON.stringify(value)}
      </span>
    );
  }
  if (typeof value === "object") {
    return (
      <pre className="num max-w-[52ch] overflow-x-auto text-[11px] whitespace-pre-wrap text-[color:var(--color-ink)]">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }
  return (
    <span className="num block max-w-[46ch] text-[11.5px] break-all text-[color:var(--color-ink)]">
      {String(value)}
    </span>
  );
}
