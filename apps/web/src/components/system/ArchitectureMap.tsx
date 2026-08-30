import { Panel } from "@/components/ui/Panel";
import { cn } from "@/lib/format";

/**
 * The system, by layer.
 *
 * Grouped the way the repository is actually grouped, because a diagram that
 * invents a tidier structure than the code has is a diagram that will mislead
 * anyone who then opens the code. Each component names the module it is.
 */

const LAYERS = [
  {
    name: "Untrusted perimeter",
    tone: "taint" as const,
    note: "Everything here may be hostile, and the design assumes it is.",
    components: [
      { name: "Intent Compiler", module: "raw user text → structured proposal" },
      { name: "Buyer Agent", module: "services/agent_orchestrator" },
      { name: "Merchant Agents", module: "services/agent_orchestrator/merchants" },
    ],
  },
  {
    name: "Security kernel",
    tone: "secure" as const,
    note: "Deterministic Python. The only thing that decides whether money may move.",
    components: [
      { name: "Provenance", module: "packages/schemas/provenance.py" },
      { name: "Taint", module: "sticky through every transformation" },
      { name: "Authority lattice", module: "services/security_kernel/authority.py" },
      { name: "Capability firewall", module: "services/security_kernel/capability.py" },
      { name: "Deterministic policy", module: "services/policy_engine/engine.py" },
      { name: "Transaction binding", module: "services/security_kernel/binding.py" },
      { name: "Authorization", module: "services/security_kernel/authorization.py" },
      { name: "Replay protection", module: "atomic conditional consume" },
      { name: "Risk advisory", module: "services/risk_engine (decides nothing)" },
    ],
  },
  {
    name: "Payment",
    tone: "accent" as const,
    note: "Reached only out of band, by a worker. Never from an HTTP request.",
    components: [
      { name: "PaymentIntent", module: "services/payment_executor/intents.py" },
      { name: "Transactional outbox", module: "services/payment_executor/outbox.py" },
      { name: "Reconciliation", module: "services/payment_executor/reconciliation.py" },
      { name: "Razorpay test rail", module: "services/payment_executor/providers/razorpay.py" },
    ],
  },
  {
    name: "Audit",
    tone: "accent" as const,
    note: "Append-only, hash-linked, verifiable and replayable — and never repaired.",
    components: [
      { name: "Hash chain", module: "services/audit_ledger/ledger.py" },
      { name: "Verification", module: "services/audit_ledger/verify.py" },
      { name: "Deterministic replay", module: "services/audit_ledger/replay.py" },
    ],
  },
  {
    name: "Protocol adapters",
    tone: "neutral" as const,
    note: "Translate shape. They assign no trust and issue nothing.",
    components: [
      { name: "Commerce", module: "services/adapters/commerce" },
      { name: "Payment authorization", module: "services/adapters/authorization" },
      { name: "Tool", module: "services/adapters/tools" },
      { name: "Payment rail", module: "services/adapters/payment_rails" },
    ],
  },
];

export function ArchitectureMap() {
  return (
    <Panel
      title="System architecture"
      subtitle="Grouped as the repository is grouped. Each component names the module it actually is."
    >
      <div className="space-y-3">
        {LAYERS.map((layer) => (
          <section
            key={layer.name}
            className={cn(
              "rounded-lg border p-3.5",
              layer.tone === "taint" &&
                "border-[color:var(--color-taint)]/30 bg-[color:var(--color-taint)]/[0.04]",
              layer.tone === "secure" &&
                "border-[color:var(--color-secure)]/30 bg-[color:var(--color-secure)]/[0.04]",
              layer.tone === "accent" &&
                "border-[color:var(--color-accent)]/25 bg-[color:var(--color-accent)]/[0.035]",
              layer.tone === "neutral" &&
                "border-[color:var(--color-line)] bg-[color:var(--color-surface-2)]",
            )}
          >
            <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
              <h3
                className={cn(
                  "label-xs",
                  layer.tone === "taint" && "text-[color:var(--color-taint)]",
                  layer.tone === "secure" && "text-[color:var(--color-secure)]",
                  layer.tone === "accent" && "text-[color:var(--color-accent)]",
                  layer.tone === "neutral" && "text-[color:var(--color-ink-3)]",
                )}
              >
                {layer.name}
              </h3>
              <p className="text-[11px] text-[color:var(--color-ink-4)]">{layer.note}</p>
            </div>
            <ul className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
              {layer.components.map((component) => (
                <li
                  key={component.name}
                  className="rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface)] px-2.5 py-1.5"
                >
                  <p className="text-[11.5px] font-medium text-[color:var(--color-ink)]">
                    {component.name}
                  </p>
                  <p className="num mt-0.5 truncate text-[10px] text-[color:var(--color-ink-4)]" title={component.module}>
                    {component.module}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </Panel>
  );
}
