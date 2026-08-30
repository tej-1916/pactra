import { ArrowRight, ShieldCheck } from "lucide-react";

import { Panel } from "@/components/ui/Panel";
import { AuthorityBadge, TaintBadge, TrustBadge } from "@/components/ui/StatusBadges";
import { InvariantCard } from "@/components/ui/InvariantCard";

/**
 * What an adapter is, and — more usefully — what it is not.
 *
 * The four invariants are the adapter layer's own, and each is enforced
 * structurally rather than by convention: input authority is capped at
 * AGENT_PROPOSAL because no protocol channel is authenticated (AL-01), so an
 * adapter cannot raise authority even in principle.
 */

const ADAPTER_INVARIANTS = [
  "TRANSLATION → NEVER EXECUTION",
  "ADAPTER TRUST → NEVER CALLER AUTHORITY",
  "SCHEMA VALID → NEVER TRUSTED",
  "UNTRUSTED INPUT → STILL TAINTED AFTER TRANSLATION",
];

const STAGES = [
  {
    label: "External protocol",
    note: "A document from outside. A claimed identity, a claimed merchant, claimed amounts.",
    tone: "taint" as const,
  },
  {
    label: "Adapter",
    note: "Translates shape. It assigns no trust, authenticates nothing, and issues nothing.",
    tone: "accent" as const,
  },
  {
    label: "Canonical candidate",
    note: "A CandidateOperation / CandidateOffer / CandidateAuthorizationRequest. A candidate, never an artifact.",
    tone: "accent" as const,
  },
  {
    label: "Security kernel",
    note: "Adjudicates from scratch. Provenance, taint, authority, capability, policy, binding.",
    tone: "secure" as const,
  },
];

export function TranslationBoundary() {
  return (
    <Panel
      title="The translation boundary"
      subtitle="An adapter changes the shape of a message. It changes nothing about how much that message is believed."
    >
      <div className="space-y-4">
        <ol className="flex flex-wrap items-stretch gap-2">
          {STAGES.map((stage, index) => (
            <li key={stage.label} className="flex flex-1 items-center gap-2">
              <div
                className={
                  stage.tone === "taint"
                    ? "min-w-0 flex-1 rounded-lg border border-[color:var(--color-taint)]/30 bg-[color:var(--color-taint)]/[0.05] px-3 py-2.5"
                    : stage.tone === "secure"
                      ? "min-w-0 flex-1 rounded-lg border border-[color:var(--color-secure)]/30 bg-[color:var(--color-secure)]/[0.05] px-3 py-2.5"
                      : "min-w-0 flex-1 rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2.5"
                }
              >
                <p className="text-[11.5px] font-semibold text-[color:var(--color-ink)]">
                  {stage.label}
                </p>
                <p className="mt-1 text-[10.5px] leading-relaxed text-[color:var(--color-ink-4)]">
                  {stage.note}
                </p>
              </div>
              {index < STAGES.length - 1 ? (
                <ArrowRight aria-hidden className="hidden size-3.5 shrink-0 text-[color:var(--color-ink-4)] sm:block" />
              ) : null}
            </li>
          ))}
        </ol>

        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          {ADAPTER_INVARIANTS.map((invariant) => (
            <InvariantCard key={invariant} invariant={invariant} compact />
          ))}
        </div>

        <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
          <p className="label-xs mb-2.5 flex items-center gap-1.5 text-[color:var(--color-ink-4)]">
            <ShieldCheck aria-hidden className="size-3.5" />
            What a translated field carries out the other side
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-left">
              <thead>
                <tr className="border-b border-[color:var(--color-line)]">
                  <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">External field</th>
                  <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">Translated to</th>
                  <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">Authority</th>
                  <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">Trust</th>
                  <th scope="col" className="label-xs py-1.5 text-[color:var(--color-ink-4)]">Taint</th>
                </tr>
              </thead>
              <tbody>
                <Row external="merchant_id" internal="claimed_merchant_id" />
                <Row external="price" internal="claimed_amount_inr" />
                <Row external="tool name" internal="claimed_tool_name" />
                <Row external="authorization ref" internal="external_authorization_reference" />
                <Row external="(unknown fields)" internal="untrusted_metadata" />
              </tbody>
            </table>
          </div>
          <p className="mt-2.5 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
            Notice the naming: every external assertion becomes a <code className="num">claimed_</code>{" "}
            field. Input authority is capped at <code className="num">AGENT_PROPOSAL</code> because
            no protocol channel is authenticated (AL-01) — so an adapter cannot raise authority even
            in principle, and unknown fields are kept as untrusted metadata rather than dropped
            silently or trusted quietly.
          </p>
        </div>
      </div>
    </Panel>
  );
}

function Row({ external, internal }: { external: string; internal: string }) {
  return (
    <tr className="border-b border-[color:var(--color-line)]/60 last:border-b-0">
      <td className="num py-2 pr-3 text-[11.5px] text-[color:var(--color-ink-2)]">{external}</td>
      <td className="num py-2 pr-3 text-[11.5px] text-[color:var(--color-ink)]">{internal}</td>
      <td className="py-2 pr-3"><AuthorityBadge level={20} /></td>
      <td className="py-2 pr-3"><TrustBadge trust="untrusted" /></td>
      <td className="py-2"><TaintBadge tainted /></td>
    </tr>
  );
}
