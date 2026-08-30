import { CheckCircle2, CircleAlert, CircleHelp, CircleSlash, Lock, ShieldCheck, ShieldX, TriangleAlert } from "lucide-react";

import { Badge } from "./Badge";
import {
  attackVerdict,
  authorityName,
  authorityTone,
  authorizationStatusTone,
  missionStateTone,
  paymentStateTone,
  policyOutcomeTone,
  protocolStatusTone,
  riskBandTone,
  severityTone,
  trustTone,
  type AttackStatusValue,
} from "@/lib/semantics";

/**
 * Every status in the console renders through one of these.
 *
 * Two properties hold across all of them, and they are accessibility
 * requirements as much as design ones:
 *
 *  * status is never conveyed by colour alone — each badge carries a word, and
 *    the ones that matter most carry an icon too;
 *  * the machine value is always printed verbatim. `SUCCEEDED` shows as
 *    `SUCCEEDED`, not as "Done".
 */

export function SecurityStatusBadge({
  status,
  expectedStatus,
  category,
}: {
  status: AttackStatusValue;
  expectedStatus: AttackStatusValue;
  category: string;
}) {
  const verdict = attackVerdict(status, expectedStatus, category);
  const icon =
    verdict.label === "BLOCKED" ? (
      <ShieldCheck aria-hidden className="size-3.5" />
    ) : verdict.label === "NOT BLOCKED" || verdict.label === "FALSE POSITIVE" ? (
      <ShieldX aria-hidden className="size-3.5" />
    ) : verdict.label === "ERROR" ? (
      <TriangleAlert aria-hidden className="size-3.5" />
    ) : verdict.label === "INCONCLUSIVE" ? (
      <CircleHelp aria-hidden className="size-3.5" />
    ) : verdict.label === "KNOWN LIMITATION" ? (
      <CircleAlert aria-hidden className="size-3.5" />
    ) : (
      <CheckCircle2 aria-hidden className="size-3.5" />
    );

  return (
    <Badge tone={verdict.tone} variant="solid" icon={icon} title={verdict.meaning}>
      {verdict.label}
    </Badge>
  );
}

/** Outlined by construction: severity describes the ATTACK, never the outcome. */
export function SeverityChip({ severity }: { severity: string }) {
  return (
    <Badge
      tone={severityTone(severity)}
      variant="outline"
      title="Attack severity — an ordinal scale, deliberately not CVSS. It describes the attack, not the result."
    >
      {severity}
    </Badge>
  );
}

export function PaymentStateBadge({ state }: { state: string }) {
  return (
    <Badge tone={paymentStateTone(state)} mono>
      {state}
    </Badge>
  );
}

export function MissionStateBadge({ state }: { state: string }) {
  return (
    <Badge tone={missionStateTone(state)} mono>
      {state}
    </Badge>
  );
}

export function PolicyDecisionBadge({ decision }: { decision: string }) {
  return (
    <Badge
      tone={policyOutcomeTone(decision)}
      icon={<Lock aria-hidden className="size-3.5" />}
      title="Deterministic policy outcome. This is the authoritative decision."
    >
      {decision}
    </Badge>
  );
}

export function AuthorizationStatusBadge({ status }: { status: string }) {
  return <Badge tone={authorizationStatusTone(status)} mono>{status}</Badge>;
}

export function AuthorityBadge({ level }: { level: number }) {
  const name = authorityName(level);
  return (
    <Badge tone={authorityTone(level)} variant="outline" mono title={`AuthorityLevel = ${level}`}>
      {name}
    </Badge>
  );
}

export function TrustBadge({ trust }: { trust: string }) {
  return (
    <Badge tone={trustTone(trust)} variant="outline" mono>
      {trust.toUpperCase()}
    </Badge>
  );
}

export function TaintBadge({ tainted }: { tainted: boolean }) {
  return tainted ? (
    <Badge
      tone="taint"
      icon={<CircleSlash aria-hidden className="size-3.5" />}
      title="Taint is sticky: a transformed untrusted value stays untrusted."
    >
      TAINTED
    </Badge>
  ) : (
    <Badge tone="neutral" variant="outline">
      NOT TAINTED
    </Badge>
  );
}

export function RiskBadge({ band }: { band: string }) {
  return (
    <Badge
      tone={riskBandTone(band)}
      variant="outline"
      title="Advisory risk band. CRITICAL is not a synonym for DENY — the loudest thing an advisory layer can say is still advice."
    >
      RISK {band}
    </Badge>
  );
}

export function ProtocolStatusBadge({ status }: { status: string }) {
  return (
    <Badge tone={protocolStatusTone(status)} mono>
      {status}
    </Badge>
  );
}

export function VerificationBadge({ valid }: { valid: boolean }) {
  return valid ? (
    <Badge tone="secure" icon={<ShieldCheck aria-hidden className="size-3.5" />}>
      VALID
    </Badge>
  ) : (
    <Badge tone="critical" icon={<ShieldX aria-hidden className="size-3.5" />}>
      CORRUPTED
    </Badge>
  );
}
