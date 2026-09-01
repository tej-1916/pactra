import { ArrowRight, RefreshCw } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { DataTierBadge } from "@/components/ui/DataTier";

export function PaymentReliabilitySection() {
  const steps = [
    { title: "1. DISPATCH", type: "ACTION", desc: "Idempotent PaymentIntent created and dispatched with unique nonce." },
    { title: "2. UNKNOWN RESULT", type: "FLOW STATE", desc: "Network timeout or lost provider HTTP response handled safely." },
    { title: "3. PROVIDER_PENDING", type: "PAYMENT_STATE", desc: "State machine enters PROVIDER_PENDING — never retries blindly without check." },
    { title: "4. RECONCILE", type: "NEXT_ACTION", desc: "Dispatches RECONCILE_PAYMENT via provider API or webhook event evidence." },
    { title: "5. EVIDENCE & AUDIT", type: "TERMINAL STATE", desc: "Final payment_state settled to SUCCEEDED, FAILED_RETRYABLE, or FAILED_TERMINAL." },
  ];

  return (
    <Panel
      title="EXECUTION & RELIABILITY FLOW"
      subtitle="How PACTRA manages lost provider responses, network partitions, and idempotency guarantees."
      actions={<DataTierBadge tier="generated" />}
    >
      <div className="space-y-4">
        {/* Step Flow */}
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
          {steps.map((s, idx) => (
            <div
              key={s.title}
              className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-3 space-y-1.5 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)]">
                    {s.title}
                  </span>
                </div>
                <span className="inline-block font-mono text-[9px] font-semibold text-[color:var(--pactra-ink-muted)] uppercase tracking-wider mt-0.5">
                  [{s.type}]
                </span>
                <p className="text-[11.5px] leading-snug text-[color:var(--pactra-ink-secondary)] pt-1">
                  {s.desc}
                </p>
              </div>
              {idx < steps.length - 1 && (
                <div className="hidden lg:block pt-2 text-right">
                  <ArrowRight className="inline size-3.5 text-[color:var(--pactra-ink-muted)]" />
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="rounded border border-[#B7791F]/30 bg-[#B7791F]/10 p-3 text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)] flex items-start gap-2.5">
          <RefreshCw className="size-4 text-[#B7791F] shrink-0 mt-0.5" />
          <div>
            <span className="font-mono font-bold text-[#B7791F]">RAZORPAY TEST MODE PATH SUPPORTED:</span>{" "}
            Provider-derived terminal outcomes such as SUCCEEDED, FAILED_RETRYABLE, and FAILED_TERMINAL are shown only when supported by runtime evidence.
          </div>
        </div>
      </div>
    </Panel>
  );
}
