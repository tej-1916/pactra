/**
 * Response contracts, transcribed from the FastAPI read models.
 *
 * Every type here has a named counterpart in the backend, and the pairing is
 * recorded in the doc comment so a drift is a findable diff rather than a
 * runtime surprise. Nothing in this file is aspirational: a field that does not
 * exist on the wire does not exist here, which is why — for example — there is
 * no `nonce` on `Authorization` and no `request_fingerprint` on `PaymentIntent`.
 * Those are withheld by the API on purpose, and inventing an optional field for
 * them would invite a component to render one.
 */

/** `apps/api/pactra/main.py :: health` */
export interface HealthResponse {
  status: string;
  app_env: string;
  payment_test_mode: boolean;
}

/** `apps/api/pactra/schemas_api.py :: OfferOut` */
export interface Offer {
  offer_id: string;
  offer_version: string;
  merchant_id: string;
  merchant_name: string;
  merchant_trust: number;
  product_id: string;
  title: string;
  amount_inr: number;
  currency: string;
  rating: number;
  in_stock: boolean;
  valid: boolean;
  rejection_reasons: string[];
  rank: number | null;
}

/** `apps/api/pactra/schemas_api.py :: PolicyDecisionOut` */
export interface PolicyDecision {
  decision: string;
  policy_version: string;
  reason_codes: string[];
  requested_amount: number | null;
  soft_budget: number;
  hard_limit: number;
  selected_offer_id: string | null;
}

/** `apps/api/pactra/schemas_api.py :: MissionOut` */
export interface Mission {
  id: string;
  state: string;
  raw_query: string | null;
  quantity: number;
  offers: Offer[];
  policy_decision: PolicyDecision | null;
  created_at: string;
}

/** `apps/api/pactra/schemas_api.py :: AuditEventOut` */
export interface AuditEvent {
  event_id: string;
  sequence: number;
  event_type: string;
  actor: string;
  payload: Record<string, unknown>;
  previous_hash: string;
  event_hash: string;
  created_at: string;
}

/**
 * `apps/api/pactra/schemas_api.py :: AuthorizationOut`
 *
 * The nonce is absent because the API never sends it. It is server-held
 * material in the digest preimage; there is no optional field for it here.
 */
export interface Authorization {
  authorization_id: string;
  mission_id: string;
  status: string;
  transaction_digest: string;
  binding_version: string;
  policy_version: string;
  offer_version: string;
  issued_at: string;
  expires_at: string;
  consumed_at: string | null;
  bound_merchant_id: string;
  bound_product_id: string;
  bound_quantity: number;
  bound_amount_inr: number;
  bound_currency: string;
}

/** `apps/api/pactra/schemas_api.py :: PaymentIntentOut` */
export interface PaymentIntent {
  payment_intent_id: string;
  mission_id: string;
  authorization_id: string;
  state: string;
  idempotency_key: string;
  amount_inr: number;
  currency: string;
  merchant_id: string;
  provider: string;
  provider_payment_id: string | null;
  attempts: number;
  last_reason_code: string | null;
  created_at: string;
}

/** `packages/schemas/audit.py :: AuditVerificationResult` */
export interface AuditVerification {
  valid: boolean;
  mission_id: string;
  events_checked: number;
  first_invalid_sequence: number | null;
  reason_code: string;
  expected_hash: string | null;
  actual_hash: string | null;
  detail: string | null;
}

/** `packages/schemas/audit.py :: ReplayedAuthorization` */
export interface ReplayedAuthorization {
  authorization_id: string | null;
  status: string | null;
  transaction_digest_prefix: string | null;
  policy_version: string | null;
  offer_version: string | null;
  binding_version: string | null;
  expires_at: string | null;
  consumed_at: string | null;
  bound_merchant_id: string | null;
  bound_product_id: string | null;
  bound_quantity: number | null;
  bound_amount_inr: number | null;
  bound_currency: string | null;
  replay_detected: boolean;
  binding_failures: number;
}

/** `packages/schemas/audit.py :: ReplayedPayment` */
export interface ReplayedPayment {
  payment_intent_id: string | null;
  state: string | null;
  provider: string | null;
  provider_payment_id: string | null;
  idempotency_key: string | null;
  amount_inr: number | null;
  currency: string | null;
  merchant_id: string | null;
  last_reason_code: string | null;
  attempts: number;
  intent_reused: boolean;
  uncertain_episodes: number;
  provider_timeouts: number;
  retries_scheduled: number;
  reconciliations: number;
  dead_lettered: boolean;
  webhooks_verified: number;
  duplicate_webhooks_ignored: number;
  out_of_order_webhooks_ignored: number;
}

