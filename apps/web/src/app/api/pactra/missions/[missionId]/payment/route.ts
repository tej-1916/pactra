import { NextResponse } from "next/server";

import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { PaymentIntent } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

/** Backend cap on the accepted key (`routes_payments.MAX_IDEMPOTENCY_KEY_LENGTH`). */
const MAX_IDEMPOTENCY_KEY_LENGTH = 200;

export async function GET(_request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  return respond(
    await pactraFetch<PaymentIntent>(`/api/v1/missions/${encodeURIComponent(missionId)}/payment`),
  );
}

/**
 * Request the one logical payment for this mission.
 *
 * The idempotency key is taken from the CLIENT and forwarded. This handler will
 * not mint one: a server-generated key would make each retry a distinct logical
 * payment, defeating the guarantee the console exists to demonstrate. A missing
 * key is refused here rather than passed on as an empty header.
 *
 * The amount, merchant, product and currency are not accepted from anywhere —
 * there is no field for them in the backend request and none is added here. The
 * intent is derived entirely from the authorization the kernel holds.
 */
export async function POST(request: Request, context: { params: Promise<{ missionId: string }> }) {
  const { missionId } = await context.params;
  const key = request.headers.get("x-pactra-idempotency-key") ?? "";

  if (key.length === 0 || key.length > MAX_IDEMPOTENCY_KEY_LENGTH) {
    return NextResponse.json(
      {
        detail: {
          reason_code: "IDEMPOTENCY_KEY_INVALID",
          detail: `An Idempotency-Key of 1..${MAX_IDEMPOTENCY_KEY_LENGTH} characters is required.`,
        },
      },
      { status: 400 },
    );
  }

  return respond(
    await pactraFetch<PaymentIntent>(
      `/api/v1/missions/${encodeURIComponent(missionId)}/payment`,
      { method: "POST", headers: { "Idempotency-Key": key }, timeoutMs: 20_000 },
    ),
  );
}
