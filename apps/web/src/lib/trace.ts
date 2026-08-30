/**
 * Decision Trace semantics: WHAT HAPPENED, WHY, WHAT CAN HAPPEN NEXT.
 *
 * The trace is an ACTION / SECURITY DECISION record. It is not model
 * chain-of-thought, and nothing in this module may make it look like one.
 *
 * The division of labour is strict, and it is the whole point of the file:
 *
 *   WHAT HAPPENED  a fixed statement of what THIS EVENT TYPE records. It
 *                  describes the contract, not the mission. An event type with
 *                  no entry renders as its own name and nothing else.
 *   WHY            reason codes, the invariant ID, the policy outcome and the
 *                  approval scheme — VERBATIM, from the entry. When the entry
 *                  carries none, the answer is "the source event recorded
 *                  none", never a sentence invented to fill the space.
 *   WHAT NEXT      `next_action`, printed verbatim, with a fixed description of
 *                  what that enum value permits.
 *
 * No function here reads one field and reports another, and none produces a
 * narrative. If the backend did not record it, this module does not say it.
 */

import type {
  DecisionNextAction,
  DecisionStage,
  DecisionTraceEntry,
  DecisionVerdict,
} from "@/lib/types/pactra";
import { DECISION_STAGES } from "@/lib/types/pactra";
import type { Tone } from "@/lib/semantics";

// --------------------------------------------------------------------------- //
// Verdict
// --------------------------------------------------------------------------- //

export interface VerdictPresentation {
  tone: Tone;
  /** One line on what this verdict asserts. Fixed text about the enum value. */
  meaning: string;
}

/**
 * Verdict tone.
 *
 * `REFUSED` is SECURE, not critical, and that is deliberate: a refusal is a
 * control holding, which is PACTRA working rather than PACTRA breaking. The
 * house rule from `lib/semantics.ts` — a blocked action is never rendered red —
 * applies to the trace unchanged.
 *
 * `ACCEPTED` is NEUTRAL rather than green. Most entries in a healthy trace are
 * accepted steps, and painting all of them as successes would leave no contrast
 * for the two entries that actually carry a security result.
 */
export const VERDICT_PRESENTATION: Readonly<Record<DecisionVerdict, VerdictPresentation>> = {
  ACCEPTED: {
    tone: "neutral",
    meaning: "The step was admitted and the mission continued. An ordinary forward move, not a security result.",
  },
  REFUSED: {
    tone: "secure",
    meaning: "A control refused the action. Nothing was authorized and nothing moved — this is the kernel doing its job.",
  },
  PENDING: {
    tone: "advisory",
    meaning: "Recorded and waiting. The outcome is not yet known, and no outcome may be assumed from this entry.",
  },
  SUCCEEDED: {
    tone: "secure",
    meaning: "The action completed with a positive, durable outcome.",
  },
  FAILED: {
    tone: "critical",
    meaning: "The action was attempted and did not complete. This is a failure, distinct from a refusal.",
  },
  IGNORED: {
    tone: "neutral",
    meaning: "Accepted at the boundary and applied to nothing — a duplicate or out-of-order delivery. State did not change.",
  },
  ADVISORY: {
    tone: "advisory",
    meaning: "Advice only. It grants no authority, changes no policy, and authorizes nothing.",
  },
};

export function verdictTone(verdict: DecisionVerdict): Tone {
  return VERDICT_PRESENTATION[verdict]?.tone ?? "neutral";
}

// --------------------------------------------------------------------------- //
// Stage
// --------------------------------------------------------------------------- //

export interface StagePresentation {
  /** What this stage is responsible for. Fixed contract text. */
  purpose: string;
  /** The question the stage answers. */
  question: string;
}

export const STAGE_PRESENTATION: Readonly<Record<DecisionStage, StagePresentation>> = {
  ADMIT: {
    question: "May this even be considered?",
    purpose:
      "Mission and intent parsing, discovery, ingress classification and normalization, ranking, deterministic policy, admission refusals, and advisory risk evidence.",
  },
  BIND: {
    question: "What exactly is authorized, and by whom?",
    purpose:
      "Approval requests and authorization issuance, activation, consumption, and every expiry, revocation, replay or binding refusal.",
  },
  EXECUTE: {
    question: "What actually moved, and what is the durable record of it?",
    purpose:
      "The durable PaymentIntent, outbox and provider dispatch, reconciliation, the payment result, and webhook handling.",
  },
};

