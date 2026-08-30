import "server-only";

import { NextResponse } from "next/server";

import type { ApiResult } from "./result";

/**
 * Turns an `ApiResult` into an HTTP response for the browser client.
 *
 * `unavailable` becomes **599**, a status the PACTRA API itself never returns.
 * A stopped backend must not arrive at the browser wearing a 502 or a 500,
 * because the console renders "PACTRA API unavailable" and "PACTRA refused this
 * request" as different screens, and a shared status code would collapse them.
 */
export function respond<T>(result: ApiResult<T>): NextResponse {
  if (result.kind === "ok") {
    return NextResponse.json(result.data, { status: result.status });
  }
  if (result.kind === "unavailable") {
    return NextResponse.json({ detail: result.detail }, { status: 599 });
  }
  return NextResponse.json(
    { detail: { reason_code: result.reasonCode, detail: result.detail } },
    { status: result.status },
  );
}
