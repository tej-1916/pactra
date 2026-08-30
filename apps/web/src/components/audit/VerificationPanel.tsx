import { Panel } from "@/components/ui/Panel";
import { HashDisplay } from "@/components/ui/HashDisplay";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { VerificationBadge } from "@/components/ui/StatusBadges";
import { count } from "@/lib/format";
import type { AuditVerification } from "@/lib/types/pactra";

/**
 * The verification verdict.
 *
 * `events_checked` is presented as "how much of the chain is known-good", not as
 * a table size, because that is what it means on a failure: verification stops
 * at the earliest break and reports the position, and listing every downstream
 * hash it also invalidated would report one act of tampering as dozens of
 * findings.
 *
 * Expected/actual hashes are shown when present. The tampered PAYLOAD is not,
 * and cannot be — the backend deliberately does not put event payloads in a
 * verification result.
 */
export function VerificationPanel({ verification }: { verification: AuditVerification }) {
  return (
    <Panel
      title="Chain verification"
      subtitle="Recomputed server-side over the stored events. Read-only in the strong sense: it repairs nothing it finds, because tamper evidence is worthless if the verifier fixes what it exists to detect."
      actions={<VerificationBadge valid={verification.valid} />}
    >
      <KeyValueGrid columns={3}>
        <KeyValue label="Verdict">
          <ReasonCode code={verification.reason_code} describe />
        </KeyValue>
        <KeyValue
          label="Events verified"
          hint="Events the verifier actually validated — on a failure this is the position of the break, not the size of the table."
        >
          <span className="num">{count(verification.events_checked)}</span>
        </KeyValue>
        <KeyValue label="First invalid sequence">
          <span className="num">
            {verification.first_invalid_sequence === null
              ? "—"
              : `#${verification.first_invalid_sequence}`}
          </span>
        </KeyValue>
        {verification.expected_hash ? (
          <KeyValue label="Expected hash">
            <HashDisplay value={verification.expected_hash} tone="secure" />
          </KeyValue>
        ) : null}
        {verification.actual_hash ? (
          <KeyValue label="Actual hash">
            <HashDisplay value={verification.actual_hash} tone="critical" />
          </KeyValue>
        ) : null}
        {verification.detail ? (
          <KeyValue label="Detail" className="sm:col-span-2 xl:col-span-3">
            <span className="text-[color:var(--color-ink-2)]">{verification.detail}</span>
          </KeyValue>
        ) : null}
      </KeyValueGrid>
    </Panel>
  );
}
