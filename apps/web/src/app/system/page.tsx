import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, History, ShieldAlert, ShoppingBag } from "lucide-react";

import { PageHeader } from "@/components/shell/PageHeader";
import { ArchitectureMap } from "@/components/system/ArchitectureMap";
import { ComponentAvailabilityTable } from "@/components/system/ComponentAvailabilityTable";
import { VocabularyPanel } from "@/components/system/VocabularyPanel";
import { InvariantCard } from "@/components/ui/InvariantCard";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { Panel } from "@/components/ui/Panel";
import { PageContainer } from "@/components/ui/PageContainer";
import { KernelPipeline } from "@/components/viz/KernelPipeline";
import { LIMITATIONS, VOCABULARY } from "@/lib/reference";
import { Badge } from "@/components/ui/Badge";

export const metadata: Metadata = { title: "System" };

export default function SystemPage() {
  return (
    <PageContainer variant="wide">
      <div className="space-y-6">
        <PageHeader
          eyebrow="SYSTEM"
          title="Runtime evidence, component availability, and integration state."
          description="A comprehensive inspection of PACTRA's implemented architecture, deterministic security boundaries, and conservative integration state."
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="secure" variant="outline">
                TIER A: IMPLEMENTATION
              </Badge>
              <Badge tone="accent" variant="outline">
                TIER B: CONFIGURATION
              </Badge>
              <Badge tone="advisory" variant="outline">
                TIER C: RUNTIME EVIDENCE
              </Badge>
            </div>
          }
        />

        {/* 1. Component Availability & Runtime Evidence Matrix */}
        <ComponentAvailabilityTable />

        {/* 2. Three-Stage Security Kernel Pipeline */}
        <Panel
          title="The Security Boundary"
          subtitle="Untrusted merchant inputs on the left, authorized payment execution on the right, and three deterministic kernel stages between them (ADMIT → BIND → EXECUTE)."
        >
          <KernelPipeline />
        </Panel>

        {/* 3. Cross-Page Evidence Navigation */}
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-4 flex flex-col justify-between space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 font-display text-[13.5px] font-bold text-white">
                <History className="size-4 text-[#7C78E2]" />
                Audit & Replay
              </div>
              <p className="text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
                Inspect recorded audit evidence, verification results, and deterministic historical replay.
              </p>
            </div>
            <Link
              href="/audit"
              className="inline-flex items-center justify-between rounded-md border border-[#7C78E2] bg-[#7C78E2]/20 px-3 py-1.5 font-mono text-[11.5px] font-bold text-white transition-colors hover:bg-[#7C78E2]/35"
            >
              Inspect Audit Evidence
              <ArrowRight className="size-3.5 text-[#9D9BE7]" />
            </Link>
          </div>

          <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-4 flex flex-col justify-between space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 font-display text-[13.5px] font-bold text-white">
                <ShieldAlert className="size-4 text-[color:var(--pactra-critical)]" />
                Attack Lab
              </div>
              <p className="text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
                Inspect authored adversarial regression scenarios across PACTRA&apos;s deterministic authority boundaries.
              </p>
            </div>
            <Link
              href="/attack-lab"
              className="inline-flex items-center justify-between rounded-md border border-[color:var(--pactra-critical)]/40 bg-[color:var(--pactra-critical)]/15 px-3 py-1.5 font-mono text-[11.5px] font-bold text-[color:var(--pactra-critical)] transition-colors hover:bg-[color:var(--pactra-critical)]/25"
            >
              Open Attack Lab
              <ArrowRight className="size-3.5" />
            </Link>
          </div>

          <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-4 flex flex-col justify-between space-y-3">
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 font-display text-[13.5px] font-bold text-white">
                <ShoppingBag className="size-4 text-[color:var(--pactra-success)]" />
                Live Commerce
              </div>
              <p className="text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">
                Execute end-to-end purchasing missions from untrusted merchant proposals to verified payment execution.
              </p>
            </div>
            <Link
              href="/commerce"
              className="inline-flex items-center justify-between rounded-md border border-[color:var(--pactra-success)]/40 bg-[color:var(--pactra-success)]/15 px-3 py-1.5 font-mono text-[11.5px] font-bold text-[color:var(--pactra-success)] transition-colors hover:bg-[color:var(--pactra-success)]/25"
            >
              Open Live Commerce
              <ArrowRight className="size-3.5" />
            </Link>
          </div>
        </div>

        {/* 4. Critical Invariant Contract */}
        <Panel
          title={`Critical Invariants — Full Contract (${VOCABULARY.invariantContract.length})`}
          subtitle="Formal properties that must hold even when the reasoning layer, merchant input, or a participating agent is compromised."
        >
          <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
            {VOCABULARY.invariantContract.map((invariant) => (
              <InvariantCard key={invariant} invariant={invariant} />
            ))}
          </div>
        </Panel>

        {/* 5. Architecture Map */}
        <ArchitectureMap />

        {/* 6. Declared Limitation Registers */}
        <Panel
          id="limitations"
          title="Declared Boundaries & Limitation Registers"
          subtitle="Three registers kept strictly separate: Security Contract, Risk Measurement, and Integration Surface."
        >
          <div className="space-y-5">
            <Register
              heading="Security Contract"
              caption="What the kernel cannot detect or prove, stated so nobody has to discover it from an incident."
              items={LIMITATIONS.security}
              register="SECURITY CONTRACT"
            />
            <Register
              heading="Risk Measurement"
              caption="What the reported risk numbers do and do not measure."
              items={LIMITATIONS.risk}
              register="RISK MEASUREMENT"
            />
            <Register
              heading="Integration Surface"
              caption="What PACTRA can and cannot say it speaks."
              items={LIMITATIONS.adapter}
              register="INTEGRATION SURFACE"
            />
          </div>
        </Panel>

        {/* 7. Vocabulary Panel */}
        <VocabularyPanel />

        {/* 8. Console Evidence Tiers */}
        <Panel title="Where the Numbers on This Console Come From">
          <div className="grid gap-3 lg:grid-cols-3">
            <Tier
              tier="live"
              body="Read from the PACTRA API for the current request: mission state, offers, authorization, payment, audit events, verification, replay, and advisory risk. Real system state."
            />
            <Tier
              tier="generated"
              body="Exported from backend source by apps/web/scripts/export_reference.py — protocol support matrix, limitation registers, PaymentIntent transition table, and kernel enums. Declarations, not measurements."
            />
            <Tier
              tier="benchmark"
              body="Recorded harness runs read from disk, always shown with a run id, harness version, and timestamp. Repository test counts belong to this tier and are never presented as runtime health."
            />
          </div>
        </Panel>
      </div>
    </PageContainer>
  );
}

