import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { AuditVerification } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

/**
 * Verify the mission's hash chain. GET only, and that is not an oversight:
 * the backend route is read-only by design — it repairs nothing it finds
 * broken — so there is no write verb to expose.
 */
export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<AuditVerification>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/audit/verify`,
    ),
  );
}
