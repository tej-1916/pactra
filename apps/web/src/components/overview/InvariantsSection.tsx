import { Check, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";

export function InvariantsSection() {
  const invariants = [
    {
      condition: "NO VALID AUTHORIZATION",
      enforcement: "NO PAYMENT DISPATCHED",
      desc: "No funds leave the system unless a valid POLICY_AUTO or USER_ED25519 authorization exists.",
    },
    {
      condition: "LLM REASONING OUTPUT",
      enforcement: "NEVER AUTHORIZATION",
      desc: "Model output is an untrusted proposal. Authority exists strictly within the deterministic policy kernel.",
    },
    {
      condition: "TRANSACTION MUTATED AFTER APPROVAL",
      enforcement: "AUTHORIZATION INVALIDATED",
      desc: "Altering price, payee, or items breaks the canonical digest and instantly voids approval.",
    },
    {
      condition: "EXPIRED / REPLAYED APPROVAL",
      enforcement: "PAYMENT IMPOSSIBLE",
      desc: "Nonces and timestamp windows guarantee each authorization can execute at most once.",
    },
    {
      condition: "DENIED CAPABILITY / SCOPE",
      enforcement: "EXECUTOR UNREACHABLE",
      desc: "Unapproved merchant actions or unauthorized API calls are halted at Gate 1 ADMIT.",
    },
    {
      condition: "SAME IDEMPOTENCY KEY",
      enforcement: "AT MOST ONE LOGICAL PAYMENT",
      desc: "Prevents double-charging or duplicate provider calls regardless of retry attempts.",
    },
    {
      condition: "ADVISORY RISK SCORE",
      enforcement: "ADVISORY ONLY",
      desc: "Risk index guides monitoring — it never grants authority or overrides policy rules.",
    },
  ];

  return (
    <Panel
      title="CRITICAL SECURITY INVARIANTS"
      subtitle="Deterministic properties that hold unconditionally, even when the model, merchant, or agent is compromised."
      actions={
        <Badge tone="accent" variant="outline" icon={<ShieldCheck className="size-3.5" />}>
          CORE INVARIANTS
        </Badge>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {invariants.map((item, idx) => (
          <div
            key={item.condition}
            className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-3.5 flex flex-col justify-between"
          >
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)]">
                <span className="flex size-4 items-center justify-center rounded-full bg-[color:var(--pactra-indigo)]/15 text-[10px]">
                  {idx + 1}
                </span>
                <span>{item.condition}</span>
              </div>
              <div className="font-mono text-[12px] font-bold text-[color:var(--pactra-ink)] flex items-center gap-1.5">
                <Check className="size-3.5 text-[color:var(--pactra-success)] shrink-0" />
                <span>➔ {item.enforcement}</span>
              </div>
              <p className="text-[12px] leading-snug text-[color:var(--pactra-ink-secondary)] pt-1">
                {item.desc}
              </p>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11.5px] text-[color:var(--pactra-ink-muted)]">
        <Link href="/system" className="text-[color:var(--pactra-indigo)] font-semibold hover:underline">
          Explore all contract invariants on the System page ➔
        </Link>
      </p>
    </Panel>
  );
}
