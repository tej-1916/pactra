"use client";

import { Server, ShieldCheck, Scale, KeyRound, CreditCard, Layers, History, Cpu } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { useHealth } from "@/lib/hooks/queries";

interface SystemComponentDef {
  name: string;
  category: string;
  icon: typeof Server;
  implementationStatus: "IMPLEMENTED IN CODE" | "PARTIAL IMPLEMENTATION" | "NOT IMPLEMENTED";
  configurationStatus: (healthData: { payment_test_mode?: boolean } | null) =>
    | "CONFIGURED"
    | "TEST MODE CONFIGURED"
    | "NOT TEST MODE CONFIGURED"
    | "FRONTEND CONFIGURED"
    | "NOT CONFIGURED"
    | "CONFIGURATION NOT OBSERVED";
  runtimeEvidence: (isPending: boolean, isOk: boolean) => "RUNTIME EVIDENCE" | "AWAITING RUNTIME EVIDENCE" | "RUNTIME EVIDENCE UNAVAILABLE" | "NOT RUNTIME VERIFIED";
  runtimeTone: (isPending: boolean, isOk: boolean) => "secure" | "advisory" | "neutral";
  details: string;
  limitations: string;
}

const COMPONENTS: SystemComponentDef[] = [
  {
    name: "API Surface",
    category: "Transport & Routing",
    icon: Server,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: () => "CONFIGURED",
    runtimeEvidence: (isPending, isOk) => (isPending ? "AWAITING RUNTIME EVIDENCE" : isOk ? "RUNTIME EVIDENCE" : "RUNTIME EVIDENCE UNAVAILABLE"),
    runtimeTone: (isPending, isOk) => (isPending ? "neutral" : isOk ? "secure" : "advisory"),
    details: "FastAPI backend routes and Next.js BFF proxy for missions, events, authorization, payment, replay, and risk.",
    limitations: "HTTP 200 represents network transport response for the tested endpoint, not end-to-end downstream provider success.",
  },
  {
    name: "Security Kernel",
    category: "Core Authority Engine",
    icon: ShieldCheck,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: () => "FRONTEND CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "Deterministic authority lattice, provenance propagation, taint tracking, and capability boundary enforcement.",
    limitations: "Operates across strictly 3 stages: ADMIT, BIND, EXECUTE. Invariants are verified in test suites rather than live heartbeats.",
  },
  {
    name: "Policy Engine",
    category: "Deterministic Adjudication",
    icon: Scale,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: () => "FRONTEND CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "Evaluates hard budget limits, merchant categories, and policy rules, returning deterministic ALLOW, REQUIRE_APPROVAL, or DENY.",
    limitations: "Does not consume caller-supplied risk scores or advisory weights during adjudication.",
  },
  {
    name: "Authorization System",
    category: "Transaction Authorization",
    icon: KeyRound,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: () => "FRONTEND CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "Creates and validates transaction authorizations under POLICY_AUTO, USER_ED25519, and LEGACY_SERVER schemes.",
    limitations: "Authorization is single-use and strictly bound to canonical merchant offer and transaction digest.",
  },
  {
    name: "Payment Outbox",
    category: "Idempotent Execution",
    icon: CreditCard,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: () => "FRONTEND CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "Single-dispatch state machine implemented (CREATED → QUEUED → PROCESSING → PROVIDER_PENDING → SUCCEEDED/FAILED).",
    limitations: "Prevents double-charges via database UNIQUE(idempotency_key) constraint and outbox polling.",
  },
  {
    name: "Razorpay Payment Rail",
    category: "Payment Provider Adapter / Payment Rail",
    icon: Layers,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: (health) =>
      health === null
        ? "CONFIGURATION NOT OBSERVED"
        : health.payment_test_mode
        ? "TEST MODE CONFIGURED"
        : "NOT TEST MODE CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "Orders API integration and constant-time HMAC-SHA256 webhook signature verification.",
    limitations: "Razorpay TEST mode only: rzp_test_* credentials are supported and live-mode credentials are refused. This overview does not itself prove a current provider call — per-transaction provider evidence appears on the mission and payment surfaces. No Checkout front end exists.",
  },
  {
    name: "Audit & Deterministic Replay",
    category: "Evidence Reconstruction",
    icon: History,
    implementationStatus: "IMPLEMENTED IN CODE",
    configurationStatus: () => "CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "Cryptographic event hash chaining and deterministic historical replay projection from recorded evidence.",
    limitations: "Replay is evidence reconstruction from recorded audit evidence, NOT payment re-execution. Verified on /audit per mission.",
  },
  {
    name: "Protocol Adapters",
    category: "Commerce Protocol Ingestion",
    icon: Cpu,
    implementationStatus: "PARTIAL IMPLEMENTATION",
    configurationStatus: () => "FRONTEND CONFIGURED",
    runtimeEvidence: () => "NOT RUNTIME VERIFIED",
    runtimeTone: () => "neutral",
    details: "JSON-RPC 2.0 tools/call translation for MCP; PACTRA-native commerce and authorization intent adapters.",
    limitations: "PACTRA is not an MCP server. External protocols AP2, x402, and ACP are roadmap items only.",
  },
];

