import { ArrowRight, Ban, ShieldCheck, ShieldX } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { ReasonCode } from "@/components/ui/ReasonCode";
import { cn, count } from "@/lib/format";
import type { MissionReplay } from "@/lib/types/pactra";

const STEPS = ["AUDIT HISTORY", "VERIFY", "PURE REPLAY", "RECONSTRUCTED STATE"];

/**
 * Deterministic replay of a mission from its event history alone.
 *
 * Two things this panel is careful about:
 *
 * `trusted` is displayed separately from `audit_valid`, because a chain can
 * verify and still fail to replay (an event type this build does not know).
 * Collapsing them would hide "history is intact but uninterpretable" behind
 * "history is not intact".
 *
 * The side-effect banner states zeroes, and they are STRUCTURAL rather than
 * measured: the replay route is documented read-only, appends no event, mutates
 * no mission and calls no provider. The panel says which of those it is, so
 * nobody reads a structural guarantee as a counter that happened to be zero.
 */
export function ReplayPanel({ replay }: { replay: MissionReplay }) {
  const projection = replay.state;
  const comparison = replay.comparison;

  return (
    <Panel
      title="Deterministic replay"
      subtitle="Mission state reconstructed purely from the ordered event log. Nothing is read from the live mission, offer, authorization or payment rows — a projection that consulted current state would verify nothing at all."
      actions={
        replay.trusted ? (
          <Badge tone="secure" icon={<ShieldCheck aria-hidden className="size-3.5" />}>
            TRUSTED PROJECTION
          </Badge>
        ) : (
          <Badge tone="critical" icon={<ShieldX aria-hidden className="size-3.5" />}>
            REPLAY REFUSED
          </Badge>
        )
      }
    >
      <div className="space-y-4">
        <ol className="flex flex-wrap items-center gap-1.5">
          {STEPS.map((step, index) => (
            <li key={step} className="flex items-center gap-1.5">
              <span
                className={cn(
                  "num rounded border px-2.5 py-1 text-[11px] font-semibold",
                  replay.trusted
                    ? "border-[color:var(--color-secure)]/35 bg-[color:var(--color-secure)]/[0.07] text-[color:var(--color-secure)]"
                    : index < 2
                      ? "border-[color:var(--color-line-strong)] bg-[color:var(--color-surface-3)] text-[color:var(--color-ink-2)]"
                      : "border-[color:var(--color-line)] text-[color:var(--color-ink-4)]",
                )}
              >
                {step}
              </span>
              {index < STEPS.length - 1 ? (
                <ArrowRight aria-hidden className="size-3 text-[color:var(--color-ink-4)]" />
              ) : null}
            </li>
          ))}
        </ol>

        <div className="rounded-lg border border-[color:var(--color-secure)]/30 bg-[color:var(--color-secure)]/[0.05] px-4 py-3">
          <p className="label-xs mb-2 flex items-center gap-1.5 text-[color:var(--color-secure)]">
            <Ban aria-hidden className="size-3.5" />
            Replay side effects
          </p>
          <div className="grid gap-2 sm:grid-cols-3">
            <SideEffect label="Provider calls" />
            <SideEffect label="Payments created" />
            <SideEffect label="Authorizations created" />
          </div>
          <p className="mt-2.5 text-[11px] leading-relaxed text-[color:var(--color-ink-3)]">
            These are structural, not counted: the replay route appends no audit event, mutates no
            mission, and holds no import path to the payment executor. A mismatch it finds against
            persisted state is <em>reported and never repaired</em> — replay is observability here,
            not recovery.
          </p>
        </div>

        <KeyValueGrid columns={3}>
          <KeyValue label="Outcome">
            <ReasonCode code={replay.reason_code} describe />
          </KeyValue>
          <KeyValue label="Audit valid">
            <span className={replay.audit_valid ? "text-[color:var(--color-secure)]" : "text-[color:var(--color-critical)]"}>
              {String(replay.audit_valid)}
            </span>
          </KeyValue>
          <KeyValue label="Events replayed">
            <span className="num">{count(replay.events_replayed)}</span>
          </KeyValue>
        </KeyValueGrid>

        {projection ? (
          <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
            <p className="label-xs mb-2.5 text-[color:var(--color-ink-4)]">Reconstructed state</p>
            <KeyValueGrid columns={3}>
              <KeyValue label="Mission state">
                <span className="num">{projection.mission_state ?? "—"}</span>
              </KeyValue>
              <KeyValue label="Policy decision">
                <span className="num">{projection.policy_decision ?? "—"}</span>
              </KeyValue>
              <KeyValue label="Authorization status">
                <span className="num">{projection.authorization.status ?? "—"}</span>
              </KeyValue>
              <KeyValue label="Payment state">
                <span className="num">{projection.payment.state ?? "—"}</span>
              </KeyValue>
              <KeyValue label="Replay detected" hint="A consumed authorization was presented again.">
                <span className={cn("num", projection.authorization.replay_detected && "text-[color:var(--color-critical)]")}>
                  {String(projection.authorization.replay_detected)}
                </span>
              </KeyValue>
              <KeyValue label="Binding failures">
                <span className="num">{count(projection.authorization.binding_failures)}</span>
              </KeyValue>
              <KeyValue label="Uncertain episodes" hint="Times the payment entered PROVIDER_PENDING.">
                <span className="num">{count(projection.payment.uncertain_episodes)}</span>
              </KeyValue>
              <KeyValue label="Reconciliations">
                <span className="num">{count(projection.payment.reconciliations)}</span>
              </KeyValue>
              <KeyValue label="Security events recorded">
                <span className="num">{count(projection.security_events.length)}</span>
              </KeyValue>
            </KeyValueGrid>
          </div>
        ) : (
          <p className="rounded border border-[color:var(--color-critical)]/30 bg-[color:var(--color-critical)]/[0.05] px-3.5 py-3 text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
            No reconstructed state is attached. That is deliberate: a chain that does not verify
            yields <code className="num">trusted: false</code> with nothing to read past the flag —
            returning a projection alongside a warning would hand callers exactly the object they
            would read past the warning to reach.
          </p>
        )}

        {comparison ? (
          <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3.5">
            <p className="label-xs mb-2.5 text-[color:var(--color-ink-4)]">
              Replayed vs. persisted — diagnostic only
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[460px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-[color:var(--color-line)]">
                    <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">Aspect</th>
                    <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">Replayed</th>
                    <th scope="col" className="label-xs py-1.5 pr-3 text-[color:var(--color-ink-4)]">Persisted</th>
                    <th scope="col" className="label-xs py-1.5 text-[color:var(--color-ink-4)]">Matches</th>
                  </tr>
                </thead>
                <tbody>
                  <ComparisonRow
                    aspect="Mission state"
                    replayed={comparison.replay_state}
                    persisted={comparison.persisted_state}
                    matches={comparison.matches}
                  />
                  <ComparisonRow
                    aspect="Authorization"
                    replayed={comparison.replay_authorization_status}
                    persisted={comparison.persisted_authorization_status}
                    matches={comparison.authorization_matches}
                  />
                  <ComparisonRow
                    aspect="Payment"
                    replayed={comparison.replay_payment_state}
                    persisted={comparison.persisted_payment_state}
                    matches={comparison.payment_matches}
                  />
                </tbody>
              </table>
            </div>
          </div>
        ) : null}

        {replay.unsupported_events.length > 0 ? (
          <pre className="num overflow-auto rounded border border-[color:var(--color-critical)]/30 bg-[color:var(--color-critical)]/[0.05] p-3 text-[11px] text-[color:var(--color-ink-2)]">
            {JSON.stringify(replay.unsupported_events, null, 2)}
          </pre>
        ) : null}
      </div>
    </Panel>
  );
}

function SideEffect({ label }: { label: string }) {
  return (
    <div className="rounded border border-[color:var(--color-line)] bg-[color:var(--color-surface)] px-3 py-2">
      <p className="label-xs text-[color:var(--color-ink-4)]">{label}</p>
      <p className="num mt-0.5 text-[19px] leading-none font-semibold text-[color:var(--color-secure)]">0</p>
    </div>
  );
}

function ComparisonRow({
  aspect,
  replayed,
  persisted,
  matches,
}: {
  aspect: string;
  replayed: string | null;
  persisted: string | null;
  matches: boolean | null;
}) {
  return (
    <tr className="border-b border-[color:var(--color-line)]/60 last:border-b-0">
      <th scope="row" className="py-1.5 pr-3 text-[11.5px] font-normal text-[color:var(--color-ink-2)]">
        {aspect}
      </th>
      <td className="num py-1.5 pr-3 text-[11.5px] text-[color:var(--color-ink)]">{replayed ?? "—"}</td>
      <td className="num py-1.5 pr-3 text-[11.5px] text-[color:var(--color-ink)]">{persisted ?? "—"}</td>
      <td
        className={cn(
          "num py-1.5 text-[11.5px] font-semibold",
          matches === true && "text-[color:var(--color-secure)]",
          matches === false && "text-[color:var(--color-critical)]",
          matches === null && "text-[color:var(--color-ink-4)]",
        )}
      >
        {matches === null ? "n/a" : String(matches)}
      </td>
    </tr>
  );
}
