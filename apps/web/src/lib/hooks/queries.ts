"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import type { ApiResult } from "@/lib/api/result";
import type {
  Authorization,
  HealthResponse,
  Mission,
  MissionReplay,
  PaymentIntent,
  RiskAssessment,
} from "@/lib/types/pactra";

/**
 * React Query over the `ApiResult` transport.
 *
 * The important decision here is that a refusal is NOT a query error. `api.*`
 * already models "the backend answered with a refusal", "the backend could not
 * be reached", and "here is your data" as three values of one type, and that
 * distinction is the whole reason the console can render a 409 carrying
 * `AUTHORIZATION_REPLAY_DETECTED` as the kernel doing its job rather than as a
 * red failure toast.
 *
 * Throwing on a non-ok result would collapse all three into React Query's
 * single `error` channel and lose it. So every hook resolves with the
 * `ApiResult` intact and the caller branches on `kind` — the same thing the
 * server components already do.
 *
 * `retry: false` is inherited from the client in `app/providers.tsx`: a
 * refusal is an answer, and retrying it three times before showing it would
 * hide the fastest, clearest result the kernel produces.
 */

export const queryKeys = {
  health: () => ["health"] as const,
  mission: (id: string) => ["mission", id] as const,
  replay: (id: string) => ["replay", id] as const,
  authorization: (id: string) => ["authorization", id] as const,
  payment: (id: string) => ["payment", id] as const,
  risk: (id: string) => ["risk", id] as const,
} as const;

type Result<T> = UseQueryResult<ApiResult<T>>;

/**
 * System health.
 *
 * Polled rather than read once: an operator needs to know that what they are
 * reading is current, and a console that reports a backend as up because it was
 * up when the tab opened is worse than one that reports nothing.
 */
export function useHealth(): Result<HealthResponse> {
  return useQuery({
    queryKey: queryKeys.health(),
    queryFn: () => api.getHealth(),
    refetchInterval: 15_000,
  });
}

export function useMission(missionId: string | null): Result<Mission> {
  return useQuery({
    queryKey: queryKeys.mission(missionId ?? ""),
    queryFn: () => api.getMission(missionId as string),
    enabled: missionId !== null,
  });
}

/**
 * The mission replay — and therefore the Decision Trace.
 *
 * There is no separate trace endpoint and this hook does not pretend there is:
 * `decision_trace` is an array on this read-only, audit-verified response, and
 * it is empty whenever verification or replay failed.
 */
export function useReplay(missionId: string | null): Result<MissionReplay> {
  return useQuery({
    queryKey: queryKeys.replay(missionId ?? ""),
    queryFn: () => api.replay(missionId as string),
    enabled: missionId !== null,
  });
}

export function useAuthorization(missionId: string | null): Result<Authorization> {
  return useQuery({
    queryKey: queryKeys.authorization(missionId ?? ""),
    queryFn: () => api.getAuthorization(missionId as string),
    enabled: missionId !== null,
  });
}

export function usePayment(missionId: string | null): Result<PaymentIntent> {
  return useQuery({
    queryKey: queryKeys.payment(missionId ?? ""),
    queryFn: () => api.getPayment(missionId as string),
    enabled: missionId !== null,
  });
}

export function useRisk(missionId: string | null): Result<RiskAssessment> {
  return useQuery({
    queryKey: queryKeys.risk(missionId ?? ""),
    queryFn: () => api.getRisk(missionId as string),
    enabled: missionId !== null,
  });
}
