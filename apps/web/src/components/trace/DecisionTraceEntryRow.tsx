"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { ChevronRight, Fingerprint, Info } from "lucide-react";

import { NextActionChip, VerdictBadge } from "./TraceBadges";
import { Badge } from "@/components/ui/Badge";
import { NotProvided } from "@/components/ui/States";
import { cn, timestamp } from "@/lib/format";
import { describeReasonCode } from "@/lib/reason-codes";
import { describeApprovalScheme } from "@/lib/authorization";
import { describeEventType, NEXT_ACTION_MEANING, verdictTone } from "@/lib/trace";
import type { DecisionTraceEntry } from "@/lib/types/pactra";

/**
 * One entry, answering three questions and inventing none of the answers.
 *
 *   WHAT HAPPENED  a fixed statement about this EVENT TYPE. Identical for every
 *                  mission; it describes the contract, not the circumstances.
 *   WHY            the entry's own reason codes, invariant ID, policy outcome
 *                  and approval scheme, verbatim. When the entry carries none,
 *                  the row says the source event recorded none.
 *   WHAT NEXT      `next_action`, verbatim, with its fixed meaning.
 *
 * Collapsed by default. Reason codes and invariant IDs must be INSPECTABLE
 * without being overwhelming, and a trace of thirty entries that shows every
 * dotted invariant ID at once is a wall, not evidence.
 */