/** `packages/schemas/audit.py :: ReplayedSecurityEvent` */
export interface ReplayedSecurityEvent {
  sequence: number;
  event_type: string;
  actor: string;
  reason_code: string | null;
  detail: Record<string, unknown>;
}

/** `packages/schemas/audit.py :: ReplayedRiskAssessment` */
export interface ReplayedRiskAssessment {
  sequence: number;
  assessment_id: string | null;
  score: number | null;
  band: string | null;
  recommendation: string | null;
  engine_version: string | null;
  model_version: string | null;
  factor_codes: string[];
}

/** `packages/schemas/audit.py :: SkippedTransition` */
export interface SkippedTransition {
  sequence: number;
  event_type: string;
  from_state: string;
  to_state: string;
}

/** `packages/schemas/audit.py :: MissionProjection` */
export interface MissionProjection {
  mission_id: string;
  mission_state: string | null;
  events_replayed: number;
  raw_query: string | null;
  quantity: number | null;
  policy_decision: string | null;
  policy_version: string | null;
  policy_reason_codes: string[];
  requested_amount: number | null;
  soft_budget: number | null;
  hard_limit: number | null;
  selected_offer_id: string | null;
  approval_required: boolean;
  approval_granted: boolean;
  raw_offer_count: number | null;
  valid_offer_count: number | null;
  invalid_offer_count: number | null;
  tainted_merchant_fields: string[];
  authorization: ReplayedAuthorization;
  payment: ReplayedPayment;
  security_events: ReplayedSecurityEvent[];
  skipped_transitions: SkippedTransition[];
  risk_assessments: ReplayedRiskAssessment[];
}

/** `packages/schemas/audit.py :: StateComparison` */
export interface StateComparison {
  replay_state: string | null;
  persisted_state: string | null;
  matches: boolean;
  replay_authorization_status: string | null;
  persisted_authorization_status: string | null;
  authorization_matches: boolean | null;
  replay_payment_state: string | null;
  persisted_payment_state: string | null;
  payment_matches: boolean | null;
}

/** `packages/schemas/audit.py :: MissionReplayResult` */
export interface MissionReplay {
  mission_id: string;
  audit_valid: boolean;
  trusted: boolean;
  reason_code: string;
  events_replayed: number;
  verification: AuditVerification;
  state: MissionProjection | null;
  comparison: StateComparison | null;
  unsupported_events: Record<string, unknown>[];
  detail: string | null;
}

/** `services/risk_engine/models.py :: FeatureValue` */
export interface RiskFeatureValue {
  name: string;
  value: number | boolean | null;
  source: string;
  authority: number;
  trust: string;
  derived_from_untrusted_evidence: boolean;
  available: boolean;
  unavailable_reason: string | null;
  source_detail: string;
}

/** `services/risk_engine/models.py :: RiskFactor` */
export interface RiskFactor {
  code: string;
  feature: string;
  contribution: number;
  weight: number;
  observed: number | boolean | null;
  threshold: number | null;
  saturates_at: number | null;
  explanation: string;
  derived_from_untrusted_evidence: boolean;
}

/** `services/risk_engine/models.py :: DataQuality` */
export interface RiskDataQuality {
  history_available: boolean;
  history_observations: number;
  history_scope: string;
  cold_start: boolean;
  features_available: number;
  features_unavailable: number;
  audit_chain_verified: boolean;
}

/**
 * `services/risk_engine/models.py :: RiskAssessment`
 *
 * `score_semantics` is pinned to `NORMALIZED_RISK_INDEX` by the backend and is
 * rendered wherever the score is. It is not a probability, and this type keeps
 * the literal so no component can describe it as one.
 */
export interface RiskAssessment {
  assessment_id: string;
  mission_id: string;
  transaction_digest_prefix: string | null;
  score: number;
  raw_points: number;
  saturation_points: number;
  band: string;
  recommendation: string;
  feature_values: Record<string, RiskFeatureValue>;
  factors: RiskFactor[];
  explanation: string[];
  evaluated_at: string;
  engine_version: string;
  model_type: string;
  model_version: string;
  score_semantics: "NORMALIZED_RISK_INDEX";
  data_quality: RiskDataQuality;
  policy_decision: string | null;
  policy_reason_codes: string[];
  advisory: true;
}
