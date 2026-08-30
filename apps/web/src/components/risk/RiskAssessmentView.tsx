import { Info, ShieldAlert } from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { KeyValue, KeyValueGrid } from "@/components/ui/KeyValue";
import { Panel } from "@/components/ui/Panel";
import { RiskBadge } from "@/components/ui/StatusBadges";
import { cn, count } from "@/lib/format";
import { riskBandTone } from "@/lib/semantics";
import type { RiskAssessment } from "@/lib/types/pactra";

/**
 * One advisory assessment, rendered so it cannot be mistaken for a decision.
 *
 * Three things this view does deliberately:
 *
 * * It leads with `RISK SCORE ≠ AUTHORITY` and shows the authoritative policy
 *   outcome BESIDE the advisory one, because the backend copies the policy
 *   decision into the assessment for exactly that purpose.
 * * It calls the number a **Risk Index**, never a fraud probability. The
 *   backend pins `score_semantics = NORMALIZED_RISK_INDEX`, and that string is
 *   printed rather than paraphrased.
 * * It shows `raw_points / saturation_points` so the index can be re-derived by
 *   the reader instead of taken on faith, and every factor's contribution,
 *   which sums to the raw total exactly.
 */
export function RiskAssessmentView({ assessment }: { assessment: RiskAssessment }) {
  const tone = riskBandTone(assessment.band);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[color:var(--color-advisory)]/30 bg-[color:var(--color-advisory)]/[0.06] px-3.5 py-2.5">
        <ShieldAlert aria-hidden className="size-4 shrink-0 text-[color:var(--color-advisory)]" />
        <p className="num text-[12px] font-semibold text-[color:var(--color-advisory)]">
          RISK SCORE ≠ AUTHORITY
        </p>
        <p className="text-[11.5px] leading-relaxed text-[color:var(--color-ink-2)]">
          A CRITICAL band changes no response status and no mission. The deterministic policy
          engine owns every decision; this layer only advises. There is no{" "}
          <code className="num">ALLOW</code> and no <code className="num">DENY</code> in the risk
          vocabulary — those words belong to policy.
        </p>
      </div>

      <Panel
        title="Advisory assessment"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge band={assessment.band} />
            <Badge tone="neutral" variant="outline" mono>
              {assessment.recommendation}
            </Badge>
            <Badge tone="advisory" variant="outline">
              ADVISORY ONLY
            </Badge>
          </div>
        }
      >
        <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
          <div className="rounded-lg border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-4">
            <p className="label-xs text-[color:var(--color-ink-4)]">Risk index</p>
            <p
              className={cn(
                "num mt-1 text-[38px] leading-none font-semibold tracking-tight",
                tone === "secure" && "text-[color:var(--color-secure)]",
                tone === "advisory" && "text-[color:var(--color-advisory)]",
                tone === "critical" && "text-[color:var(--color-critical)]",
                tone === "neutral" && "text-[color:var(--color-ink-2)]",
              )}
            >
              {assessment.score.toFixed(3)}
            </p>
            <div
              className="mt-3 h-1.5 overflow-hidden rounded-full bg-[color:var(--color-surface-3)]"
              role="img"
              aria-label={`Risk index ${assessment.score.toFixed(3)} of 1.000`}
            >
              <div
                className={cn(
                  "h-full rounded-full",
                  tone === "secure" && "bg-[color:var(--color-secure)]",
                  tone === "advisory" && "bg-[color:var(--color-advisory)]",
                  tone === "critical" && "bg-[color:var(--color-critical)]",
                  tone === "neutral" && "bg-[color:var(--color-neutral)]",
                )}
                style={{ width: `${Math.round(assessment.score * 100)}%` }}
              />
            </div>
            <p className="num mt-2.5 text-[11px] text-[color:var(--color-ink-4)]">
              {assessment.raw_points.toFixed(3)} raw points ÷ {assessment.saturation_points.toFixed(2)}{" "}
              saturation
            </p>
            <p className="mt-2 text-[11px] leading-relaxed text-[color:var(--color-ink-4)]">
              <code className="num">{assessment.score_semantics}</code> — a normalized index in
              [0,1], not a probability and not a fraud likelihood. No calibration data exists to
              support a probabilistic reading, so none is claimed.
            </p>
          </div>

          <KeyValueGrid columns={2}>
            <KeyValue
              label="Authoritative policy outcome"
              hint="Copied read-only into the assessment so the advisory value cannot be mistaken for it."
            >
              <span className="num text-[color:var(--color-ink)]">
                {assessment.policy_decision ?? "—"}
              </span>
              {assessment.policy_reason_codes.length > 0 ? (
                <span className="num mt-1 block text-[11px] text-[color:var(--color-ink-4)]">
                  {assessment.policy_reason_codes.join(", ")}
                </span>
              ) : null}
            </KeyValue>
            <KeyValue label="Engine">
              <span className="num">{assessment.engine_version}</span>
              <span className="num mt-1 block text-[11px] text-[color:var(--color-ink-4)]">
                {assessment.model_type} · {assessment.model_version}
              </span>
            </KeyValue>
            <KeyValue
              label="History"
              hint="Scoped by counterparty, never by user — PACTRA has no user identity in its data model, so no per-user baseline is available or claimed."
            >
              <span className="num">
                {assessment.data_quality.history_available
                  ? `${count(assessment.data_quality.history_observations)} observations · scope ${assessment.data_quality.history_scope}`
                  : "not available"}
              </span>
              {assessment.data_quality.cold_start ? (
                <Badge tone="neutral" variant="outline" className="mt-1">
                  COLD START
                </Badge>
              ) : null}
            </KeyValue>
            <KeyValue
              label="Feature availability"
              hint="`None` is not `0`. An unmeasured feature disables its factor rather than scoring as zero."
            >
              <span className="num">
                {count(assessment.data_quality.features_available)} available ·{" "}
                {count(assessment.data_quality.features_unavailable)} unavailable
              </span>
            </KeyValue>
            <KeyValue
              label="Audit chain verified"
              className="sm:col-span-2"
              hint="A false here means every audit-derived feature was read from history that does not verify — stated out loud rather than scored silently."
            >
              <span
                className={cn(
                  "num",
                  assessment.data_quality.audit_chain_verified
                    ? "text-[color:var(--color-secure)]"
                    : "text-[color:var(--color-critical)]",
                )}
              >
                {String(assessment.data_quality.audit_chain_verified)}
              </span>
            </KeyValue>
          </KeyValueGrid>
        </div>
      </Panel>

      <Panel
        title="Factor contributions"
        subtitle="Every line here moved the number, and the contributions sum to the raw point total exactly. A factor that contributed nothing is omitted rather than listed as zero."
        flush
      >
        {assessment.factors.length === 0 ? (
          <p className="px-4 py-4 text-[12px] text-[color:var(--color-ink-3)]">
            No factor contributed. The index is {assessment.score.toFixed(3)} because nothing the
            engine measures crossed a threshold — not because nothing was measured.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left">
              <thead>
                <tr className="border-b border-[color:var(--color-line)]">
                  <th scope="col" className="label-xs py-2 pr-3 pl-4 text-[color:var(--color-ink-4)]">Factor</th>
                  <th scope="col" className="label-xs py-2 pr-3 text-right text-[color:var(--color-ink-4)]">Contribution</th>
                  <th scope="col" className="label-xs py-2 pr-3 text-right text-[color:var(--color-ink-4)]">Weight</th>
                  <th scope="col" className="label-xs py-2 pr-3 text-right text-[color:var(--color-ink-4)]">Observed</th>
                  <th scope="col" className="label-xs py-2 pr-4 text-[color:var(--color-ink-4)]">Explanation</th>
                </tr>
              </thead>
              <tbody>
                {assessment.factors.map((factor) => (
                  <tr key={factor.code} className="border-b border-[color:var(--color-line)]/60 align-top last:border-b-0">
                    <th scope="row" className="py-2.5 pr-3 pl-4 font-normal">
                      <code className="num text-[11.5px] text-[color:var(--color-ink)]">{factor.code}</code>
                      <span className="num mt-0.5 block text-[10.5px] text-[color:var(--color-ink-4)]">
                        {factor.feature}
                      </span>
                      {factor.derived_from_untrusted_evidence ? (
                        <Badge tone="taint" variant="outline" className="mt-1">
                          UNTRUSTED EVIDENCE
                        </Badge>
                      ) : null}
                    </th>
                    <td className="num py-2.5 pr-3 text-right text-[12px] font-semibold text-[color:var(--color-advisory)]">
                      +{factor.contribution.toFixed(3)}
                    </td>
                    <td className="num py-2.5 pr-3 text-right text-[11.5px] text-[color:var(--color-ink-3)]">
                      {factor.weight.toFixed(3)}
                    </td>
                    <td
                      className="num py-2.5 pr-3 text-right text-[11.5px] text-[color:var(--color-ink-2)]"
                      title={factor.observed === null ? undefined : String(factor.observed)}
                    >
                      {observedLabel(factor.observed)}
                    </td>
                    <td className="max-w-[52ch] py-2.5 pr-4 text-[11.5px] leading-relaxed text-[color:var(--color-ink-3)]">
                      {factor.explanation}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-[color:var(--color-line)]">
                  <th scope="row" className="label-xs py-2 pr-3 pl-4 text-[color:var(--color-ink-4)]">
                    Raw points
                  </th>
                  <td className="num py-2 pr-3 text-right text-[12px] font-semibold text-[color:var(--color-ink)]">
                    {assessment.raw_points.toFixed(3)}
                  </td>
                  <td colSpan={3} />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </Panel>

      {assessment.explanation.length > 0 ? (
        <Panel title="Explanation" subtitle="Built from the arithmetic above. Never model-generated.">
          <ul className="space-y-1.5">
            {assessment.explanation.map((line, index) => (
              <li
                key={index}
                className="flex gap-2 text-[12px] leading-relaxed text-[color:var(--color-ink-2)]"
              >
                <Info aria-hidden className="mt-[3px] size-3 shrink-0 text-[color:var(--color-ink-4)]" />
                {line}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}

/**
 * A measured feature value, at readable precision.
 *
 * The full value stays in `title`, because a ratio of 0.9553333333333334 is the
 * number the engine actually used, and rounding it away in the only place it
 * appears would make the arithmetic unverifiable. Integers and booleans print
 * exactly — the shortening is for floats only.
 */
function observedLabel(observed: number | boolean | null): string {
  if (observed === null) return "—";
  if (typeof observed === "boolean") return String(observed);
  return Number.isInteger(observed) ? String(observed) : observed.toFixed(4);
}
