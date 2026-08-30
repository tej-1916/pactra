import type { ReactNode } from "react";
import { Check, CircleDashed, CircleSlash, Minus } from "lucide-react";

import { cn } from "@/lib/format";
import { TONES, type Tone } from "@/lib/semantics";

export type StageStatus = "done" | "active" | "blocked" | "pending" | "skipped";

export interface PipelineStage {
  id: string;
  name: string;
  status: StageStatus;
  /** Why this stage is in the state it is. Never marketing text. */
  reason?: ReactNode;
  /** Authority / trust / taint chips relevant at this stage. */
  meta?: ReactNode;
  detail?: ReactNode;
}

const STATUS_TONE: Record<StageStatus, Tone> = {
  done: "secure",
  active: "advisory",
  blocked: "critical",
  pending: "neutral",
  skipped: "neutral",
};

/**
 * The mission's path through the kernel, as a vertical timeline.
 *
 * Every stage carries a status and a REASON, and the reason is the point: a
 * pipeline that only showed green ticks would communicate that things happened,
 * not why they were allowed to. Reason codes appear verbatim inside `reason`.
 *
 * Stage state is derived from live API values by the caller. Nothing here
 * invents a stage that the mission has not actually reached.
 */
export function MissionPipeline({ stages }: { stages: PipelineStage[] }) {
  return (
    <ol className="relative space-y-0">
      {stages.map((stage, index) => {
        const last = index === stages.length - 1;
        const tone = STATUS_TONE[stage.status];
        return (
          <li key={stage.id} className="relative flex gap-3 pb-4 last:pb-0">
            {!last ? (
              <span
                aria-hidden
                className={cn(
                  "absolute top-6 bottom-0 left-[11px] w-[1.5px]",
                  stage.status === "done"
                    ? "bg-[color:var(--color-secure)]/35"
                    : "bg-[color:var(--color-line)]",
                )}
              />
            ) : null}

            <span
              className={cn(
                "relative z-10 mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border",
                TONES[tone].solid,
              )}
            >
              <StageIcon status={stage.status} />
            </span>

            <div className="min-w-0 flex-1 pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3
                  className={cn(
                    "text-[12.5px] font-semibold tracking-tight",
                    stage.status === "pending"
                      ? "text-[color:var(--color-ink-4)]"
                      : "text-[color:var(--color-ink)]",
                  )}
                >
                  {stage.name}
                </h3>
                <span className={cn("label-xs", TONES[tone].text)}>
                  {stage.status.toUpperCase()}
                </span>
                {stage.meta}
              </div>
              {stage.reason ? (
                <div className="mt-1.5 text-[12px] leading-relaxed text-[color:var(--color-ink-3)]">
                  {stage.reason}
                </div>
              ) : null}
              {stage.detail ? <div className="mt-2">{stage.detail}</div> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function StageIcon({ status }: { status: StageStatus }) {
  if (status === "done") return <Check aria-hidden className="size-3.5" />;
  if (status === "blocked") return <CircleSlash aria-hidden className="size-3.5" />;
  if (status === "active") return <CircleDashed aria-hidden className="size-3.5" />;
  return <Minus aria-hidden className="size-3" />;
}
