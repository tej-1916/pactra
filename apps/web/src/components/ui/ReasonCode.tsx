import { cn } from "@/lib/format";
import { describeReasonCode } from "@/lib/reason-codes";

/**
 * A reason code, printed verbatim, optionally with a readable sentence beside it.
 *
 * The code is never replaced. `AUTHORIZATION_REPLAY_DETECTED` is what the kernel
 * emitted and what an engineer will grep for; the English is an addition, and a
 * code with no description shows as itself rather than acquiring an invented one.
 */
export function ReasonCode({
  code,
  describe = false,
  className,
  expected,
}: {
  code: string | null | undefined;
  describe?: boolean;
  className?: string;
  /** When present and different, the code the correct control should have produced. */
  expected?: string | null;
}) {
  if (!code) {
    return (
      <span className={cn("num text-[12px] text-[color:var(--color-ink-4)]", className)}>
        {expected ? `none observed (expected ${expected})` : "—"}
      </span>
    );
  }
  const description = describe ? describeReasonCode(code) : null;
  const mismatch = expected != null && expected !== code;

  return (
    <span className={cn("inline-flex min-w-0 flex-col gap-1", className)}>
      <span className="flex flex-wrap items-center gap-1.5">
        <code
          className={cn(
            "num rounded border px-1.5 py-[2px] text-[11px] font-semibold",
            mismatch
              ? "border-[color:var(--color-critical)]/40 bg-[color:var(--color-critical)]/10 text-[color:var(--color-critical)]"
              : "border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] text-[color:var(--color-ink)]",
          )}
        >
          {code}
        </code>
        {mismatch ? (
          <span className="num text-[11px] text-[color:var(--color-critical)]">
            expected {expected}
          </span>
        ) : null}
      </span>
      {description ? (
        <span className="max-w-[64ch] text-[12px] leading-relaxed text-[color:var(--color-ink-3)]">
          {description}
        </span>
      ) : null}
    </span>
  );
}
