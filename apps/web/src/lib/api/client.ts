"use client";

import type { ApiResult } from "./result";
import { parseErrorBody } from "./result";
import type {
  ApprovalChallenge,
  ApprovalSubmission,
  Authorization,
  AuditEvent,
  AuditVerification,
  Mission,
  MissionReplay,
  PaymentIntent,
  RiskAssessment,
} from "@/lib/types/pactra";

/**
 * The browser-side client.
 *
 * It talks ONLY to this application's own `/api/pactra/*` route handlers, never
 * to the PACTRA API directly. That keeps the backend origin out of the client
 * bundle, removes CORS from the picture entirely, and means there is exactly
 * one server-side place (`lib/api/server.ts`) where a header could ever be
 * attached — so a credential cannot be introduced from a component.
 */

async function call<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  try {
    const response = await fetch(path, { ...init, cache: "no-store" });
    const text = await response.text();
    const parsed: unknown = text.length > 0 ? JSON.parse(text) : null;

    if (response.status === 599) {
      // The proxy's own signal that the upstream never answered. Distinguished
      // from a 5xx: PACTRA being down is not PACTRA erroring.
      const { detail } = parseErrorBody(parsed);
      return { kind: "unavailable", detail };
    }
    if (!response.ok) {
      const { reasonCode, detail } = parseErrorBody(parsed);
      return { kind: "failed", status: response.status, reasonCode, detail };
    }
    return { kind: "ok", data: parsed as T, status: response.status };
  } catch (error) {
    return {
      kind: "unavailable",
      detail: error instanceof Error ? error.message : "Unknown transport failure.",
    };
  }
}

export interface CreateMissionBody {
  raw_query: string | null;
  quantity: number;
  constraints: {
    category: string;
    soft_budget_inr: number;
    hard_limit_inr: number;
    min_rating: number;
    currency: string;
    min_merchant_trust?: number;
  };
}

export const api = {
  createMission: (body: CreateMissionBody) =>
    call<Mission>("/api/pactra/missions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }),

  getMission: (id: string) => call<Mission>(`/api/pactra/missions/${id}`),

  getEvents: (id: string) => call<AuditEvent[]>(`/api/pactra/missions/${id}/events`),

  verifyAudit: (id: string) => call<AuditVerification>(`/api/pactra/missions/${id}/audit`),

  replay: (id: string) => call<MissionReplay>(`/api/pactra/missions/${id}/replay`),

  getAuthorization: (id: string) => call<Authorization>(`/api/pactra/missions/${id}/authorization`),

  /**
   * The canonical message the EXTERNAL signer must sign.
   *
   * Fetched rather than constructed: the bytes commit to the server-held nonce
   * through `transaction_digest`, so the console could not rebuild them even if
   * it were supposed to.
   */
  getApprovalChallenge: (id: string) =>
    call<ApprovalChallenge>(`/api/pactra/missions/${id}/authorization/challenge`),

  /**
   * Submit a proof made elsewhere.
   *
   * The console never signs. It carries `{signing_key_id, signature}` produced
   * by the external signer to the kernel, which verifies before it activates.
   */
  approve: (id: string, submission: ApprovalSubmission) =>
    call<Authorization>(`/api/pactra/missions/${id}/authorization`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(submission),
    }),

  getPayment: (id: string) => call<PaymentIntent>(`/api/pactra/missions/${id}/payment`),

  /**
   * Request the one logical payment for this mission.
   *
   * The idempotency key is supplied by the caller and is REQUIRED by the
   * backend. Generating a fresh one per click would make every retry a new
   * logical payment — precisely what the header exists to prevent — so the
   * workbench holds one key per mission and sends the same value again.
   */
  requestPayment: (id: string, idempotencyKey: string) =>
    call<PaymentIntent>(`/api/pactra/missions/${id}/payment`, {
      method: "POST",
      headers: { "x-pactra-idempotency-key": idempotencyKey },
    }),

  getRisk: (id: string) => call<RiskAssessment>(`/api/pactra/missions/${id}/risk`),

  recordRisk: (id: string) =>
    call<RiskAssessment>(`/api/pactra/missions/${id}/risk`, { method: "POST" }),
};
