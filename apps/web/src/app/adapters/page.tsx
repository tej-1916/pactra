import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Check, X } from "lucide-react";

import { SupportMatrix } from "@/components/adapters/SupportMatrix";
import { TranslationBoundary } from "@/components/adapters/TranslationBoundary";
import { AdapterFlowDemo } from "@/components/adapters/AdapterFlowDemo";
import { PageHeader } from "@/components/shell/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { Panel } from "@/components/ui/Panel";
import { PageContainer } from "@/components/ui/PageContainer";
import { ProtocolStatusBadge } from "@/components/ui/StatusBadges";
import { LIMITATIONS, PROTOCOL_SUPPORT } from "@/lib/reference";

export const metadata: Metadata = { title: "Protocol Adapters" };

export default function AdaptersPage() {
  const mcp = PROTOCOL_SUPPORT.find((entry) => entry.protocol === "MCP");

  return (
    <PageContainer variant="wide">
      <div className="space-y-6">
        <PageHeader
          eyebrow="PROTOCOL ADAPTERS"
          title="Translate external commerce protocols into canonical PACTRA candidates without granting authority."
          description="Adapters parse and normalize external commerce messages into unprivileged Canonical Candidates. Translation side effects are zero: adapters never issue payments, mint authorization, or mutate policy."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="secure" variant="outline">
                ADAPTER TRUST ≠ CALLER AUTHORITY
              </Badge>
              <Badge tone="advisory" variant="outline">
                TRANSLATION SIDE EFFECTS = ZERO
              </Badge>
            </div>
          }
        />

        {/* 1. Core Ingestion Architecture & Invariants */}
        <TranslationBoundary />

        {/* 2. Interactive Input -> Translation -> Candidate Preview */}
        <AdapterFlowDemo />

        {/* 3. Scoped MCP Reality Check */}
        {mcp ? (
          <Panel
            title="MCP — stated precisely"
            subtitle="The one external tool-protocol claim PACTRA makes. Its scope is one message shape, and the boundary is drawn where the code actually stops."
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

        {/* 4. Support Matrix */}
        <SupportMatrix entries={PROTOCOL_SUPPORT} />

        {/* 5. Cross-Page Navigation */}
        <div className="rounded-lg border border-[#7C78E2]/30 bg-[#15183F]/60 p-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-display text-[13.5px] font-bold text-white">
              Test Untrusted Merchant Proposals in Live Commerce
            </h3>
            <p className="text-[11.5px] text-[color:var(--pactra-ink-secondary)]">
              Experience how candidate merchant offers enter the Security Kernel and are checked across ADMIT, BIND, and EXECUTE stages.
            </p>
          </div>
          <Link
            href="/commerce"
            className="inline-flex items-center gap-1.5 rounded-md border border-[#7C78E2] bg-[#7C78E2]/20 px-3.5 py-1.5 font-mono text-[12px] font-bold text-white transition-colors hover:bg-[#7C78E2]/35"
          >
            Open Live Commerce
            <ArrowRight className="size-3.5 text-[#9D9BE7]" />
          </Link>
        </div>

        {/* 6. Declared Limitations */}
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
    </PageContainer>
  );
}
