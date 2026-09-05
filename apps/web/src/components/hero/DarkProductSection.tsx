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
      code: `// ILLUSTRATIVE SCHEMA EXAMPLE · Deterministic Admission Policy
invariant check_agent_budget(tx: Transaction) {
  assert tx.amount <= agent.authority_limit, "EXCEEDS_GRANTED_AUTHORITY";
  assert tx.merchant.verified == true, "UNTRUSTED_MERCHANT_ORIGIN";
  assert tx.nonce == expected_nonce(), "REPLAY_ATTEMPT_DETECTED";
} => ADMIT_PASS`,
      metrics: [
        { label: "Policy Evaluation", value: "DETERMINISTIC", status: "NO MODEL INPUT" },
        { label: "Admission Checks", value: "FAIL-CLOSED", status: "BY DESIGN" },
      ],
    },
    authority: {
      title: "Canonical Transaction Authority",
      subtitle: "BIND STAGE · CANONICAL BINDING",
      icon: KeyRound,
      description:
        "Canonical transaction binding and deterministic authorization. Binds transaction digest, offer version, expiry, and nonce before authorization.",
      code: `// ILLUSTRATIVE SCHEMA EXAMPLE · Transaction Binding & Authorization Check
const boundTransaction = {
  missionId: "msn_<id>",
  transactionDigest: "0x<digest>",
  offerVersion: "v2.1",
  amount: 250000, // paise (₹2,500.00 INR)
  nonce: "nc_<nonce>",
  scheme: "POLICY_AUTO" // Policy-activated · no user signature required
};
const decision = authorize_binding(boundTransaction); => BIND_BOUND`,
      metrics: [
        { label: "Binding Scheme", value: "CANONICAL", status: "BY DESIGN" },
        { label: "Replay Protection", value: "NONCE-BOUND", status: "BY DESIGN" },
      ],
    },
    payment: {
      title: "Durable Payment Reconciliation",
      subtitle: "EXECUTE STAGE · PROVIDER RECONCILIATION",
      icon: Zap,
      description:
        "Durable PaymentIntent tracking with a one-way create fence, idempotency protection, and reconciliation against provider records. An unresolved dispatch stays uncertain rather than being guessed either way.",
      code: `// ILLUSTRATIVE SCHEMA EXAMPLE · Provider Reconciliation
reconcile_payment_intent({
  payment_intent_id: "pi_<id>",
  idempotency_key: "idemp_<key>",
  create_fence: "CONSUMED",
  payment_state: "PROVIDER_PENDING" // uncertain until evidence resolves
}) => RECONCILE_PAYMENT`,
      metrics: [
        { label: "Payment Intent", value: "DURABLE", status: "BY DESIGN" },
        { label: "Reconciliation", value: "IDEMPOTENT", status: "BY DESIGN" },
      ],
    },
    audit: {
      title: "Replayable Decision Trace",
      subtitle: "EVIDENCE · TAMPER-EVIDENT AUDIT",
      icon: FileCheck,
      description:
        "Tamper-evident audit chain and verified replay through the Decision Trace. Recorded audit events support verified replay and post-hoc verification.",
      code: `// ILLUSTRATIVE SCHEMA EXAMPLE · Decision Trace Entry (C1 Contract)
DecisionTraceEntry {
  stage: "BIND",
  event_type: "AUTHORIZATION_CREATED",
  verdict: "PENDING",
  reason_codes: [],
  invariant_id: null,
  approval_scheme: "POLICY_AUTO",
  policy_outcome: null,
  payment_state: null,
  advisory: false,
  next_action: "CONTINUE_BIND",
  evidence: { event_id: "evt_<id>", sequence: 2, actor: "kernel" },
  recorded_at: "<iso-8601>"
} => HASH_LINKED_AUDIT_EVIDENCE`,
      metrics: [
        { label: "Audit Integrity", value: "TAMPER-EVIDENT", status: "BY DESIGN" },
        { label: "Decision Trace", value: "REPLAYABLE", status: "BY DESIGN" },
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
                  isActive ? "bg-[#4B42B9] text-white" : "bg-[#12162F] text-[#C7C5F8]"
                )}
              >
                <Icon className="size-4" />
              </div>
              <div className="min-w-0">
                <span className="font-mono text-[11px] font-bold block truncate uppercase">
                  {tab}
                </span>
                <span className="text-[9.5px] text-[#C7C5F8] block truncate font-medium">
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
              <CurrentIcon className="size-5 text-[#C7C5F8]" />
              <span className="font-mono text-[11px] font-bold text-[#C7C5F8] tracking-wider uppercase">
                {current.subtitle}
              </span>
            </div>
            <h3 className="font-display text-xl font-bold text-white mb-3">
              {current.title}
            </h3>
            <p className="text-xs sm:text-sm text-[#E2E1FC] leading-relaxed mb-6">
              {current.description}
            </p>
          </div>

          {/* Structural properties of the design, not measured output. The
              heading is part of the claim: a number or a rate does not belong
              on this panel, and the only place a measured figure is shown is a
              labelled harness report. */}
          <div className="pt-4 border-t border-white/10">
            <span className="font-mono text-[9.5px] font-semibold uppercase tracking-wider text-[#BBB9F5]">
              Design properties · not measurements
            </span>
            <div className="mt-2.5 grid grid-cols-2 gap-3">
              {current.metrics.map((metric) => (
                <div key={metric.label} className="p-2.5 rounded-lg bg-[#12162F]/60 border border-white/10">
                  <span className="text-[10px] font-mono text-[#C7C5F8] block">
                    {metric.label}
                  </span>
                  <span className="font-mono text-sm font-bold text-white block mt-0.5">
                    {metric.value}
                  </span>
                  <span className="inline-flex items-center gap-1 font-mono text-[9px] text-[#10B981] font-semibold mt-1">
                    <CheckCircle2 className="size-2.5" />
                    {metric.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Code & Trace Visualizer */}
        <div className="lg:col-span-7 rounded-xl border border-[#7C78E2]/40 bg-[#12162F] p-4 sm:p-6 font-mono text-xs text-[#F7F7FF] flex flex-col justify-between shadow-inner">
          <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-4">
            <div className="flex items-center gap-2">
              <div className="size-2.5 rounded-full bg-[#EF4444]" />
              <div className="size-2.5 rounded-full bg-[#FBBF24]" />
              <div className="size-2.5 rounded-full bg-[#10B981]" />
              <span className="font-mono text-[11px] text-[#C7C5F8] ml-2 uppercase tracking-wide">
                Illustrative schema example
              </span>
            </div>
            <span className="text-[10px] text-[#C7C5F8] bg-[#202160] px-2 py-0.5 rounded border border-[#7771DF]/40">
              NOT RUNTIME EVIDENCE
            </span>
          </div>

          <pre className="overflow-x-auto text-[11.5px] leading-relaxed text-[#E2E1FC] p-3 rounded bg-[#1E2160]/40 border border-white/5 whitespace-pre-wrap">
            <code>{current.code}</code>
          </pre>

          {/* The panel is a conceptual explainer, so it says so where the code
              is, not in an appendix. Nothing here is a measurement, a provider
              result, or evidence that any payment was paid, captured, settled
              or completed through Checkout. */}
          <div className="mt-4 pt-3 border-t border-white/10 flex items-start gap-1.5 text-[11px] leading-relaxed text-[#C7C5F8]">
            <ShieldCheck className="size-3.5 shrink-0 mt-0.5 text-[#C7C5F8]" />
            <span>
              Conceptual illustration of the enforced contract — not runtime evidence, not a
              measurement, and not a provider result.
            </span>
          </div>
        </div>
      </div>
      </PactraBeamsBackground>
    </section>
  );
}
