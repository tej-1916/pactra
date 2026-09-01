import { Activity, CreditCard, Fingerprint, Network } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

interface DemoSignal {
  type: string;
  category: "BEHAVIORAL" | "TRANSACTION" | "PROVENANCE" | "PROVIDER";
  icon: typeof Activity;
  name: string;
  observedValue: string;
  rawWeight: number;
  explanation: string;
}

const DEMO_SIGNALS: DemoSignal[] = [
  {
    type: "BEHAVIORAL SIGNAL",
    category: "BEHAVIORAL",
    icon: Activity,
    name: "Burst Request Velocity",
    observedValue: "4 purchase attempts in 12 seconds",
    rawWeight: 0.25,
    explanation: "Autonomous agent repeatedly requesting checkout within a compressed timeframe.",
  },
  {
    type: "TRANSACTION SIGNAL",
    category: "TRANSACTION",
    icon: CreditCard,
    name: "Soft Budget Proximity",
    observedValue: "Requested ₹4,800 against ₹5,000 budget cap",
    rawWeight: 0.15,
    explanation: "Transaction amount within 95% of user-declared soft policy threshold.",
  },
  {
    type: "PROVENANCE SIGNAL",
    category: "PROVENANCE",
    icon: Fingerprint,
    name: "Unregistered Merchant Endpoint",
    observedValue: "Catalog domain mismatch vs registry",
    rawWeight: 0.4,
    explanation: "Merchant offer contains unverified metadata fields not grounded in trusted registry.",
  },
  {
    type: "PROVIDER SIGNAL",
    category: "PROVIDER",
    icon: Network,
    name: "Upstream Gateway Latency",
    observedValue: "Payment provider response time > 2500ms",
    rawWeight: 0.1,
    explanation: "Elevated provider response times suggest potential transient timeout risk.",
  },
];

export function DemoAdvisorySignals() {
  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--pactra-line)] pb-3">
        <div>
          <h2 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            DEMO ADVISORY SIGNALS
          </h2>
          <p className="text-[12px] text-[color:var(--pactra-ink-muted)]">
            Authored advisory indicators illustrating non-authoritative operator context.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="accent" variant="outline">
            SYNTHETIC DEMO DATA
          </Badge>
          <Badge tone="advisory" variant="outline">
            DEMO ADVISORY SIGNALS
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {DEMO_SIGNALS.map((signal) => {
          const Icon = signal.icon;
          return (
            <div
              key={signal.name}
              className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between space-y-3"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[10.5px] font-bold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-2 py-0.5 rounded">
                    {signal.type}
                  </span>
                  <Icon className="size-4 text-[color:var(--pactra-indigo)]" />
                </div>
                <h3 className="font-display text-[13px] font-bold text-[color:var(--pactra-ink)]">
                  {signal.name}
                </h3>
                <div className="rounded bg-[color:var(--pactra-surface-3)] p-2 font-mono text-[11px] text-[color:var(--pactra-indigo)] border border-[color:var(--pactra-line)]">
                  {signal.observedValue}
                </div>
                <p className="text-[11px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
                  {signal.explanation}
                </p>
              </div>

              <div className="border-t border-[color:var(--pactra-line)] pt-2 flex items-center justify-between text-[11px] font-mono">
                <span className="text-[color:var(--pactra-ink-muted)]">Weight:</span>
                <span className="font-bold text-[color:var(--pactra-ink)]">+{signal.rawWeight.toFixed(2)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
