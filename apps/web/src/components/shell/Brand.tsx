import { cn } from "@/lib/format";

/** The kernel mark: a boundary with something contained inside it. */
export function PactraMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden
      className={cn("size-7", className)}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path
        d="M16 2.6 27.2 7.4v9.1c0 6.7-4.5 11.6-11.2 13.9C9.3 28.1 4.8 23.2 4.8 16.5V7.4L16 2.6Z"
        stroke="var(--color-accent)"
        strokeWidth="1.6"
      />
      <path
        d="M16 8.4v15.2M10.4 13.2h11.2"
        stroke="var(--color-secure)"
        strokeWidth="1.6"
      />
      <circle cx="16" cy="13.2" r="2.4" fill="var(--color-ground)" stroke="var(--color-secure)" strokeWidth="1.6" />
    </svg>
  );
}

export function Wordmark({
  compact = false,
  compactText = false,
}: {
  compact?: boolean;
  compactText?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <PactraMark />
      {compact ? null : compactText ? (
        <span className="font-display text-[16px] font-extrabold tracking-[0.16em] text-[color:var(--color-ink)]">
          PACTRA
        </span>
      ) : (
        <div className="min-w-0 leading-tight">
          <p className="font-display text-[15px] font-bold tracking-[0.16em] text-[color:var(--color-ink)]">
            PACTRA
          </p>
          <p className="text-[10px] leading-tight tracking-[0.02em] text-[color:var(--color-ink-4)]">
            Adversarial Transaction Security
            <br />
            for Agentic Commerce
          </p>
        </div>
      )}
    </div>
  );
}
