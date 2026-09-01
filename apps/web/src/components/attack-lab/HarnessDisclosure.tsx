import { ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

export function HarnessDisclosure() {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-warning)]/40 bg-[color:var(--pactra-surface-2)] p-4 space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldAlert className="size-4 text-[color:var(--pactra-warning)]" />
          <span className="font-mono text-[13px] font-bold text-[color:var(--pactra-ink)]">
            AUTHORED ADVERSARIAL REGRESSION HARNESS
          </span>
        </div>
        <Badge tone="advisory" variant="outline">
          DEMO SCENARIO
        </Badge>
      </div>
      <p className="text-[12px] text-[color:var(--pactra-ink-secondary)] leading-relaxed">
        This lab is an authored adversarial regression suite demonstrating PACTRA&apos;s deterministic transaction boundaries against hostile input. It does not perform live penetration testing or vulnerability scanning. All scenario execution results are projected from authored regression evidence.
      </p>
    </div>
  );
}
