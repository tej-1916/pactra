import type { Metadata } from "next";

import { AuditInspector } from "@/components/audit/AuditInspector";
import { TamperEvidence } from "@/components/audit/TamperEvidence";
import { BenchmarkProvenance } from "@/components/benchmark/BenchmarkHeader";
import { NAV_ITEMS } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { LimitationCard } from "@/components/ui/LimitationCard";
import { Panel } from "@/components/ui/Panel";
import { loadAttackReport } from "@/lib/api/reports";
import { sortByCategory, summarizeScenarios } from "@/lib/attack-lab";
import { LIMITATIONS } from "@/lib/reference";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Audit & Replay" };

export default async function AuditPage() {
  const attack = await loadAttackReport();
  const blurb = NAV_ITEMS.find((item) => item.href === "/audit")?.blurb;

  const auditScenarios = attack.available
    ? sortByCategory(summarizeScenarios(attack.report)).filter(
        (summary) => summary.result.category === "AUDIT",
      )
    : [];

  const tailTruncation = LIMITATIONS.security.find((entry) =>
    entry.id.startsWith("KL-01"),
  );
  const canonicalization = LIMITATIONS.security.find((entry) => entry.id.startsWith("KL-03"));

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Audit & Replay" title="Tamper-evident history" description={blurb} />

      <Panel title="What the chain does and does not prove">
        <div className="grid gap-4 lg:grid-cols-3">
          <Claim
            title="Detected"
            tone="secure"
            body="Any edit to a hashed field, a deleted middle event, a reordered or renumbered event, and an injected one. Each breaks the event's own hash, the link to the event before it, or the contiguity of the sequence."
          />
          <Claim
            title="Never repaired"
            tone="secure"
            body="Verification rewrites nothing — not event_hash, not previous_hash, not sequence, not payload. There is no repair path to reach, because tamper evidence is worthless if the verifier fixes what it exists to detect."
          />
          <Claim
            title="Not detected"
            tone="advisory"
            body="Tail truncation and whole-chain deletion. A per-mission chain has no anchor outside itself, so removing the last k events leaves a still-valid prefix. This is KL-01 and it is stated on every run rather than discovered from an integration."
          />
        </div>
      </Panel>

      <AuditInspector />

      {attack.available ? (
        <>
          <BenchmarkProvenance
            runId={attack.report.run_id}
            harnessVersion={attack.report.harness_version}
            startedAt={attack.report.started_at}
            scenarios={attack.report.scenarios_selected}
            iterations={attack.report.iterations}
            sourceFile={attack.sourceFile}
          />
          <TamperEvidence scenarios={auditScenarios} />
        </>
      ) : null}

      <Panel
        title="Declared boundaries of the audit contract"
        subtitle="Stated because security credibility increases when limitations are explicit — and because a reader who discovers one from an integration attempt has been misled by its absence."
      >
        <div className="grid gap-3 xl:grid-cols-2">
          {tailTruncation ? (
            <LimitationCard
              id={tailTruncation.id}
              title={tailTruncation.title}
              detail={tailTruncation.detail}
              demonstratedBy={tailTruncation.demonstratedBy}
              register="SECURITY CONTRACT"
            />
          ) : null}
          {canonicalization ? (
            <LimitationCard
              id={canonicalization.id}
              title={canonicalization.title}
              detail={canonicalization.detail}
              demonstratedBy={canonicalization.demonstratedBy}
              register="SECURITY CONTRACT"
            />
          ) : null}
        </div>
      </Panel>
    </div>
  );
}

function Claim({
  title,
  body,
  tone,
}: {
  title: string;
  body: string;
  tone: "secure" | "advisory";
}) {
  return (
    <div
      className={
        tone === "secure"
          ? "rounded-lg border border-[color:var(--color-secure)]/30 bg-[color:var(--color-secure)]/[0.05] p-3.5"
          : "rounded-lg border border-[color:var(--color-advisory)]/30 bg-[color:var(--color-advisory)]/[0.05] p-3.5"
      }
    >
      <h3
        className={
          tone === "secure"
            ? "label-xs text-[color:var(--color-secure)]"
            : "label-xs text-[color:var(--color-advisory)]"
        }
      >
        {title}
      </h3>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">{body}</p>
    </div>
  );
}