function Register({
  heading,
  caption,
  items,
  register,
}: {
  heading: string;
  caption: string;
  items: Array<{ id: string; title: string; detail: string; demonstratedBy: string | null }>;
  register: "SECURITY CONTRACT" | "RISK MEASUREMENT" | "INTEGRATION SURFACE";
}) {
  return (
    <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-4">
      <div className="border-b border-[color:var(--color-line)] pb-3">
        <h3 className="text-[13.5px] font-semibold tracking-tight text-white">{heading}</h3>
        <p className="mt-1 text-[11.5px] text-[color:var(--pactra-ink-secondary)]">{caption}</p>
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        {items.map((limitation) => (
          <LimitationCard
            key={limitation.id}
            id={limitation.id}
            title={limitation.title}
            detail={limitation.detail}
            demonstratedBy={limitation.demonstratedBy}
            register={register}
          />
        ))}
      </div>
    </div>
  );
}

function Tier({ tier, body }: { tier: "live" | "generated" | "benchmark"; body: string }) {
  return (
    <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
      <p className="label-xs mb-1.5 uppercase tracking-wider text-[color:var(--pactra-indigo)]">
        {tier} Tier
      </p>
      <p className="text-[11.5px] leading-relaxed text-[color:var(--pactra-ink-secondary)]">{body}</p>
    </div>
  );
}
