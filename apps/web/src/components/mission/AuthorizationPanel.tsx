"use client";

import { KeyRound, ShieldCheck, TriangleAlert, Zap } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { HashDisplay } from "@/components/ui/HashDisplay";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { AuthorizationStatusBadge } from "@/components/ui/StatusBadges";
import { inr, timestamp } from "@/lib/format";
import type { ApprovalScheme, Authorization } from "@/lib/types/pactra";

/**
 * The authorization artifact.
 *
 * The bound fields are shown together and labelled as the binding, because that
 * is the security claim: an approval commits to ONE exact transaction, and a
 * merchant that edits its offer after approval cannot keep the authorization
 * valid — the digest covers the offer version.
 *
 * The nonce is not shown and there is no field for it: the API never sends it.
 *
 * ACTIVATION ORIGIN IS RENDERED AS ITS OWN FACT. `POLICY_AUTO` and
 * `USER_ED25519` are different security claims and this panel never lets the
 * weaker one borrow the stronger one's language: a deterministic policy ALLOW
 * is labelled as exactly that and is never called human or signed approval.
 */

interface SchemeCopy {
  label: string;
  tone: "secure" | "advisory" | "critical" | "neutral";
  icon: typeof ShieldCheck;
  summary: string;
  detail: string;
}

const SCHEMES: Record<ApprovalScheme, SchemeCopy> = {
  POLICY_AUTO: {
    label: "POLICY_AUTO",
    tone: "advisory",
    icon: Zap,
    summary: "Deterministic policy ALLOW — not human approval",
    detail:
      "The transaction fell inside the pre-set limits, so the kernel activated this " +
      "authorization itself. Nobody approved it and no signature exists. It is recorded " +
      "as a policy outcome precisely so it is never mistaken for a person deciding.",
  },
  USER_ED25519: {
    label: "USER_ED25519",
    tone: "secure",
    icon: ShieldCheck,
    summary: "Local cryptographic approval proof",
    detail:
      "Activation required an Ed25519 signature over a server-rebuilt canonical message " +
      "committing to this authorization, this mission, and this transaction digest. The " +
      "kernel verified it before activating and re-verifies it before any payment. This " +
      "is one pre-enrolled demo key, not production identity and not non-repudiation.",
  },
  LEGACY_SERVER: {
    label: "LEGACY_SERVER",
    tone: "critical",
    icon: TriangleAlert,
    summary: "Migration-only origin — fails closed for payment",
    detail:
      "A historical row whose origin could not be established as a deterministic ALLOW. " +
      "It is deliberately NOT relabelled as user-approved, and payment verification " +
      "refuses it outright.",
  },
};

export function AuthorizationPanel({ authorization }: { authorization: Authorization }) {
  const scheme = SCHEMES[authorization.approval_scheme] ?? {
    label: authorization.approval_scheme,
    tone: "critical" as const,
    icon: TriangleAlert,
    summary: "Unrecognised activation origin",
    detail:
      "This console does not know this approval scheme. It is shown verbatim rather " +
      "than normalised into a familiar-looking label.",
  };
  const SchemeIcon = scheme.icon;

  return (
    <Panel
      title="Authorization artifact"
      subtitle="One-time, expiring, and bound to exactly one transaction. Activation is an atomic conditional update, so a second approval of the same authorization cannot succeed."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <AuthorizationStatusBadge status={authorization.status} />
          <Badge tone={scheme.tone} variant="outline" icon={<SchemeIcon aria-hidden className="size-3" />} mono>
            {scheme.label}
          </Badge>
        </div>
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg border border-[color:var(--color-accent)]/25 bg-[color:var(--color-accent)]/[0.05] p-3.5">
          <p className="label-xs mb-2.5 flex items-center gap-1.5 text-[color:var(--color-accent)]">
            <KeyRound aria-hidden className="size-3.5" />
            Bound transaction — the approval commits to this and nothing else
          </p>
          <KeyValueGrid columns={3}>
            <KeyValue label="Merchant"><span className="num">{authorization.bound_merchant_id}</span></KeyValue>
            <KeyValue label="Product"><span className="num">{authorization.bound_product_id}</span></KeyValue>
            <KeyValue label="Quantity"><span className="num">{authorization.bound_quantity}</span></KeyValue>
            <KeyValue label="Amount"><span className="num">{inr(authorization.bound_amount_inr)}</span></KeyValue>
            <KeyValue label="Currency"><span className="num">{authorization.bound_currency}</span></KeyValue>
            <KeyValue label="Transaction digest">
              <HashDisplay value={authorization.transaction_digest} head={12} tail={8} />
            </KeyValue>
          </KeyValueGrid>
        </div>

        <div className="rounded-lg border border-[color:var(--color-line)] p-3.5">
          <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-ink-3)]">
            <SchemeIcon aria-hidden className="size-3.5" />
            Activation origin — {scheme.summary}
          </p>
          <p className="text-[11.5px] leading-relaxed text-[color:var(--color-ink-4)]">{scheme.detail}</p>
          {authorization.signing_key_id ? (
            <div className="mt-2.5 border-t border-[color:var(--color-line)] pt-2.5">
              <KeyValue
                label="Signing key id"
                hint="The identifier of the pre-enrolled demo key. The private half never enters PACTRA, this console, or the browser."
              >
                <span className="num">{authorization.signing_key_id}</span>
              </KeyValue>
            </div>
          ) : null}
        </div>

        <KeyValueGrid columns={3}>
          <KeyValue label="Authorization id">
            <HashDisplay value={authorization.authorization_id} head={8} tail={6} />
          </KeyValue>
          <KeyValue label="Issued at"><span className="num">{timestamp(authorization.issued_at)}</span></KeyValue>
          <KeyValue
            label="Expires at"
            hint="Short by design: an approval is a commitment to one transaction at one moment, and a long window is a long replay window."
          >
            <span className="num">{timestamp(authorization.expires_at)}</span>
          </KeyValue>
          <KeyValue label="Consumed at">
            <span className="num">{timestamp(authorization.consumed_at)}</span>
          </KeyValue>
          <KeyValue
            label="Versions bound in"
            className="sm:col-span-2"
            hint="Bound into the digest so an approval cannot be carried across a policy change or an edited offer."
          >
            <span className="num text-[11.5px]">
              binding {authorization.binding_version} · policy {authorization.policy_version} · offer{" "}
              {authorization.offer_version}
            </span>
          </KeyValue>
        </KeyValueGrid>

        <div className="flex flex-wrap items-center gap-2 border-t border-[color:var(--color-line)] pt-3">
          <Badge tone="neutral" variant="outline">SERVER-ISSUED ARTIFACT</Badge>
          <Badge tone={scheme.tone} variant="outline">
            {authorization.approval_scheme === "USER_ED25519" ? "USER-SIGNED ACTIVATION" : "NO USER SIGNATURE"}
          </Badge>
          <p className="text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
            KL-04: signed approval uses ONE pre-enrolled demo key. There is no user or account
            system, no authenticated approval principal, no trusted payment-detail display, and no
            credential rotation — so this is not production identity, not WebAuthn, and not
            non-repudiation. The artifact itself remains server-issued, and the nonce is server-held
            entropy the API never returns, so it is absent here rather than hidden.
          </p>
        </div>
      </div>
    </Panel>
  );
}
