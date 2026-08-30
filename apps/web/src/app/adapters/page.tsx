import type { Metadata } from "next";
import { Check, X } from "lucide-react";

import { SupportMatrix } from "@/components/adapters/SupportMatrix";
import { TranslationBoundary } from "@/components/adapters/TranslationBoundary";
import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { DataTierBadge } from "@/components/ui/DataTier";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { Panel } from "@/components/ui/Panel";
import { ProtocolStatusBadge } from "@/components/ui/StatusBadges";
import { LIMITATIONS, PROTOCOL_SUPPORT } from "@/lib/reference";

export const metadata: Metadata = { title: "Protocol Adapters" };

/**
 * The MCP scoping is rendered from the support matrix's own prose, split on the
 * sentence boundaries the backend wrote. Nothing here paraphrases it upward:
 * "PACTRA supports MCP" without the scope would be false, so the scope travels
 * with the claim.
 */
export default function AdaptersPage() {
  const blurb = ALL_ROUTES.find((item) => item.href === "/adapters")?.blurb;
  const mcp = PROTOCOL_SUPPORT.find((entry) => entry.protocol === "MCP");

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Protocol Adapters"
        title="Translation, not execution"
        description={blurb}
        actions={<DataTierBadge tier="generated" />}
      />

      <TranslationBoundary />

      {mcp ? (
        <Panel
          title="MCP — stated precisely"
          subtitle="The one external-protocol claim PACTRA makes. Its scope is one message shape, and the boundary is drawn where the code actually stops."
          actions={<ProtocolStatusBadge status={mcp.status} />}
        >
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-lg border border-[color:var(--color-secure)]/25 bg-[color:var(--color-secure)]/[0.04] p-3.5">
              <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-secure)]">
                <Check aria-hidden className="size-3" />
                Implemented
              </p>
              <p className="text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
                {mcp.supported}
              </p>
            </div>
            <div className="rounded-lg border border-[color:var(--color-critical)]/25 bg-[color:var(--color-critical)]/[0.04] p-3.5">
              <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-critical)]">
                <X aria-hidden className="size-3" />
                Not implemented
              </p>
              <p className="text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
                {mcp.notSupported}
              </p>
            </div>
          </div>
          <p className="mt-3 rounded border border-[color:var(--color-advisory)]/30 bg-[color:var(--color-advisory)]/[0.05] px-3.5 py-2.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">
            <strong className="text-[color:var(--color-advisory)]">PACTRA is not an MCP server.</strong>{" "}
            No MCP host can connect to it. The status is PARTIAL and the scope appears wherever the
            claim does — &ldquo;Full MCP support&rdquo; would be false, and a status of
            IMPLEMENTED here would be the fake integration this project exists not to ship.
          </p>
        </Panel>
      ) : null}

      <SupportMatrix entries={PROTOCOL_SUPPORT} />

      <Panel
        title="Declared boundaries of the integration surface"
        subtitle="Kept separate from the security-contract and risk-measurement registers. Three different kinds of claim, three lists — folding them together would make a protocol scoping note read like a security defect."
      >
        <div className="grid gap-3 xl:grid-cols-2">
          {LIMITATIONS.adapter.map((limitation) => (
            <LimitationCard
              key={limitation.id}
              id={limitation.id}
              title={limitation.title}
              detail={limitation.detail}
              demonstratedBy={limitation.demonstratedBy}
              register="INTEGRATION SURFACE"
            />
          ))}
        </div>
      </Panel>
    </div>
  );
}
