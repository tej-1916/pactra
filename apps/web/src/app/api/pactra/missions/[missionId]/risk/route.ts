import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { RiskAssessment } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

/** Score the mission. Read-only: writes no row and appends no audit event. */
export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<RiskAssessment>(`/api/v1/missions/${encodeURIComponent(missionId)}/risk`),
  );
}

/**
 * Score AND record a `RISK_ASSESSED` audit event.
 *
 * Kept a separate verb from the read for the reason the backend states: a read
 * that quietly appended to a mission's hash chain would mean anyone inspecting
 * a mission had altered its history. The console therefore never records as a
 * side effect of rendering — only when someone asks for it.
 */
export async function POST(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<RiskAssessment>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/risk/assess`,
      { method: "POST" },
    ),
  );
}
