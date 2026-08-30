import {
  ArrowRight,
  CheckCircle2,
  CircleDashed,
  CircleSlash,
  Info,
  ShieldX,
  TriangleAlert,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/format";
import { NEXT_ACTION_MEANING, VERDICT_PRESENTATION, verdictTone } from "@/lib/trace";
import type { DecisionNextAction, DecisionStage, DecisionVerdict } from "@/lib/types/pactra";

/**
 * Every verdict in the trace renders through here, and the machine value is
 * always printed verbatim: `REFUSED` shows as `REFUSED`, never as "Blocked".
 *
 * Each verdict carries a distinct ICON as well as a distinct tone, because two
 * of them share the secure palette — a refusal and a success are both PACTRA
 * working — and colour alone would make them indistinguishable.
 */
const VERDICT_ICON: Record<DecisionVerdict, typeof CheckCircle2> = {
  ACCEPTED: CheckCircle2,
  REFUSED: ShieldX,
  PENDING: CircleDashed,
  SUCCEEDED: CheckCircle2,
  FAILED: XCircle,
  IGNORED: CircleSlash,
  ADVISORY: Info,
};

export function VerdictBadge({ verdict }: { verdict: DecisionVerdict }) {
  const Icon = VERDICT_ICON[verdict] ?? TriangleAlert;
  const presentation = VERDICT_PRESENTATION[verdict];
  return (
    <Badge
      tone={verdictTone(verdict)}
      mono
      icon={<Icon aria-hidden className="size-3.5" />}
      title={presentation?.meaning}
    >
      {verdict}
    </Badge>
  );
}

const STAGE_ORDINAL: Record<DecisionStage, string> = {
  ADMIT: "01",
  BIND: "02",
  EXECUTE: "03",
};

export function StageMarker({
  stage,
  active,
  className,
}: {
  stage: DecisionStage;
  /** The stage this mission's history actually reached. */
  active: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "num inline-flex items-center gap-1.5 rounded px-2 py-[3px] text-[11px] font-semibold tracking-tight",
        active
          ? // The active decision path is one of the four places gradient is
            // spent. It marks where authority actually travelled.
            "gradient-authority text-[color:var(--color-surface)]"
          : "border border-[color:var(--color-line)] text-[color:var(--color-ink-4)]",
        className,
      )}
    >
      <span className={cn("text-[9px]", active ? "opacity-70" : "opacity-60")}>
        {STAGE_ORDINAL[stage]}
      </span>
      {stage}
    </span>
  );
}

/** What may happen next, printed verbatim with its fixed meaning attached. */
export function NextActionChip({
  action,
  className,
}: {
  action: DecisionNextAction;
  className?: string;
}) {
  return (
    <span
      title={NEXT_ACTION_MEANING[action]}
      className={cn(
        "num inline-flex items-center gap-1 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-1.5 py-[2px] text-[10.5px] text-[color:var(--color-ink-3)]",
        className,
      )}
    >
      <ArrowRight aria-hidden className="size-3 shrink-0" />
      {action}
    </span>
  );
}
