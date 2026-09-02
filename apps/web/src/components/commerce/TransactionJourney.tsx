import { Lock, ShieldCheck, ArrowDown, FileCode, KeyRound, AlertTriangle } from "lucide-react";
import type { DemoScenario } from "./demoScenarios";
import { Badge } from "@/components/ui/Badge";

export function TransactionJourney({ scenario }: { scenario: DemoScenario }) {
  const { admit, bind, authorization, execute } = scenario;

  return (
    <div className="space-y-4 min-w-0 max-w-full">
      {/* Gate 1: ADMIT */}
      <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-3 relative min-w-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileCode className="size-4 text-[color:var(--pactra-indigo)] shrink-0" />
            <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
              1. GATE 1 · ADMIT
            </span>
          </div>
          <span className="font-mono text-[10px] font-semibold text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/15 px-2 py-0.5 rounded uppercase">
            STAGE: ADMIT
          </span>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          {admit.checks.map((chk) => (
            <div
              key={chk.name}
              className="flex items-center justify-between p-2 rounded bg-[color:var(--pactra-surface-2)] text-[11.5px] font-mono"
            >
              <span className="text-[color:var(--pactra-ink-secondary)]">{chk.name}</span>
              <span
                className={
                  chk.status === "PASSED"
                    ? "text-[color:var(--pactra-success)] font-semibold"
                    : "text-[color:var(--pactra-warning)] font-semibold"
                }
              >
                {chk.status}
              </span>
            </div>
          ))}
        </div>

        <div className="pt-2 border-t border-[color:var(--pactra-line)] flex flex-wrap items-center justify-between text-[10.5px] font-mono gap-2">
          <div>
            verdict: <span className="text-[color:var(--pactra-success)] font-bold">{admit.verdict}</span>
          </div>
          <div>
            policy_outcome: <span className="text-[color:var(--pactra-indigo)] font-bold">{admit.policyOutcome}</span>
          </div>
          <div>
            next_action: <span className="text-[color:var(--pactra-indigo)] font-bold">{admit.nextAction}</span>
          </div>
        </div>
      </div>

      <div className="flex justify-center my-1">
        <ArrowDown className="size-4 text-[color:var(--pactra-indigo)]" />
      </div>

      {/* Gate 2: BIND */}
      <div className="rounded-lg border border-[color:var(--pactra-indigo)]/40 bg-[color:var(--pactra-surface-2)] p-4 space-y-3 relative overflow-hidden min-w-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Lock className="size-4 text-[color:var(--pactra-indigo)] shrink-0" />
            <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
              2. GATE 2 · BIND
            </span>
          </div>
          <Badge tone="accent" variant="outline">
            STAGE: BIND
          </Badge>
        </div>

        <div className="space-y-1.5 bg-[color:var(--pactra-surface-3)] p-3 rounded border border-[color:var(--pactra-line)] font-mono text-[11px] min-w-0">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase tracking-wider font-bold">
            AUTHORITATIVE TRANSACTION DIGEST (DEMO SHA-256)
          </div>
          <div className="text-[color:var(--pactra-indigo)] break-all font-semibold select-all">
            {bind.canonicalDigest}
          </div>
          <div className="flex flex-wrap items-center justify-between pt-1 text-[10px] text-[color:var(--pactra-ink-secondary)] gap-2">
            <span>binding_version: {bind.bindingVersion} (DEMO BINDING)</span>
            <span>bound_amount: ₹{bind.boundAmountInr} {bind.boundCurrency}</span>
            <span>quantity: {bind.boundQuantity}</span>
          </div>
        </div>

        <div className="rounded border border-[color:var(--pactra-indigo)]/30 bg-[color:var(--pactra-indigo)]/10 p-2 text-[10.5px] font-mono text-[color:var(--pactra-ink-secondary)] flex items-center gap-2">
          <AlertTriangle className="size-3.5 text-[color:var(--pactra-indigo)] shrink-0" />
          <span>INVARIANT: Transaction mutation after approval invalidates authorization digest.</span>
        </div>
      </div>

      <div className="flex justify-center my-1">
        <ArrowDown className="size-4 text-[color:var(--pactra-indigo)]" />
      </div>

      {/* AUTHORIZATION GATE (BIND SUB-GATE) */}
      <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-3 min-w-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="size-4 text-[color:var(--pactra-indigo)] shrink-0" />
            <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
              AUTHORIZATION GATE (BIND SUB-GATE)
            </span>
          </div>
          <span
            className={
              authorization.scheme === "POLICY_AUTO"
                ? "font-mono text-[10px] font-semibold text-[color:var(--pactra-success)] bg-[color:var(--pactra-success)]/15 px-2 py-0.5 rounded"
                : "font-mono text-[10px] font-semibold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-2 py-0.5 rounded"
            }
          >
            {authorization.scheme}
          </span>
        </div>

        <p className="text-[12px] text-[color:var(--pactra-ink-secondary)] leading-relaxed">
          {authorization.scheme === "POLICY_AUTO"
            ? "Deterministic policy allowed transaction within soft budget limits. No user signature required."
            : "Soft budget limit exceeded. Cryptographic user approval/signature over bound canonical digest required."}
        </p>

        {authorization.signingKeyId && (
          <div className="font-mono text-[11px] text-[color:var(--pactra-ink-muted)]">
            signing_key_id: <span className="text-[color:var(--pactra-ink)] font-semibold">{authorization.signingKeyId}</span>
          </div>
        )}

        <div className="pt-2 border-t border-[color:var(--pactra-line)] flex flex-wrap items-center justify-between text-[10.5px] font-mono gap-2">
          <div>
            stage: <span className="text-[color:var(--pactra-indigo)] font-bold">BIND</span>
          </div>
          <div>
            admit_outcome: <span className="text-[color:var(--pactra-success)] font-bold">{admit.policyOutcome}</span>
          </div>
          <div>
            auth_status:{" "}
            <span className="text-[color:var(--pactra-ink)] font-bold">
              {authorization.scheme === "POLICY_AUTO" ? "ACTIVE" : "PENDING"}
            </span>
          </div>
          <div>
            next_action: <span className="text-[color:var(--pactra-indigo)] font-bold">{authorization.nextAction}</span>
          </div>
        </div>
      </div>

      <div className="flex justify-center my-1">
        <ArrowDown className="size-4 text-[color:var(--pactra-success)]" />
      </div>

      {/* Gate 3: EXECUTE */}
      <div className="rounded-lg border border-[color:var(--pactra-success)]/40 bg-[color:var(--pactra-surface)] p-4 space-y-3 min-w-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-[color:var(--pactra-success)] shrink-0" />
            <span className="font-mono text-[14px] font-bold text-[color:var(--pactra-ink)]">
              3. GATE 3 · EXECUTE
            </span>
          </div>
          <span
            className={
              execute.paymentState === "SUCCEEDED"
                ? "font-mono text-[10px] font-bold text-[color:var(--pactra-success)] bg-[color:var(--pactra-success)]/15 px-2 py-0.5 rounded"
                : "font-mono text-[10px] font-bold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-2 py-0.5 rounded"
            }
          >
            DEMO payment_state: {execute.paymentState}
          </span>
        </div>

        <div className="font-mono text-[11px] space-y-1 bg-[color:var(--pactra-surface-2)] p-2.5 rounded">
          <div className="text-[color:var(--pactra-ink-muted)]">idempotency_key (DEMO):</div>
          <div className="text-[color:var(--pactra-success)] font-semibold">{execute.idempotencyKey}</div>
        </div>

        <div className="pt-2 border-t border-[color:var(--pactra-line)] flex flex-wrap items-center justify-between text-[10.5px] font-mono gap-2">
          <div className="text-[color:var(--pactra-ink-secondary)]">
            EXECUTION: CREATED ➔ PROCESSING ➔ SUCCEEDED / TIMEOUT
          </div>
          <div className="text-[color:var(--pactra-success)] font-bold">
            INVARIANT: Same idempotency key ➔ at most one logical payment.
          </div>
        </div>
      </div>
    </div>
  );
}
