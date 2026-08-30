import { Panel } from "@/components/ui/Panel";
import { AuthorityBadge } from "@/components/ui/StatusBadges";
import { AUTHORITY_LEVELS } from "@/lib/semantics";
import { VOCABULARY } from "@/lib/reference";

/**
 * The kernel's own vocabulary, exported from the enums that define it.
 *
 * Present because reason codes and states are the durable handles on everything
 * this system does — an operator who sees `AUTHORIZATION_REPLAY_DETECTED` should
 * be able to find out what else the system can say, without reading Python.
 */
export function VocabularyPanel() {
  return (
    <div className="space-y-5">
      <Panel
        title="Authority lattice"
        subtitle="Ordered, and the ordering is the control: lower-authority data can never modify higher-authority state. USER_POLICY is deliberately not called 'user-signed' — nothing in the current phase cryptographically signs a user policy."
      >
        <ol className="space-y-1.5">
          {[...AUTHORITY_LEVELS].reverse().map((level) => (
            <li
              key={level.name}
              className="flex flex-wrap items-center gap-3 rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] px-3 py-2"
            >
              <span className="num w-8 shrink-0 text-[11px] text-[color:var(--color-ink-4)]">
                {level.value}
              </span>
              <AuthorityBadge level={level.value} />
              <span className="min-w-0 flex-1 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
                {level.note}
              </span>
            </li>
          ))}
        </ol>
      </Panel>

      <div className="grid gap-5 xl:grid-cols-2">
        <CodeList
          title="Reason codes"
          subtitle="What the kernel can say about a decision. These are the durable handles — the console prints them verbatim everywhere."
          items={VOCABULARY.reasonCodes}
        />
        <CodeList
          title="Audit reason codes"
          subtitle="Kept separate from decision reason codes on purpose: folding them together would make AUDIT_VALID look like a reason to permit a payment."
          items={VOCABULARY.auditReasonCodes}
        />
        <CodeList
          title="Event types"
          subtitle="Everything the hash chain can record."
          items={VOCABULARY.eventTypes}
        />
        <CodeList
          title="Capabilities"
          subtitle="Granted only by the server-owned registry. A request cannot widen its own set."
          items={VOCABULARY.capabilities}
        />
        <CodeList title="Mission states" items={VOCABULARY.missionStates} />
        <CodeList
          title="Adapter warning codes"
          subtitle="Attached to every translated envelope that needs one."
          items={VOCABULARY.adapterWarningCodes}
        />
      </div>
    </div>
  );
}

function CodeList({
  title,
  subtitle,
  items,
}: {
  title: string;
  subtitle?: string;
  items: string[];
}) {
  return (
    <Panel title={`${title} (${items.length})`} subtitle={subtitle}>
      <ul className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <li key={item}>
            <code className="num inline-block rounded border border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-2)] px-1.5 py-[3px] text-[10.5px] text-[color:var(--color-ink-2)]">
              {item}
            </code>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
