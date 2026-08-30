import { NextResponse } from "next/server";

import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { Mission } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

/**
 * Create a mission.
 *
 * The body is forwarded unchanged. This handler adds no field, defaults no
 * constraint and rewrites no value: `MissionConstraints` is `extra="forbid"`,
 * so a helpful addition here would become a 422 there — and, worse, would mean
 * the console had authored part of a user policy.
 *
 * There is deliberately no GET. PACTRA exposes no mission-list endpoint, and
 * inventing one in the proxy would mean inventing it in the backend.
 */
export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Request body was not valid JSON." }, { status: 400 });
  }
  // A mission runs a full discovery + normalization + policy pass, so it is
  // allowed appreciably longer than a read before being called unreachable.
  return respond(await pactraFetch<Mission>("/api/v1/missions", { method: "POST", body, timeoutMs: 20_000 }));
}
