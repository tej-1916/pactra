"use client";

import { useState } from "react";
import { ShieldCheck, KeyRound, Zap, FileCheck, Lock, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/format";
import { PactraBeamsBackground } from "@/components/ui/beams-background";

export function DarkProductSection() {
  const [activeTab, setActiveTab] = useState<"policy" | "authority" | "payment" | "audit">("policy");

  const tabDetails = {
    policy: {
      title: "Deterministic Policy Gate",
      subtitle: "ADMIT STAGE · ZERO MODEL-TRUST",
      icon: ShieldCheck,
      description:
        "LLMs select and propose transactions, but PACTRA applies deterministic policy and invariant checks before authority-bearing transaction execution.",
      code: `// Deterministic Admission Policy
invariant check_agent_budget(tx: Transaction) {
  assert tx.amount <= agent.authority_limit, "EXCEEDS_GRANTED_AUTHORITY";
  assert tx.merchant.verified == true, "UNTRUSTED_MERCHANT_ORIGIN";
  assert tx.nonce == expected_nonce(), "REPLAY_ATTEMPT_DETECTED";
} => ADMIT_PASS`,
      metrics: [
        { label: "Invariant Checks", value: "100%", status: "STRICT" },
        { label: "Policy Execution", value: "< 1.2ms", status: "DETERMINISTIC" },
      ],
    },
    authority: {
      title: "Canonical Transaction Authority",
      subtitle: "BIND STAGE · CANONICAL BINDING",
      icon: KeyRound,
      description:
        "Canonical transaction binding and deterministic authorization. Binds transaction digest, offer version, expiry, and nonce before authorization.",
      code: `// Canonical Transaction Binding & Authorization
const boundTransaction = {
  missionId: "msn_8f9a2b",
  transactionDigest: "0x8f7a...3e1d",
  offerVersion: "v2.1",
  amount: 25000, // in cents ($250.00)
  nonce: "nc_7749120485",
  scheme: "POLICY_AUTO" // Policy-authorized · no user signature required
};
const decision = authorize_binding(boundTransaction); => BIND_BOUND`,
      metrics: [
        { label: "Binding Scheme", value: "CANONICAL", status: "VERIFIED" },
        { label: "Replay Protection", value: "ACTIVE", status: "NONCE_HELD" },
      ],
    },
    payment: {
      title: "Durable Payment Verification",
      subtitle: "EXECUTE STAGE · PAYMENT RECONCILIATION",
      icon: Zap,
      description:
        "Durable PaymentIntent tracking with provider evidence verification, idempotency protection, and reconciliation.",
      code: `// Durable Payment Verification & Reconciliation
verify_payment_intent({
  payment_intent_id: "pi_3K9x1a2b",
  provider: "razorpay",
  evidence_status: "SUCCEEDED",
  idempotency_key: "idemp_99182a"
}) => EXECUTE_SETTLED`,
      metrics: [
        { label: "Payment Intent", value: "DURABLE", status: "TRACKED" },
        { label: "Reconciliation", value: "IDEMPOTENT", status: "VERIFIED" },
      ],
    },
    audit: {
      title: "Replayable Decision Trace",
      subtitle: "EVIDENCE · TAMPER-EVIDENT AUDIT",
      icon: FileCheck,
      description:
        "Tamper-evident audit chain and verified replay through the Decision Trace. Recorded audit events support verified replay and post-hoc verification.",
      code: `// SCHEMA EXAMPLE · Decision Trace Entry (C1 Contract)
DecisionTraceEntry {
  stage: "EXECUTE",
  event_type: "PAYMENT_SUCCEEDED",
  verdict: "SUCCEEDED",
  reason_codes: [],
  invariant_id: null,
  approval_scheme: "POLICY_AUTO",
  policy_outcome: "ALLOW",
  payment_state: "SUCCEEDED",
  advisory: false,
  next_action: "NONE",
  evidence: { event_id: "evt_8f9a2b", sequence: 4, actor: "PAYMENT_WORKER" },
  recorded_at: "2026-08-31T03:35:00Z"
} => VERIFIED_REPLAYABLE`,
      metrics: [
        { label: "Audit Integrity", value: "TAMPER-EVIDENT", status: "VERIFIED" },
        { label: "Decision Trace", value: "REPLAYABLE", status: "VERIFIED" },
      ],
    },
  };

  const current = tabDetails[activeTab];
  const CurrentIcon = current.icon;

  return (
    <section className="relative w-full overflow-hidden rounded-2xl border border-[color:var(--pactra-line-strong)] shadow-xl">
      <PactraBeamsBackground className="p-5 sm:p-8">
        {/* Section Header */}
        <div className="relative z-10 max-w-3xl mb-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#202160]/80 border border-[#7771DF]/40 mb-2.5">
            <Lock className="size-3.5 text-[#BBB9F5]" />
            <span className="font-mono text-[10.5px] font-semibold text-[#BBB9F5] tracking-wide uppercase">
              HIGH-IMPACT SECURITY FOUNDATION
            </span>
          </div>
          <h2 className="font-display text-2xl sm:text-3xl font-extrabold tracking-tight text-white">
            Architected for zero model-trust execution.
          </h2>
          <p className="mt-1.5 text-xs sm:text-sm text-[#BBB9F5]/90 leading-relaxed">
            The AI reasoning layer is treated as an untrusted client. PACTRA enforces policy, authority, payment execution, and cryptographic audit traces at the infrastructure level.
          </p>
        </div>

      {/* Navigation Tabs */}
      <div className="relative z-10 grid grid-cols-2 sm:grid-cols-4 gap-2 mb-6">
        {(["policy", "authority", "payment", "audit"] as const).map((tab) => {
          const tabInfo = tabDetails[tab];
          const Icon = tabInfo.icon;
          const isActive = activeTab === tab;

          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              type="button"
              className={cn(
                "flex items-center gap-2.5 p-3 rounded-xl border text-left transition-all duration-200 cursor-pointer",
                isActive
                  ? "bg-[#28247A] border-[#9D9BE7] text-white shadow-lg shadow-[#4B42B9]/30"
                  : "bg-[#1E2160]/60 border-white/10 text-[#C1C0F3]/70 hover:bg-[#1E2160] hover:text-white"
              )}
            >
              <div
                className={cn(
                  "flex size-7 items-center justify-center rounded-lg shrink-0",
                  isActive ? "bg-[#4B42B9] text-white" : "bg-[#12162F] text-[#9D9BE7]"
                )}
              >
                <Icon className="size-4" />
              </div>
              <div className="min-w-0">
                <span className="font-mono text-[11px] font-bold block truncate uppercase">
                  {tab}
                </span>
                <span className="text-[9.5px] text-[#9D9BE7]/80 block truncate">
                  {tabInfo.subtitle.split(" · ")[0]}
                </span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Interactive Feature Display Area */}
      <div className="relative z-10 grid gap-6 lg:grid-cols-12 items-stretch">
        {/* Left Info Panel */}
        <div className="lg:col-span-5 flex flex-col justify-between rounded-xl border border-white/15 bg-[#1E2160]/80 p-5 sm:p-6 backdrop-blur-md">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <CurrentIcon className="size-5 text-[#9D9BE7]" />
              <span className="font-mono text-[11px] font-bold text-[#9D9BE7] tracking-wider uppercase">
                {current.subtitle}
              </span>
            </div>
            <h3 className="font-display text-xl font-bold text-white mb-3">
              {current.title}
            </h3>
            <p className="text-xs sm:text-sm text-[#C1C0F3] leading-relaxed mb-6">
              {current.description}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-4 border-t border-white/10">
            {current.metrics.map((metric) => (
              <div key={metric.label} className="p-2.5 rounded-lg bg-[#12162F]/60 border border-white/10">
                <span className="text-[10px] font-mono text-[#9D9BE7] block">
                  {metric.label}
                </span>
                <span className="font-mono text-sm font-bold text-white block mt-0.5">
                  {metric.value}
                </span>
                <span className="inline-flex items-center gap-1 font-mono text-[9px] text-[#04785A] font-semibold mt-1">
                  <CheckCircle2 className="size-2.5" />
                  {metric.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Right Code & Trace Visualizer */}
        <div className="lg:col-span-7 rounded-xl border border-[#7C78E2]/40 bg-[#12162F] p-4 sm:p-6 font-mono text-xs text-[#F7F7FF] flex flex-col justify-between shadow-inner">
          <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-4">
            <div className="flex items-center gap-2">
              <div className="size-2.5 rounded-full bg-[#C02231]" />
              <div className="size-2.5 rounded-full bg-[#B7791F]" />
              <div className="size-2.5 rounded-full bg-[#04785A]" />
              <span className="text-[11px] text-[#9D9BE7] ml-2">pactra_kernel.rs</span>
            </div>
            <span className="text-[10px] text-[#04785A] bg-[#04785A]/15 px-2 py-0.5 rounded border border-[#04785A]/30">
              STATE: VERIFIED_LEGAL
            </span>
          </div>

          <pre className="overflow-x-auto text-[11.5px] leading-relaxed text-[#C1C0F3] p-3 rounded bg-[#1E2160]/40 border border-white/5 whitespace-pre-wrap">
            <code>{current.code}</code>
          </pre>

          <div className="mt-4 pt-3 border-t border-white/10 flex items-center justify-between text-[11px] text-[#9D9BE7]">
            <span className="flex items-center gap-1.5">
              <ShieldCheck className="size-3.5 text-[#04785A]" />
              AUTHORITATIVE CONTRACT ENFORCED
            </span>
            <span className="font-mono text-[10px] text-white">0 FAILS · 100% REPLAYABLE</span>
          </div>
        </div>
      </div>
      </PactraBeamsBackground>
    </section>
  );
}
