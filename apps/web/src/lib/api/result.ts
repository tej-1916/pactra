/**
 * One shape for "what happened when we asked the backend".
 *
 * A thrown fetch error and a 409 carrying `AUTHORIZATION_REPLAY_DETECTED` are
 * completely different events, and the console has to render them completely
 * differently — the first is an infrastructure problem, the second is the
 * security kernel doing its job. So both are values, and neither is an
 * exception a caller can forget to catch.
 *
 * `unavailable` exists separately from `failed` for the reason stated in the
 * phase brief: an unreachable API must render as "PACTRA API unavailable",
 * never as "0 transactions". Empty is not the same as failure.
 */

export type ApiResult<T> =
  | { kind: "ok"; data: T; status: number }
  /** The backend answered, and its answer was a refusal or a validation error. */
  | { kind: "failed"; status: number; reasonCode: string | null; detail: string }
  /** The backend could not be reached at all. */
  | { kind: "unavailable"; detail: string };

export function isOk<T>(result: ApiResult<T>): result is { kind: "ok"; data: T; status: number } {
  return result.kind === "ok";
}

/**
 * Pull a reason code out of a FastAPI error body.
 *
 * PACTRA raises `HTTPException(detail={"reason_code": ..., "detail": ...})` for
 * every security refusal and a plain string for a 404. Both are handled, and a
 * body matching neither yields `null` rather than a guessed code — displaying an
 * invented reason code beside a real one would be worse than displaying none.
 */
export function parseErrorBody(body: unknown): { reasonCode: string | null; detail: string } {
  if (typeof body === "string") return { reasonCode: null, detail: body };
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return { reasonCode: null, detail };
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item === "object") {
            const loc = Array.isArray((item as { loc?: unknown[] }).loc)
              ? (item as { loc: unknown[] }).loc.filter((p) => p !== "body" && p !== "path").join(".")
              : "";
            const msg = typeof (item as { msg?: string }).msg === "string" ? (item as { msg: string }).msg : null;
            if (loc && msg) return `${loc}: ${msg}`;
            if (msg) return msg;
          }
          return null;
        })
        .filter((msg): msg is string => Boolean(msg));
      return {
        reasonCode: null,
        detail: messages.length > 0 ? messages.join("; ") : "Invalid request parameter format.",
      };
    }
    if (detail && typeof detail === "object") {
      const record = detail as Record<string, unknown>;
      const reasonCode = typeof record.reason_code === "string" ? record.reason_code : null;
      const text =
        typeof record.detail === "string"
          ? record.detail
          : typeof record.state === "string"
            ? `state: ${record.state}`
            : JSON.stringify(record);
      return { reasonCode, detail: text };
    }
  }
  return { reasonCode: null, detail: "The backend returned an error with no readable detail." };
}
