import { KeyRound, ShieldAlert, ShieldCheck, Sigma } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/format";
import { authorityStatement, describeApprovalScheme } from "@/lib/authorization";
import type { ApprovalScheme } from "@/lib/types/pactra";

/**
 * Who authorized this, stated exactly.
 *
 * The failure mode this component exists to prevent is a screen that renders
 * `POLICY_AUTO` as though a person approved it. So the machine value is printed
 * verbatim, the copy comes from `lib/authorization.ts` where it is
 * test-asserted against a list of overclaims, and every scheme carries its
 * "what this does NOT establish" line — including the one that verified a real
 * signature, because a verified Ed25519 proof is still not a verified identity.
 *
 * No signature, private key, nonce or approval-message byte appears here. The
 * API does not send the first three at all.
 */

const SCHEME_ICON: Record<ApprovalScheme, typeof ShieldCheck> = {
  POLICY_AUTO: Sigma,
  USER_ED25519: KeyRound,
  LEGACY_SERVER: ShieldAlert,
};

export function AuthorizationSchemeCard({
  scheme,
  signingKeyId,
  className,
}: {
  scheme: ApprovalScheme | null | undefined;
  /**
   * The KEY ID only. It is a server-configured identifier, not key material,
   * and there is deliberately no prop on this component that could carry a
   * signature or a private key.
   */
  signingKeyId?: string | null;
  className?: string;
}) {
  const presentation = describeApprovalScheme(scheme);

  if (!presentation) {
    return (
      <div
        className={cn(
          "rounded-md border border-dashed border-[color:var(--color-line)] px-3 py-3",
          className,
        )}
      >
        <p className="text-[12px] text-[color:var(--color-ink-4)]">
          No approval scheme recorded. Nothing has been authorized.
        </p>
      </div>
    );
  }

  const Icon = SCHEME_ICON[presentation.code];

  return (
    <div
      data-testid="authorization-scheme"
      data-scheme={presentation.code}
      className={cn(
        "rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface)] p-3",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Icon
          aria-hidden
          className={cn(
            "size-4 shrink-0",
            presentation.tone === "secure"
              ? "text-[color:var(--color-secure)]"
              : presentation.tone === "critical"
                ? "text-[color:var(--color-critical)]"
                : "text-[color:var(--color-accent)]",
          )}
        />
        <code className="num text-[12.5px] font-semibold text-[color:var(--color-ink)]">
          {presentation.code}
        </code>
        <Badge tone={presentation.tone} variant="outline">
          {presentation.label}
        </Badge>
        {presentation.failsClosedForPayment ? (
          <Badge tone="critical">FAILS CLOSED FOR PAYMENT</Badge>
        ) : null}
      </div>

      <p className="mt-2 text-[12.5px] leading-relaxed font-medium text-[color:var(--color-ink)]">
        {authorityStatement(presentation.code)}
      </p>
      {/* The headline is the sentence that names what this scheme did and did
          NOT do. It belongs on the card, not only in the trace. */}
      <p className="mt-1.5 text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
        {presentation.headline}
      </p>
      <p className="mt-1.5 text-[12px] leading-relaxed text-[color:var(--color-ink-3)]">
        {presentation.detail}
      </p>

      <p className="mt-2 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-2.5 py-2 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
        <span className="label-xs mr-1.5 text-[color:var(--color-ink-4)]">Does not establish</span>
        {presentation.notEstablished}
      </p>

      <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
        <Fact label="Human approved" value={presentation.humanApproved ? "YES" : "NO"} />
        <Fact label="Cryptographic proof" value={presentation.cryptographic ? "YES" : "NO"} />
        {presentation.cryptographic ? (
          <Fact
            label="Signing key ID"
            value={signingKeyId ?? "—"}
            hint="A server-configured public key identifier. Key material is never sent to this console."
          />
        ) : null}
      </dl>
    </div>
  );
}

function Fact({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <dt className="label-xs text-[color:var(--color-ink-4)]" title={hint}>
        {label}
      </dt>
      <dd className="num mt-0.5 truncate text-[11.5px] text-[color:var(--color-ink)]" title={value}>
        {value}
      </dd>
    </div>
  );
}
