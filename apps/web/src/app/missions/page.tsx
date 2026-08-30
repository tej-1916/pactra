import type { Metadata } from "next";

import { RecentMissions } from "@/components/command/RecentMissions";
import { MissionLauncher } from "@/components/mission/MissionLauncher";
import { ALL_ROUTES } from "@/components/shell/nav";
import { PageHeader } from "@/components/shell/PageHeader";
import { Panel } from "@/components/ui/Panel";

export const metadata: Metadata = { title: "Mission Workbench" };

const FLOW = [
  { label: "USER INTENT", note: "Free text. Never a security input." },
  { label: "NORMALIZED CONSTRAINTS", note: "Validated through a strict schema at the trusted boundary." },
  { label: "MERCHANT OFFERS", note: "Untrusted payloads from the merchant transport." },
  { label: "TRUST / PROVENANCE", note: "Identity and trust come from the server, never the payload." },
  { label: "POLICY DECISION", note: "Deterministic rules produce ALLOW / REQUIRE_APPROVAL / DENY." },
  { label: "SELECTED OFFER", note: "The one candidate the decision names." },
  { label: "TRANSACTION DIGEST", note: "A commitment to one exact transaction." },
  { label: "AUTHORIZATION", note: "One-time, expiring, consumed atomically." },
  { label: "RISK ADVISORY", note: "Advice. It grants and blocks nothing." },
  { label: "PAYMENT", note: "Derived entirely from the held authorization." },
];

export default function MissionsPage() {
  const blurb = ALL_ROUTES.find((item) => item.href === "/missions")?.blurb;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Mission Workbench"
        title="Agentic commerce, stage by stage"
        description={blurb}
      />

      <Panel
        title="The path a mission takes"
        subtitle="Each stage below is a real component making a real decision. Every mission you run exposes its status, its reason codes, and the authority and taint of what it acted on."
      >
        <ol className="flex flex-wrap gap-1.5">
          {FLOW.map((stage, index) => (
            <li
              key={stage.label}
              title={stage.note}
              className="flex min-w-0 items-center gap-2 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-2.5 py-1.5"
            >
              <span className="num text-[10px] text-[color:var(--color-ink-4)]">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="num text-[11px] font-medium text-[color:var(--color-ink-2)]">
                {stage.label}
              </span>
            </li>
          ))}
        </ol>
      </Panel>

      <MissionLauncher />
      <RecentMissions limit={20} />
    </div>
  );
}