export function ComponentAvailabilityTable() {
  const health = useHealth();
  const isPending = health.isPending;
  const isOk = health.data?.kind === "ok";
  const healthData = health.data?.kind === "ok" ? health.data.data : null;

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--pactra-line)] pb-3">
        <div>
          <h2 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            COMPONENT AVAILABILITY & THREE-TIER EVIDENCE REGISTER
          </h2>
          <p className="text-[12px] text-[color:var(--pactra-ink-muted)]">
            Separates implementation presence in code, environment configuration, and empirical runtime evidence.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="secure" variant="outline">
            TIER A: IMPLEMENTATION
          </Badge>
          <Badge tone="accent" variant="outline">
            TIER B: CONFIGURATION
          </Badge>
          <Badge tone="advisory" variant="outline">
            TIER C: RUNTIME EVIDENCE
          </Badge>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-left font-mono text-[11px]">
          <thead>
            <tr className="border-b border-[color:var(--pactra-line)] text-[10px] uppercase tracking-wider text-[color:var(--pactra-ink-muted)]">
              <th className="py-2.5 px-3">Component</th>
              <th className="py-2.5 px-3">Category</th>
              <th className="py-2.5 px-3">Tier A: Implementation</th>
              <th className="py-2.5 px-3">Tier B: Configuration</th>
              <th className="py-2.5 px-3">Tier C: Runtime Evidence</th>
              <th className="py-2.5 px-3">Operational Scope & Limitations</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[color:var(--pactra-line)]/50">
            {COMPONENTS.map((comp) => {
              const Icon = comp.icon;
              const configStatus = comp.configurationStatus(healthData);
              const runtimeEv = comp.runtimeEvidence(isPending, isOk);
              const tone = comp.runtimeTone(isPending, isOk);

              return (
                <tr key={comp.name} className="hover:bg-[color:var(--pactra-surface-2)]/50 transition-colors">
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-2 font-display text-[12.5px] font-bold text-[color:var(--pactra-ink)]">
                      <Icon className="size-4 text-[color:var(--pactra-indigo)] shrink-0" />
                      {comp.name}
                    </div>
                  </td>
                  <td className="py-3 px-3 text-[color:var(--pactra-ink-secondary)]">
                    {comp.category}
                  </td>
                  <td className="py-3 px-3">
                    <span className="inline-flex rounded bg-[color:var(--pactra-surface-3)] px-2 py-0.5 text-[10px] font-bold text-[color:var(--pactra-indigo)] border border-[color:var(--pactra-line)]">
                      {comp.implementationStatus}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span className="inline-flex rounded bg-[color:var(--pactra-surface-2)] px-2 py-0.5 text-[10px] font-bold text-[color:var(--pactra-ink-secondary)] border border-[color:var(--pactra-line)]">
                      {configStatus}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <span
                      className={`inline-flex rounded px-2 py-0.5 text-[10px] font-bold ${
                        tone === "secure"
                          ? "bg-[color:var(--pactra-success)]/15 text-[color:var(--pactra-success)] border border-[color:var(--pactra-success)]/30"
                          : tone === "advisory"
                          ? "bg-[color:var(--pactra-warning)]/15 text-[color:var(--pactra-warning)] border border-[color:var(--pactra-warning)]/30"
                          : "bg-[color:var(--pactra-surface-3)] text-[color:var(--pactra-ink-muted)] border border-[color:var(--pactra-line)]"
                      }`}
                    >
                      {runtimeEv}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-[10.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)] max-w-[300px]">
                    <div>{comp.details}</div>
                    <div className="mt-1 text-[9.5px] text-[color:var(--pactra-ink-muted)] italic">
                      {comp.limitations}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
