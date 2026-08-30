import { pactraFetch } from "@/lib/api/server";
import { respond } from "@/lib/api/proxy";
import type { HealthResponse } from "@/lib/types/pactra";

export const dynamic = "force-dynamic";

export async function GET() {
  return respond(await pactraFetch<HealthResponse>("/health", { timeoutMs: 4000 }));
}
