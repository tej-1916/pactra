"use client";

import type { ReactNode } from "react";

import { EmptyState, ErrorState, LoadingSkeleton, RefusalState, UnavailableState } from "./States";
import type { ApiResult } from "@/lib/api/result";
import { describeReasonCode } from "@/lib/reason-codes";

/**
 * One place that turns an `ApiResult` into the right state, so no screen has to
 * remember the difference between five things that all look like "no data".
 *
 * The routing rule, and the reasoning behind each branch:
 *
 *   loading       we are still asking.
 *   unavailable   we could not ask at all. NEVER rendered as zero or empty —
 *                 a stopped backend is not a system with nothing in it.
 *   404           we asked, and the thing does not exist yet. Empty, not error.
 *   401/403/409   a CONTROL refused. Rendered in the secure tone, because a
 *                 refusal is the kernel working and painting it red would tell
 *                 a reader the system broke.
 *   other 4xx/5xx a genuine error, with whatever reason code came back.
 *
 * The reason code is always printed verbatim. It is the durable handle on the
 * event — what the ledger recorded and what an engineer greps for — and a
 * friendly sentence in its place would destroy the only thing worth having.
 */
export function ResultBoundary<T>({
  result,
  isLoading,
  children,
  /** What is being fetched, in words. Used in every state's copy. */
  what,
  /** Rows of skeleton while loading. */
  skeletonRows = 3,
  /** Rendered instead of the default empty state for a 404. */
  notFound,
}: {
  result: ApiResult<T> | undefined;
  isLoading: boolean;
  children: (data: T) => ReactNode;
  what: string;
  skeletonRows?: number;
  notFound?: ReactNode;
}) {
  if (isLoading || result === undefined) {
    return <LoadingSkeleton rows={skeletonRows} />;
  }

  if (result.kind === "unavailable") {
    return (
      <UnavailableState
        title="PACTRA API unavailable"
        detail={
          <>
            The {what} could not be read because the backend did not answer:{" "}
            <span className="num">{result.detail}</span>. This is not the same as there being
            nothing to show, and this screen will not pretend it is.
          </>
        }
      />
    );
  }

  if (result.kind === "failed") {
    if (result.status === 404) {
      return (
        <>
          {notFound ?? (
            <EmptyState
              title={`No ${what} yet`}
              detail={
                <>
                  PACTRA holds no {what} for this mission.{" "}
                  {result.reasonCode ? (
                    <>
                      Reason code <code className="num">{result.reasonCode}</code>
                      {describeReasonCode(result.reasonCode)
                        ? ` — ${describeReasonCode(result.reasonCode)}`
                        : ""}
                      .
                    </>
                  ) : null}
                </>
              }
            />
          )}
        </>
      );
    }

    const refused = result.status === 401 || result.status === 403 || result.status === 409;
    const detail = (
      <>
        {result.reasonCode ? (
          <>
            <code className="num font-semibold">{result.reasonCode}</code>
            {describeReasonCode(result.reasonCode) ? (
              <> — {describeReasonCode(result.reasonCode)}</>
            ) : null}{" "}
          </>
        ) : null}
        <span className="text-[color:var(--color-ink-3)]">
          HTTP {result.status}. {result.detail}
        </span>
      </>
    );

    return refused ? (
      <RefusalState
        title="PACTRA refused this request"
        detail={
          <>
            {detail}
            <p className="mt-1.5">
              A refusal is an answer, not a malfunction. Nothing was authorized and nothing moved.
            </p>
          </>
        }
      />
    ) : (
      <ErrorState title={`Could not read the ${what}`} detail={detail} />
    );
  }

  return <>{children(result.data)}</>;
}
