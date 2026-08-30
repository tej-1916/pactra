import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { ApprovalSubmission, Authorization } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<Authorization>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/authorization`,
    ),
  );
}

/**
 * Submit a LOCAL CRYPTOGRAPHIC APPROVAL PROOF: PENDING -> ACTIVE.
 *
 * The body carries only `{signing_key_id, signature}`. The console does not
 * hold, transport, or generate the demo signing key — the signature is produced
 * by the external signer and arrives here already made. This proxy forwards the
 * two fields and nothing else, because the backend's `ApprovalRequest` forbids
 * extra keys and would reject an enriched body.
 */
export async function POST(request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;

  let submission: ApprovalSubmission;
  try {
    const raw: unknown = await request.json();
    submission = normalizeSubmission(raw);
  } catch (error) {
    return respond({
      kind: "failed",
      status: 400,
      reasonCode: "APPROVAL_REQUEST_MALFORMED",
      detail: error instanceof Error ? error.message : "The approval request body is unreadable.",
    });
  }

  return respond(
    await pactraFetch<Authorization>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/authorization/approve`,
      { method: "POST", body: submission },
    ),
  );
}

/**
 * Reject a malformed proof here rather than forwarding it.
 *
 * The shape is checked, never the cryptography: only the kernel can say whether
 * a signature verifies, and a console that pre-judged that would be claiming an
 * authority it does not have. This exists so an empty or mistyped field returns
 * a readable console error instead of a bare FastAPI 422.
 */
function normalizeSubmission(raw: unknown): ApprovalSubmission {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("Expected a JSON object with signing_key_id and signature.");
  }
  const { signing_key_id: keyId, signature } = raw as Record<string, unknown>;
  if (typeof keyId !== "string" || keyId.length === 0) {
    throw new Error("signing_key_id must be a non-empty string.");
  }
  if (typeof signature !== "string" || !/^[0-9a-f]{128}$/.test(signature)) {
    throw new Error(
      "signature must be exactly 128 lowercase hexadecimal characters, as emitted by the signer.",
    );
  }
  return { signing_key_id: keyId, signature };
}
