import "server-only";

import { type ApiResult, parseErrorBody } from "./result";

/**
 * The single place this application talks to the PACTRA API.
 *
 * `PACTRA_API_URL` is read here and nowhere else, and this module is
 * `server-only`, so the API origin cannot end up in a client bundle. That is
 * also why there is no `NEXT_PUBLIC_PACTRA_API_URL`: a browser-reachable
 * backend URL is the first step toward a browser-held credential, and this
 * console needs neither.
 */
export function apiBaseUrl(): string {
  return (process.env.PACTRA_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

interface RequestOptions {
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  body?: unknown;
  /** Milliseconds before the request is abandoned as unreachable. */
  timeoutMs?: number;
}

/**
 * A timeout is mandatory rather than optional.
 *
 * A console page that hangs forever on a stopped backend teaches an operator
 * that the system is slow, when the truth is that it is down. Ten seconds is
 * long enough for a cold mission run against SQLite and short enough that
 * "unavailable" arrives while anyone is still looking.
 */
const DEFAULT_TIMEOUT_MS = 10_000;

export async function pactraFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ApiResult<T>> {
  const { method = "GET", headers = {}, body, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      method,
      headers: {
        accept: "application/json",
        ...(body === undefined ? {} : { "content-type": "application/json" }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      // Never cached. Every value on this console is either a security decision
      // or evidence about one; a stale authorization status is a wrong answer.
      cache: "no-store",
    });

    const text = await response.text();
    const parsed: unknown = text.length > 0 ? safeJson(text) : null;

    if (!response.ok) {
      const { reasonCode, detail } = parseErrorBody(parsed ?? text);
      return { kind: "failed", status: response.status, reasonCode, detail };
    }
    return { kind: "ok", data: parsed as T, status: response.status };
  } catch (error) {
    const detail =
      error instanceof Error && error.name === "AbortError"
        ? `No response from the PACTRA API within ${timeoutMs / 1000}s.`
        : error instanceof Error
          ? error.message
          : "Unknown transport failure.";
    return { kind: "unavailable", detail };
  } finally {
    clearTimeout(timer);
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
