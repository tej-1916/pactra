import { Info, ShieldCheck, Scale, KeyRound, AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

export function AuthoritySeparationDiagram() {
  const steps = [
    {
      step: "1. RISK SIGNAL",
      badge: "INFORMATIONAL CONTEXT",
      tone: "advisory" as const,
      icon: AlertTriangle,
      role: "Observed Indicators",
      description: "Heuristic features, merchant velocity, price delta, and session history.",
      authorityNote: "AUTHORITY: ZERO",
    },
    {
      step: "2. ADVISORY CONTEXT",
      badge: "OPERATOR ADVICE",
      tone: "advisory" as const,
      icon: Info,
      role: "Normalized Risk Index",
      description: "Scores in [0, 1], bands (LOW..CRITICAL), and recommendations (PROCEED, REVIEW, REQUIRE_STRONGER_APPROVAL, ESCALATE).",
      authorityNote: "ADVISORY ONLY",
    },
    {
      step: "3. POLICY ENGINE",
      badge: "DETERMINISTIC EVALUATION",
      tone: "secure" as const,
      icon: Scale,
      role: "Invariant Adjudication",
      description: "Evaluates hard budget caps, category rules, and registered merchant IDs.",
      authorityNote: "EMITS ALLOW / REQUIRE_APPROVAL / DENY",
    },
    {
      step: "4. AUTHORIZATION GATE",
      badge: "BOUND AUTHORITY",
      tone: "secure" as const,
      icon: KeyRound,
      role: "Transaction Authorization",
      description: "Creates or validates transaction authorization according to the selected approval scheme (POLICY_AUTO, USER_ED25519, LEGACY_SERVER) and bound transaction.",
      authorityNote: "AUTHORITATIVE BINDING",
    },
  ];

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[color:var(--pactra-line)] pb-3">
        <div>
          <h2 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            AUTHORITY SEPARATION ARCHITECTURE
          </h2>
          <p className="text-[12px] text-[color:var(--pactra-ink-muted)]">
            Risk scores inform operator context but never possess transaction authority.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone="advisory" variant="outline">
            ADVISORY ONLY
          </Badge>
          <Badge tone="secure" variant="outline">
            RISK SCORE ≠ AUTHORITY
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {steps.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.step}
              className="relative rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface-2)] p-4 flex flex-col justify-between space-y-3"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)]">
                    {item.step}
                  </span>
                  <Icon className="size-4 text-[color:var(--pactra-indigo)]" />
                </div>
                <div className="font-display text-[13px] font-bold text-[color:var(--pactra-ink)]">
                  {item.role}
                </div>
                <p className="text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
                  {item.description}
                </p>
              </div>

              <div className="border-t border-[color:var(--pactra-line)] pt-2 flex items-center justify-between text-[10px] font-mono font-bold">
                <span className={item.tone === "secure" ? "text-[color:var(--pactra-success)]" : "text-[color:var(--pactra-warning)]"}>
                  {item.authorityNote}
                </span>
                <span className="text-[color:var(--pactra-ink-muted)]">
                  {item.badge}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="rounded border border-[color:var(--pactra-indigo)]/30 bg-[color:var(--pactra-surface-2)] p-3.5 flex items-start gap-3 text-[12px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
        <ShieldCheck className="size-4 text-[color:var(--pactra-indigo)] shrink-0 mt-0.5" />
        <div>
          <strong className="text-[color:var(--pactra-ink)]">Structural Guarantee:</strong> Even if a heuristic risk index reaches{" "}
          <span className="font-mono text-[color:var(--pactra-critical)] font-bold">CRITICAL (1.000)</span>, it cannot
          abort or deny a transaction on its own. It emits recommendation{" "}
          <span className="font-mono text-[color:var(--pactra-warning)]">REQUIRE_STRONGER_APPROVAL</span> or{" "}
          <span className="font-mono text-[color:var(--pactra-warning)]">REVIEW</span> for operator advice. This is strictly
          distinct from the Policy Engine&apos;s deterministic{" "}
          <span className="font-mono text-[color:var(--pactra-warning)]">REQUIRE_APPROVAL</span> or{" "}
          <span className="font-mono text-[color:var(--pactra-critical)] font-bold">DENY</span> outcomes.
        </div>
      </div>
    </div>
  );
}
