import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { ApprovalChallenge } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

/**
 * The canonical bytes the EXTERNAL signer signs.
 *
 * The server rebuilds this message from durable authorization state, so the
 * console is a display surface for it and never a producer of it. The response
 * carries no key material: the private half of the demo key is not in this
 * repository, this process, or the browser.
 *
 * The kernel returns 409 when the mission is not awaiting a `USER_ED25519`
 * approval, which is what distinguishes "no proof is wanted here" from "the
 * backend is down". Both reach the console as distinct states.
 */
export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<ApprovalChallenge>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/authorization/challenge`,
    ),
  );
}
