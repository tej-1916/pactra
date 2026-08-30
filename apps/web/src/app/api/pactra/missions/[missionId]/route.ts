import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { Mission } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(await pactraFetch<Mission>(`/api/v1/missions/${encodeURIComponent(missionId)}`));
}
