import limitationsData from "@/data/limitations.generated.json";
import paymentStateMachineData from "@/data/paymentStateMachine.generated.json";
import protocolSupportData from "@/data/protocolSupport.generated.json";
import vocabularyData from "@/data/vocabulary.generated.json";

/**
 * Typed access to the GENERATED reference export.
 *
 * These four files are produced by `apps/web/scripts/export_reference.py`, which
 * imports the real backend modules and serializes them. Nothing here is authored
 * in TypeScript, which is the point: `services/adapters/support.py` exists
 * precisely so a protocol claim cannot drift between the code that implements it
 * and the surface that advertises it, and re-typing that table by hand would
 * reintroduce exactly the drift it was written to prevent.
 *
 * The export contains DECLARATIONS only — never a measured value. Anything
 * counted lives either behind the live API or in a labelled benchmark report.
 */

export interface ProtocolSupportEntry {
  protocol: string;
  actualRole: string;
  family: string | null;
  status: string;
  adapterId: string | null;
  supported: string;
  notSupported: string;
  reason: string;
  specificationSources: string[];
}

export interface LimitationEntry {
  id: string;
  title: string;
  detail: string;
  demonstratedBy: string | null;
}

export const PROTOCOL_SUPPORT = protocolSupportData.entries as ProtocolSupportEntry[];

export const LIMITATIONS = {
  security: limitationsData.security as LimitationEntry[],
  risk: limitationsData.risk as LimitationEntry[],
  adapter: limitationsData.adapter as LimitationEntry[],
};

export const PAYMENT_STATE_MACHINE = {
  states: paymentStateMachineData.states as string[],
  transitions: paymentStateMachineData.transitions as Record<string, string[]>,
  terminal: paymentStateMachineData.terminal as string[],
  uncertain: paymentStateMachineData.uncertain as string[],
};

export const VOCABULARY = {
  invariantContract: vocabularyData.invariantContract as string[],
  missionStates: vocabularyData.missionStates as string[],
  eventTypes: vocabularyData.eventTypes as string[],
  policyOutcomes: vocabularyData.policyOutcomes as string[],
  reasonCodes: vocabularyData.reasonCodes as string[],
  auditReasonCodes: vocabularyData.auditReasonCodes as string[],
  authorityLevels: vocabularyData.authorityLevels as { name: string; value: number }[],
  trustLevels: vocabularyData.trustLevels as string[],
  capabilities: vocabularyData.capabilities as string[],
  attackCategories: vocabularyData.attackCategories as string[],
  maliciousCategories: vocabularyData.maliciousCategories as string[],
  attackStatuses: vocabularyData.attackStatuses as string[],
  severities: vocabularyData.severities as string[],
  riskBands: vocabularyData.riskBands as string[],
  riskRecommendations: vocabularyData.riskRecommendations as string[],
  adapterFamilies: vocabularyData.adapterFamilies as string[],
  adapterWarningCodes: vocabularyData.adapterWarningCodes as string[],
};

/**
 * The five invariants the Command Center leads with.
 *
 * Chosen from the generated contract by exact string match rather than by index,
 * so a reordering of the README block cannot silently change which five appear —
 * and a renamed invariant drops out visibly instead of showing the wrong line.
 */
const HEADLINE_INVARIANTS = [
  "NO VALID AUTHORIZATION → NO PAYMENT",
  "MERCHANT CONTENT → NEVER SYSTEM AUTHORITY",
  "EXPIRED / REPLAYED APPROVAL → PAYMENT IMPOSSIBLE",
  "SAME IDEMPOTENCY KEY → AT MOST ONE LOGICAL PAYMENT",
  "AUDIT EVENT MODIFIED → VERIFICATION FAILURE",
];

export function headlineInvariants(): string[] {
  return HEADLINE_INVARIANTS.filter((invariant) =>
    VOCABULARY.invariantContract.includes(invariant),
  );
}
