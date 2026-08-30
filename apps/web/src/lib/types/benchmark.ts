/**
 * Shapes of the GENERATED evaluation artifacts.
 *
 * These are report files written by `python -m services.attack_lab.run --out …`
 * and `python -m services.risk_engine.run --evaluate --out …`. They are
 * DEVELOPMENT EVIDENCE, not runtime state, and every surface that renders them
 * is required to say so — see `DataTierBadge`.
 *
 * The files are gitignored on purpose (a benchmark committed by default becomes
 * a number nobody re-measures), so their absence is the normal case on a fresh
 * clone and is rendered as `RUNNER NOT CONNECTED` rather than as zeroes.
 */

export type AttackStatus = "BLOCKED" | "NOT_BLOCKED" | "ERROR" | "INCONCLUSIVE";
export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

/** `services/attack_lab/models.py :: AttackResult` */
export interface AttackResult {
  scenario_id: string;
  scenario_name: string;
  category: string;
  severity: Severity;
  target_invariants: string[];
  backend: string;
  run_id: string;
  iteration: number;
  started_at: string;
  duration_ms: number;
  execute_ms: number;
  status: AttackStatus;
  expected_status: AttackStatus;
  blocked: boolean | null;
  reason_code: string | null;
  expected_reason_code: string | null;
  reason_match: boolean | null;
  invariant_preserved: boolean | null;
  observed_effects: Record<string, unknown>;
  evidence: string | null;
  error: string | null;
  critical: boolean;
}

export interface CategoryMetric {
  category: string;
  runs: number;
  blocked: number;
  not_blocked: number;
  errors: number;
  inconclusive: number;
  block_rate: number | null;
}

export interface LatencyMetric {
  samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  min_ms: number | null;
  max_ms: number | null;
  mean_ms: number | null;
}

/**
 * `services/attack_lab/metrics.py :: AttackMetrics`
 *
 * Every rate is nullable because the harness reports `null` when there was no
 * denominator. A rate with nothing behind it renders as `n/a`, never as 0% or
 * 100% — formatting an absence of evidence as a number is how a benchmark
 * starts lying.
 */
export interface AttackMetrics {
  total_runs: number;
  total_scenarios: number;
  iterations: number;
  attack_runs: number;
  valid_attack_runs: number;
  attacks_blocked: number;
  attacks_not_blocked: number;
  control_runs: number;
  valid_control_runs: number;
  controls_allowed: number;
  controls_blocked: number;
  errors: number;
  inconclusive: number;
  known_limitation_runs: number;
  attack_block_rate: number | null;
  attack_success_rate: number | null;
  invariant_preservation_rate: number | null;
  replay_attack_success_rate: number | null;
  duplicate_payment_rate: number | null;
  false_positive_rate: number | null;
  false_negative_rate: number | null;
  reason_match_rate: number | null;
  invariant_checked_runs: number;
  replay_attempts: number;
  replay_unauthorized_effects: number;
  duplicate_payment_attempts: number;
  duplicate_payment_observations: number;
  reason_code_checked_runs: number;
  reason_code_matches: number;
  latency: LatencyMetric;
  by_category: CategoryMetric[];
  bypassed_scenarios: string[];
  false_positive_scenarios: string[];
  errored_scenarios: string[];
  inconclusive_scenarios: string[];
  critical_failures: string[];
}

export interface SecurityFinding {
  id: string;
  scenario_id: string;
  severity: Severity;
  category: string;
  invariants: string[];
  description: string;
  reproduction: string;
  observed_effect: Record<string, unknown>;
  status: string;
  occurrences: number;
}

export interface KnownLimitationRecord {
  id: string;
  title: string;
  detail: string;
  demonstrated_by: string | null;
}

/** `services/attack_lab/evaluation.py :: AttackRunReport` */
export interface AttackRunReport {
  run_id: string;
  system: string;
  harness_version: string;
  iterations: number;
  scenarios_selected: number;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  postgres_included: boolean;
  postgres_exercised: boolean;
  results: AttackResult[];
  metrics: AttackMetrics;
  findings: SecurityFinding[];
  known_limitations: KnownLimitationRecord[];
}

/** One row of `services/risk_engine/evaluation.py`'s outcome list. */
export interface RiskOutcome {
  scenario_id: string;
  scenario_name: string;
  category: string;
  label: string;
  iteration: number;
  score: number;
  band: string;
  recommendation: string;
  policy_decision: string | null;
  factor_codes: string[];
  history_available: boolean;
  cold_start: boolean;
  audit_chain_verified: boolean;
  assess_ms: number;
  error: string | null;
}

export interface RiskEvalReport {
  run_id: string;
  system: string;
  harness_version: string;
  engine_version: string;
  model_type: string;
  model_version: string;
  score_semantics: string;
  /** The corpus disclosure. Rendered verbatim; never summarized. */
  data_disclosure: string;
  iterations: number;
  scenarios_selected: number;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  outcomes: RiskOutcome[];
  metrics: Record<string, unknown>;
}

/**
 * What a report loader returns.
 *
 * `available: false` is a first-class outcome carrying a machine-readable
 * reason, because "no report on disk" and "the API is down" and "there are zero
 * results" are three different statements and the UI renders three different
 * things.
 */
export type ReportEnvelope<T> =
  | { available: true; report: T; sourceFile: string; loadedAt: string }
  | { available: false; reason: "NO_REPORT_FOUND" | "REPORT_UNREADABLE"; detail: string };