export function DecisionTraceEntryRow({
  entry,
  defaultOpen = false,
}: {
  entry: DecisionTraceEntry;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const statement = describeEventType(entry.event_type);
  const scheme = describeApprovalScheme(entry.approval_scheme);
  const tone = verdictTone(entry.verdict);
  const hasWhy =
    entry.reason_codes.length > 0 ||
    entry.invariant_id !== null ||
    entry.policy_outcome !== null ||
    entry.approval_scheme !== null;

  return (
    <li
      data-testid="decision-trace-entry"
      data-stage={entry.stage}
      data-verdict={entry.verdict}
      data-sequence={entry.evidence.sequence}
      className="relative"
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={cn(
          "flex w-full items-start gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
          "border-[color:var(--color-line)] bg-[color:var(--color-surface)] hover:bg-[color:var(--color-surface-2)]",
          entry.verdict === "REFUSED" && "border-l-[3px] border-l-[color:var(--color-secure)]",
          entry.verdict === "FAILED" && "border-l-[3px] border-l-[color:var(--color-critical)]",
          entry.advisory && "border-l-[3px] border-l-[color:var(--color-advisory)]",
        )}
      >
        <span className="num mt-[3px] w-7 shrink-0 text-right text-[10.5px] text-[color:var(--color-ink-4)]">
          {entry.evidence.sequence}
        </span>

        <motion.span
          aria-hidden
          animate={{ rotate: open ? 90 : 0 }}
          transition={{ duration: 0.16, ease: "easeOut" }}
          className="mt-[2px] shrink-0 text-[color:var(--color-ink-4)]"
        >
          <ChevronRight className="size-3.5" />
        </motion.span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <code className="num text-[12px] font-semibold text-[color:var(--color-ink)]">
              {entry.event_type}
            </code>
            <VerdictBadge verdict={entry.verdict} />
            {entry.advisory ? (
              <Badge tone="advisory" variant="outline" title="Advisory evidence. It grants no authority.">
                ADVISORY
              </Badge>
            ) : null}
            {entry.reason_codes.length > 0 ? (
              <span className="num text-[10.5px] text-[color:var(--color-ink-4)]">
                {entry.reason_codes.length} reason code
                {entry.reason_codes.length === 1 ? "" : "s"}
              </span>
            ) : null}
          </span>

          <span className="mt-1 block text-[12px] leading-relaxed text-[color:var(--color-ink-2)]">
            {statement ?? (
              <span className="text-[color:var(--color-ink-4)]">
                No fixed statement is recorded in this build for{" "}
                <code className="num">{entry.event_type}</code>. The event type is shown as
                received rather than described from a guess.
              </span>
            )}
          </span>
        </span>

        <span className="hidden shrink-0 flex-col items-end gap-1 sm:flex">
          <NextActionChip action={entry.next_action} />
          <span className="num text-[10px] text-[color:var(--color-ink-4)]">
            {timestamp(entry.recorded_at)}
          </span>
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div className="mt-1.5 ml-[42px] space-y-3 rounded-md border border-[color:var(--color-line)] bg-[color:var(--color-surface-2)] p-3">
              {/* -------------------------------------------------- WHY -- */}
              <section>
                <h4 className="label-xs text-[color:var(--color-ink-4)]">Why</h4>
                {hasWhy ? (
                  <div className="mt-1.5 space-y-2">
                    {entry.reason_codes.length > 0 ? (
                      <ul className="space-y-1">
                        {entry.reason_codes.map((code) => (
                          <li key={code} className="text-[11.5px] leading-snug">
                            <code
                              className={cn(
                                "num font-semibold",
                                tone === "secure"
                                  ? "text-[color:var(--color-secure)]"
                                  : "text-[color:var(--color-ink)]",
                              )}
                            >
                              {code}
                            </code>
                            {describeReasonCode(code) ? (
                              <span className="text-[color:var(--color-ink-3)]">
                                {" "}
                                — {describeReasonCode(code)}
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : null}

                    {entry.invariant_id ? (
                      <p className="text-[11.5px] text-[color:var(--color-ink-3)]">
                        <span className="label-xs text-[color:var(--color-ink-4)]">Invariant</span>{" "}
                        <code className="num text-[color:var(--color-ink-2)]">
                          {entry.invariant_id}
                        </code>
                      </p>
                    ) : null}

                    {entry.policy_outcome ? (
                      <p className="text-[11.5px] text-[color:var(--color-ink-3)]">
                        <span className="label-xs text-[color:var(--color-ink-4)]">
                          Policy outcome
                        </span>{" "}
                        <code className="num font-semibold text-[color:var(--color-ink)]">
                          {entry.policy_outcome}
                        </code>{" "}
                        — the deterministic, authoritative decision.
                      </p>
                    ) : null}

                    {scheme ? (
                      <p className="text-[11.5px] leading-snug text-[color:var(--color-ink-3)]">
                        <span className="label-xs text-[color:var(--color-ink-4)]">
                          Approval scheme
                        </span>{" "}
                        <code className="num font-semibold text-[color:var(--color-ink)]">
                          {scheme.code}
                        </code>{" "}
                        — {scheme.headline}
                      </p>
                    ) : null}

                    {entry.payment_state ? (
                      <p className="text-[11.5px] text-[color:var(--color-ink-3)]">
                        <span className="label-xs text-[color:var(--color-ink-4)]">
                          Payment state
                        </span>{" "}
                        <code className="num font-semibold text-[color:var(--color-ink)]">
                          {entry.payment_state}
                        </code>
                      </p>
                    ) : null}
                  </div>
                ) : (
                  <p className="mt-1.5 flex items-start gap-1.5 text-[11.5px] leading-snug text-[color:var(--color-ink-4)]">
                    <Info aria-hidden className="mt-[2px] size-3 shrink-0" />
                    The source event recorded no reason code, invariant ID, policy outcome or
                    approval scheme. Nothing is inferred to fill the gap.
                  </p>
                )}
              </section>

              {/* -------------------------------------------- WHAT NEXT -- */}
              <section>
                <h4 className="label-xs text-[color:var(--color-ink-4)]">What can happen next</h4>
                <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[11.5px] leading-snug text-[color:var(--color-ink-3)]">
                  <NextActionChip action={entry.next_action} />
                  <span>{NEXT_ACTION_MEANING[entry.next_action]}</span>
                </p>
              </section>

              {/* ---------------------------------------------- EVIDENCE -- */}
              <section>
                <h4 className="label-xs flex items-center gap-1.5 text-[color:var(--color-ink-4)]">
                  <Fingerprint aria-hidden className="size-3" />
                  Evidence
                </h4>
                <dl className="mt-1.5 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-3">
                  <Evidence label="Event ID" value={entry.evidence.event_id} />
                  <Evidence label="Sequence" value={String(entry.evidence.sequence)} />
                  <Evidence label="Actor" value={entry.evidence.actor} />
                  <Evidence label="Recorded at" value={timestamp(entry.recorded_at)} />
                  <div className="sm:col-span-2">
                    <dt className="label-xs text-[color:var(--color-ink-4)]">Raw payload</dt>
                    <dd className="mt-1">
                      <NotProvided what="The raw audit payload" />
                      <span className="ml-1.5 text-[10.5px] text-[color:var(--color-ink-4)]">
                        The trace is an allow-listed projection. It carries no payload, signature,
                        nonce, key material or model reasoning.
                      </span>
                    </dd>
                  </div>
                </dl>
              </section>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </li>
  );
}

function Evidence({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="label-xs text-[color:var(--color-ink-4)]">{label}</dt>
      <dd className="num mt-0.5 truncate text-[11px] text-[color:var(--color-ink-2)]" title={value}>
        {value}
      </dd>
    </div>
  );
}