export function stageIndex(stage: DecisionStage): number {
  return DECISION_STAGES.indexOf(stage);
}

// --------------------------------------------------------------------------- //
// What happened — per EVENT TYPE, never per mission
// --------------------------------------------------------------------------- //

/**
 * What each event type RECORDS.
 *
 * These are statements about the contract, fixed at build time and identical
 * for every mission. They are not derived from a payload, and they never
 * describe a particular mission's circumstances — that would be an invented
 * explanation wearing a factual voice.
 *
 * An event type with no entry renders as its own name, exactly like an
 * undescribed reason code in `lib/reason-codes.ts`. An unexplained real event
 * type is strictly better than an invented explanation of one.
 */
export const EVENT_TYPE_STATEMENT: Readonly<Record<string, string>> = {
  MISSION_CREATED: "A mission was opened at the trusted API boundary.",
  INTENT_PARSED: "The request was parsed into a typed, structured intent.",
  DISCOVERY_STARTED: "Offer discovery began.",
  OFFERS_RECEIVED: "Merchant payloads arrived. Everything in them is untrusted at this point.",
  OFFERS_NORMALIZED:
    "Merchant payloads were classified and normalized at ingress. Free-form description is dropped here.",
  OFFERS_RANKED: "The deterministic ranker ordered the valid offers and selected one by offer ID.",
  POLICY_DECISION: "Deterministic policy adjudicated the request. This is the authoritative decision.",
  APPROVAL_REQUESTED: "Policy required approval, so an approval challenge was raised.",
  MISSION_DENIED: "The mission was denied and no authority was issued.",
  SECURITY_VIOLATION: "The security kernel refused an action that violated a control.",
  AUTHORIZATION_CREATED: "An authorization artifact was issued, bound to an exact transaction digest.",
  AUTHORIZATION_ACTIVATED: "The authorization became spendable.",
  AUTHORIZATION_CONSUMED:
    "The authorization was atomically spent into a durable PaymentIntent. It cannot be spent again.",
  AUTHORIZATION_EXPIRED: "The approval window closed before the authorization was used.",
  AUTHORIZATION_REVOKED: "The authorization was withdrawn before use.",
  AUTHORIZATION_REPLAY_DETECTED:
    "A second attempt to spend an already-consumed authorization was detected and refused.",
  TRANSACTION_BINDING_FAILURE:
    "The presented transaction did not match the one the authorization was bound to.",
  PAYMENT_INTENT_CREATED: "A durable PaymentIntent was created. It is now the authorized work.",
  PAYMENT_QUEUED: "The intent was handed to the transactional outbox for out-of-band dispatch.",
  PAYMENT_ATTEMPTED: "A provider call was made for this intent.",
  PAYMENT_PROVIDER_TIMEOUT:
    "The provider call timed out. Whether a provider payment exists is unknown until reconciliation.",
  PAYMENT_PROVIDER_UNCERTAIN:
    "The provider outcome is uncertain. The only way out is reconciliation, never an optimistic guess.",
  PAYMENT_RETRY_SCHEDULED: "A retry was scheduled for this intent.",
  PAYMENT_RECONCILED: "The intent's state was reconciled against what the provider actually holds.",
  PAYMENT_SUCCEEDED: "The payment settled. This state is terminal.",
  PAYMENT_FAILED: "The payment did not settle.",
  PAYMENT_INTENT_REUSED:
    "The same idempotency key resolved to the existing intent. No second payment was created.",
  IDEMPOTENCY_CONFLICT:
    "An idempotency key was presented for a materially different transaction, and was refused.",
  OUTBOX_EVENT_DEAD_LETTERED: "An outbox entry exhausted its attempts and was set aside for operators.",
  WEBHOOK_VERIFIED: "A webhook's signature over its raw body verified before the body was read as state.",
  WEBHOOK_REJECTED: "A webhook was rejected. Its payload was never applied.",
  DUPLICATE_WEBHOOK_IGNORED:
    "A delivery already seen. Accepted so the provider stops retrying; applied to nothing.",
  WEBHOOK_OUT_OF_ORDER_IGNORED:
    "A delivery that would move state backwards. Accepted and applied to nothing.",
  RISK_ASSESSED:
    "The advisory risk engine recorded an assessment. It grants no authority and changes no policy.",
};

