import type { DecisionTraceEntry } from "@/lib/types/pactra";
import { DecisionTrace } from "@/components/trace/DecisionTrace";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";
import { FileClock } from "lucide-react";

export function CommerceTraceTimeline({
  entries,
  isDemo = true,
}: {
  entries: DecisionTraceEntry[];
  isDemo?: boolean;
}) {
  return (
    <Panel
      title="DECISION TRACE TIMELINE"
      subtitle="ADMIT → BIND → EXECUTE enforcement events projected from verified evidence. Tamper-evident audit evidence recorded for replay."
      actions={
        <Badge tone={isDemo ? "advisory" : "secure"} variant="outline" icon={<FileClock className="size-3.5" />}>
          {isDemo ? "DEMO TRACE" : "RUNTIME EVIDENCE"}
        </Badge>
      }
    >
      <DecisionTrace entries={entries} />
    </Panel>
  );
}
