"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "framer-motion";
import { useState, type ReactNode } from "react";

/**
 * The two client-side providers this console needs.
 *
 * REACT QUERY is configured for a security surface rather than a content one.
 * `staleTime: 0` and no window-focus refetch look contradictory until you name
 * what is being cached: every value here is either a security decision or
 * evidence about one, so a cached answer is only ever a starting point for the
 * render and never the reported truth — while a refetch storm triggered by
 * alt-tabbing during a demo is pure noise. Retries are off for the same reason
 * the API layer models failure as a value: a refusal is an ANSWER, and retrying
 * a 409 three times before showing it would hide the fastest, clearest result
 * the kernel produces.
 *
 * MOTION is configured `reducedMotion="user"` once, here, so no component has
 * to remember it. Motion in this app explains a state change; a user who has
 * asked for less of it still gets the state change, just not the movement.
 */
export function Providers({ children }: { children: ReactNode }) {
  // Created in state, not at module scope: a module-level client would be
  // shared across requests on the server and leak one user's cache into
  // another's render.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 0,
            gcTime: 60_000,
            retry: false,
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </QueryClientProvider>
  );
}
