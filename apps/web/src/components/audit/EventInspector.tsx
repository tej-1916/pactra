import { FileCode, Lock } from "lucide-react";
import type { DecisionTraceEntry } from "@/lib/types/pactra";
import { Badge } from "@/components/ui/Badge";

export interface ReplayedAuthEvidence {
  authorizationId?: string | null;
  transactionDigestPrefix?: string | null;
  bindingVersion?: string | null;
}

export function EventInspector({
  entry,
  isDemo,
  replayedAuth,
}: {
  entry: DecisionTraceEntry | null;
  isDemo: boolean;
  replayedAuth?: ReplayedAuthEvidence | null;
}) {
  if (!entry) {
    return (
      <div className="rounded-lg border border-[color:var(--pactra-line)] bg-[color:var(--pactra-surface)] p-6 text-center font-mono text-[12px] text-[color:var(--pactra-ink-muted)]">
        Select a trace event on the timeline to inspect full frozen contract fields.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[color:var(--pactra-line-strong)] bg-[color:var(--pactra-surface)] p-4 space-y-4 min-w-0 max-w-full">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[color:var(--pactra-line)] pb-3">
        <div className="flex items-center gap-2">
          <FileCode className="size-4 text-[color:var(--pactra-indigo)]" />
          <h3 className="font-display text-[15px] font-bold text-[color:var(--pactra-ink)] uppercase tracking-wider">
            EVENT INSPECTOR · SEQ {entry.evidence.sequence}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[11px] font-bold text-[color:var(--pactra-indigo)] bg-[color:var(--pactra-indigo)]/15 px-2 py-0.5 rounded">
            STAGE: {entry.stage}
          </span>
          {isDemo ? (
            <Badge tone="accent" variant="outline">
              DEMO EVENT
            </Badge>
          ) : (
            <Badge tone="secure" variant="outline">
              RUNTIME EVENT
            </Badge>
          )}
        </div>
      </div>

      {/* 12 Frozen Contract Fields Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 font-mono text-[11px]">
        {/* 1. Stage */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">1. STAGE</div>
          <div className="text-[color:var(--pactra-ink)] font-bold">{entry.stage}</div>
        </div>

        {/* 2. Event Type */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">2. EVENT TYPE</div>
          <div className="text-[color:var(--pactra-indigo)] font-bold">{entry.event_type}</div>
        </div>

        {/* 3. Verdict */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">3. VERDICT</div>
          <div
            className={
              entry.verdict === "ACCEPTED" || entry.verdict === "SUCCEEDED"
                ? "text-[color:var(--pactra-success)] font-bold"
                : entry.verdict === "REFUSED" || entry.verdict === "FAILED"
                ? "text-[color:var(--pactra-critical)] font-bold"
                : "text-[color:var(--pactra-warning)] font-bold"
            }
          >
            {entry.verdict}
          </div>
        </div>

        {/* 4. Policy Outcome */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">4. POLICY OUTCOME</div>
          <div className="text-[color:var(--pactra-indigo)] font-bold">{entry.policy_outcome ?? "—"}</div>
        </div>

        {/* 5. Approval Scheme */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">5. APPROVAL SCHEME</div>
          <div className="text-[color:var(--pactra-ink)] font-semibold">{entry.approval_scheme ?? "—"}</div>
        </div>

        {/* 6. Payment State */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">6. PAYMENT STATE</div>
          <div className="text-[color:var(--pactra-ink)] font-semibold">{entry.payment_state ?? "—"}</div>
        </div>

        {/* 7. Next Action */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">7. NEXT ACTION</div>
          <div className="text-[color:var(--pactra-indigo)] font-bold">{entry.next_action}</div>
        </div>

        {/* 8. Advisory Flag */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">8. ADVISORY</div>
          <div className="text-[color:var(--pactra-ink)] font-semibold">{entry.advisory ? "TRUE (ADVISORY ONLY)" : "FALSE"}</div>
        </div>

        {/* 9. Invariant ID */}
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-2.5 space-y-0.5">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">9. INVARIANT ID</div>
          <div className="text-[color:var(--pactra-ink)] font-semibold">{entry.invariant_id ?? "—"}</div>
        </div>
      </div>

      {/* Supplemental Authorization Evidence for BIND Stage */}
      {entry.stage === "BIND" && (
        <div className="rounded border border-[color:var(--pactra-indigo)]/30 bg-[color:var(--pactra-surface-2)] p-3 space-y-2 font-mono text-[11px] min-w-0">
          <div className="flex items-center justify-between border-b border-[color:var(--pactra-line)] pb-1.5">
            <span className="text-[10.5px] font-bold text-[color:var(--pactra-indigo)] uppercase tracking-wider flex items-center gap-1.5">
              <Lock className="size-3 text-[color:var(--pactra-indigo)]" />
              STAGE BIND AUTHORIZATION EVIDENCE
            </span>
            <span className="text-[10px] text-[color:var(--pactra-ink-muted)]">
              {isDemo ? "DEMO BINDING" : "REPLAY STATE EVIDENCE"}
            </span>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 text-[10.5px]">
            <div>
              <span className="text-[color:var(--pactra-ink-muted)]">TRANSACTION DIGEST PREFIX: </span>
              <span className="text-[color:var(--pactra-ink)] font-semibold break-all">
                {isDemo
                  ? "DEMO DIGEST PREFIX (a1b2c3d4...)"
                  : replayedAuth?.transactionDigestPrefix ?? "NOT PRESENT IN REPLAY EVIDENCE"}
              </span>
            </div>
            <div>
              <span className="text-[color:var(--pactra-ink-muted)]">BINDING VERSION: </span>
              <span className="text-[color:var(--pactra-ink)] font-semibold">
                {isDemo
                  ? "v1.0 (DEMO BINDING)"
                  : replayedAuth?.bindingVersion ?? "NOT PRESENT IN REPLAY EVIDENCE"}
              </span>
            </div>
          </div>
          <p className="text-[10px] text-[color:var(--pactra-ink-muted)] pt-1">
            Replay state preserves the canonical digest prefix. Full digest is held in the issued authorization artifact.
          </p>
        </div>
      )}

      {/* 10. Reason Codes */}
      <div className="rounded bg-[color:var(--pactra-surface-2)] p-3 space-y-1 font-mono text-[11px]">
        <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">10. REASON CODES</div>
        {entry.reason_codes.length === 0 ? (
          <div className="text-[color:var(--pactra-ink-muted)]">—</div>
        ) : (
          <div className="flex flex-wrap gap-1 pt-1">
            {entry.reason_codes.map((code) => (
              <span key={code} className="text-[10px] font-bold text-[color:var(--pactra-warning)] bg-[color:var(--pactra-warning)]/15 px-2 py-0.5 rounded border border-[color:var(--pactra-warning)]/30">
                {code}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 11 & 12. Evidence & Recorded At */}
      <div className="grid gap-3 sm:grid-cols-2 font-mono text-[11px]">
        <div className="rounded bg-[color:var(--pactra-surface-2)] p-3 space-y-1">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">11. EVIDENCE PROVENANCE</div>
          <div className="text-[color:var(--pactra-ink-secondary)]">event_id: <span className="text-[color:var(--pactra-indigo)] font-semibold">{entry.evidence.event_id}</span></div>
          <div className="text-[color:var(--pactra-ink-secondary)]">sequence: <span className="text-[color:var(--pactra-indigo)] font-semibold">{entry.evidence.sequence}</span></div>
          <div className="text-[color:var(--pactra-ink-secondary)]">actor: <span className="text-[color:var(--pactra-indigo)] font-semibold">{entry.evidence.actor}</span></div>
        </div>

        <div className="rounded bg-[color:var(--pactra-surface-2)] p-3 space-y-1">
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)] uppercase font-semibold">12. RECORDED AT</div>
          <div className="text-[color:var(--pactra-ink)] font-semibold pt-1">{entry.recorded_at}</div>
          <div className="text-[10px] text-[color:var(--pactra-ink-muted)]">
            {isDemo ? "SYNTHETIC DEMO TRACE TIMESTAMP" : "RUNTIME TIMESTAMP"}
          </div>
        </div>
      </div>
    </div>
  );
}