export function describeEventType(eventType: string): string | null {
  return EVENT_TYPE_STATEMENT[eventType] ?? null;
}

// --------------------------------------------------------------------------- //
// What can happen next
// --------------------------------------------------------------------------- //

export const NEXT_ACTION_MEANING: Readonly<Record<DecisionNextAction, string>> = {
  CONTINUE_ADMIT: "Admission continues. Nothing is authorized and nothing can move money yet.",
  CONTINUE_BIND: "Binding continues toward an authorization over an exact transaction.",
  AWAIT_USER_SIGNATURE:
    "A cryptographic approval proof from the pre-enrolled key is required before anything proceeds.",
  CREATE_PAYMENT_INTENT: "An active authorization may be consumed into a durable PaymentIntent.",
  DISPATCH_PAYMENT: "The queued intent may be dispatched to the provider by the worker.",
  AWAIT_PROVIDER: "A provider outcome is outstanding. No outcome may be assumed while it is.",
  RECONCILE_PAYMENT: "The truth must be re-read from the provider before the state moves again.",
  RETRY_PAYMENT: "A retry is permitted under the same idempotency key.",
  NONE: "No further action follows from this entry.",
};

// --------------------------------------------------------------------------- //
// Ordering and grouping
// --------------------------------------------------------------------------- //

/**
 * The frozen order: ascending by `(evidence.sequence, evidence.event_id)`.
 *
 * Sequence is unique per mission in storage, so the event ID only ever breaks a
 * tie among diagnostic inputs. Sorting here rather than trusting arrival order
 * costs nothing and means a fixture, a hand-assembled list, or a future
 * transport that reorders cannot silently show BIND before ADMIT.
 */
export function orderTrace(entries: readonly DecisionTraceEntry[]): DecisionTraceEntry[] {
  return [...entries].sort((a, b) => {
    if (a.evidence.sequence !== b.evidence.sequence) {
      return a.evidence.sequence - b.evidence.sequence;
    }
    return a.evidence.event_id.localeCompare(b.evidence.event_id);
  });
}

export interface StageGroup {
  stage: DecisionStage;
  entries: DecisionTraceEntry[];
}

/**
 * Group into ADMIT → BIND → EXECUTE.
 *
 * All three stages are ALWAYS returned, in order, including the ones with no
 * entries. A mission refused at BIND has an empty EXECUTE, and rendering that
 * emptiness is the honest answer — dropping the stage would quietly imply the
 * pipeline has only two.
 */
export function groupByStage(entries: readonly DecisionTraceEntry[]): StageGroup[] {
  const ordered = orderTrace(entries);
  return DECISION_STAGES.map((stage) => ({
    stage,
    entries: ordered.filter((entry) => entry.stage === stage),
  }));
}

export interface StageSummary {
  stage: DecisionStage;
  total: number;
  refused: number;
  failed: number;
  pending: number;
  advisory: number;
  /** True once at least one entry has been recorded for this stage. */
  reached: boolean;
}

export function summarizeStage(group: StageGroup): StageSummary {
  const count = (verdict: DecisionVerdict) =>
    group.entries.filter((entry) => entry.verdict === verdict).length;
  return {
    stage: group.stage,
    total: group.entries.length,
    refused: count("REFUSED"),
    failed: count("FAILED"),
    pending: count("PENDING"),
    advisory: group.entries.filter((entry) => entry.advisory).length,
    reached: group.entries.length > 0,
  };
}

/**
 * The last entry, which is the one whose `next_action` still stands.
 *
 * Returned rather than computed into a prediction: the trace states what is
 * permitted next, and this only points at the entry that said so.
 */
export function currentNextAction(
  entries: readonly DecisionTraceEntry[],
): { action: DecisionNextAction; from: DecisionTraceEntry } | null {
  const ordered = orderTrace(entries);
  const last = ordered.at(-1);
  return last ? { action: last.next_action, from: last } : null;
}
