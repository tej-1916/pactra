import { Shield, CreditCard, RefreshCw } from "lucide-react";
import type { DemoScenario } from "./demoScenarios";
import { Badge } from "@/components/ui/Badge";
import { AuthoritativeField } from "@/components/ui/Provenance";
import { inr } from "@/lib/format";

export function AuthoritativeEvidencePanel({ scenario }: { scenario: DemoScenario }) {
  const { authoritativePayee, bind, authorization, execute } = scenario;

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="size-4 text-[color:var(--pactra-success)]" />
          <span className="font-display text-[14px] font-bold text-[color:var(--pactra-ink)]">
            AUTHORITATIVE EVIDENCE
          </span>
        </div>
        <Badge tone="secure" variant="outline">
          DEMO SCENARIO
        </Badge>
      </div>

      <div className="space-y-3">
        <AuthoritativeField
          heading="REGISTERED PAYEE (AUTHORITATIVE LOOKUP)"
          value={`${authoritativePayee.registeredPayeeId} · ${authoritativePayee.registeredPayeeName}`}
          source={`Server-registered merchant ID from adapter registration — resolved by PACTRA authority (${authoritativePayee.lookupStatus}).`}
        />

        <AuthoritativeField
          heading="BOUND TOTAL"
          value={`${inr(bind.boundAmountInr)} ${bind.boundCurrency}`}
          source="Bound machine amount and currency from reloaded authoritative offer row."
        />

        <AuthoritativeField
          heading="AUTHORIZATION SCHEME"
          value={authorization.scheme}
          source={
            authorization.scheme === "POLICY_AUTO"
              ? "Deterministic policy activation without human signature."
              : "User Ed25519 cryptographic approval required."
          }
        />

        <AuthoritativeField
          heading="POLICY & BINDING VERSION"
          value={`policy_v2.1 · binding_${bind.bindingVersion} (DEMO BINDING)`}
          source="Policy version covered by the canonical transaction digest."
        />

        <AuthoritativeField
          heading="DEMO PAYMENT STATE"
          value={execute.paymentState}
          source="Synthetic scenario state — not provider runtime evidence."
        />
      </div>

      {/* Provider Handoff & Reconciliation */}
      <div className="pt-3 border-t border-[color:var(--pactra-line)] space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] font-bold text-[color:var(--pactra-ink-muted)] uppercase">
            PROVIDER RECONCILIATION
          </span>
          <CreditCard className="size-3.5 text-[color:var(--pactra-indigo)]" />
        </div>

        <div className="rounded bg-[color:var(--pactra-surface-3)] p-2.5 space-y-1 font-mono text-[11px]">
          <div className="text-[color:var(--pactra-ink-muted)]">Provider Path:</div>
          <div className="text-white font-semibold">Razorpay Test Mode path</div>
          <div className="pt-1 text-[10.5px] text-[color:var(--pactra-ink-secondary)]">
            DEMO MODE: No runtime provider evidence. Scenario outcome is synthetic.
          </div>
        </div>
      </div>

      {/* Lost Provider Response Handling */}
      {scenario.id === "PROVIDER_LOST" && (
        <div className="rounded border border-[#B7791F]/30 bg-[#B7791F]/10 p-3 text-[11px] leading-relaxed text-[color:var(--pactra-ink-secondary)] flex items-start gap-2.5">
          <RefreshCw className="size-4 text-[#B7791F] shrink-0 mt-0.5" />
          <div>
            <span className="font-mono font-bold text-[#B7791F] uppercase">LOST PROVIDER RESPONSE HANDLER:</span>{" "}
            PACTRA records uncertainty (`PROVIDER_PENDING`) and dispatches `RECONCILE_PAYMENT` against provider evidence before treating the payment result as terminal.
          </div>
        </div>
      )}
    </div>
  );
}
