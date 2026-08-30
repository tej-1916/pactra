import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { Authorization } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<Authorization>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/authorization`,
    ),
  );
}

/** Human approval: PENDING -> ACTIVE. Carries no body; the backend accepts none. */
export async function POST(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<Authorization>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/authorization/approve`,
      { method: "POST" },
    ),
  );
}
