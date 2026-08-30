import type { Metadata } from "next";

import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { ArchitectureMap } from "@/components/system/ArchitectureMap";
import { VocabularyPanel } from "@/components/system/VocabularyPanel";
import { DataTierBadge } from "@/components/ui/DataTier";
import { InvariantCard } from "@/components/ui/InvariantCard";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { Panel } from "@/components/ui/Panel";
import { KernelPipeline } from "@/components/viz/KernelPipeline";
import { LIMITATIONS, VOCABULARY } from "@/lib/reference";

export const metadata: Metadata = { title: "System" };

export default function SystemPage() {
  const blurb = ALL_ROUTES.find((item) => item.href === "/system")?.blurb;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="System"
        title="Architecture and contract"
        description={blurb}
        actions={<DataTierBadge tier="generated" />}
      />

      <Panel title="The boundary" subtitle="Untrusted on the left, authorized on the right, and one deterministic kernel between them.">
        <KernelPipeline />
      </Panel>

      <Panel
        title={`Critical invariants — the full test contract (${VOCABULARY.invariantContract.length})`}
        subtitle="Parsed from the project's published contract. These are the properties that must hold even when the reasoning layer, merchant input, or a participating agent is compromised."
      >
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {VOCABULARY.invariantContract.map((invariant) => (
            <InvariantCard key={invariant} invariant={invariant} />
          ))}
        </div>
      </Panel>

      <ArchitectureMap />

      <Panel
        id="limitations"
        title="Declared boundaries"
        subtitle="Three registers, kept apart. A boundary of the SECURITY contract, a boundary of a MEASUREMENT, and a boundary of an INTEGRATION SURFACE are three different kinds of claim — merging them would make a protocol scoping note read like a security defect."
      >
        <div className="space-y-5">
          <Register
            heading="Security contract"
            caption="What the kernel cannot detect or prove, stated so nobody has to discover it from an incident."
            items={LIMITATIONS.security}
            register="SECURITY CONTRACT"
          />
          <Register
            heading="Risk measurement"
            caption="What the reported risk numbers do and do not measure."
            items={LIMITATIONS.risk}
            register="RISK MEASUREMENT"
          />
          <Register
            heading="Integration surface"
            caption="What PACTRA can and cannot say it speaks."
            items={LIMITATIONS.adapter}
            register="INTEGRATION SURFACE"
          />
        </div>
      </Panel>

      <VocabularyPanel />

      <Panel title="Where the numbers on this console come from">
        <div className="grid gap-3 lg:grid-cols-3">
          <Tier
            tier="live"
            body="Read from the PACTRA API for the current request: mission state, offers, authorization, payment, audit events, verification, replay and advisory risk. Real system state."
          />
          <Tier
            tier="generated"
            body="Exported from backend source by apps/web/scripts/export_reference.py — the protocol support matrix, the three limitation registers, the PaymentIntent transition table and the kernel enums. Declarations, not measurements."
          />
          <Tier
            tier="benchmark"
            body="Recorded harness runs read from disk, always shown with a run id, harness version and timestamp. Development evidence about a past measurement. Repository test counts belong to this tier and are never presented as runtime health."
          />
        </div>
      </Panel>
    </div>
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
  items: { id: string; title: string; detail: string; demonstratedBy: string | null }[];
  register: "SECURITY CONTRACT" | "RISK MEASUREMENT" | "INTEGRATION SURFACE";
}) {
  return (
    <section>
      <h3 className="text-[13px] font-semibold tracking-tight text-[color:var(--color-ink)]">
        {heading}{" "}
        <span className="num font-normal text-[color:var(--color-ink-4)]">({items.length})</span>
      </h3>
      <p className="mt-1 mb-3 text-[11.5px] text-[color:var(--color-ink-4)]">{caption}</p>
      <div className="grid gap-3 xl:grid-cols-2">
        {items.map((item) => (
          <LimitationCard
            key={item.id}
            id={item.id}
            title={item.title}
            detail={item.detail}
            demonstratedBy={item.demonstratedBy}
            register={register}
          />
        ))}
      </div>
    </section>
  );
}

function Tier({ tier, body }: { tier: "live" | "generated" | "benchmark"; body: string }) {
  return (
    <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
      <DataTierBadge tier={tier} />
      <p className="mt-2 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">{body}</p>
    </div>
  );
}
