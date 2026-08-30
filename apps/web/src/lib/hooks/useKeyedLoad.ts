"use client";

import { useEffect, useState } from "react";

/**
 * Load a value for a key, and treat "loaded for a different key" as loading.
 *
 * The naive shape — reset state to `null` synchronously when the key changes,
 * then fetch — triggers a cascading render and is flagged by the React Compiler
 * lint rules for good reason. Keying the stored result instead means no reset is
 * needed at all: a snapshot whose key does not match the requested one simply is
 * not this key's answer yet.
 *
 * A stale response is discarded rather than applied, so switching selection
 * quickly cannot leave one mission's data under another mission's heading.
 */
export function useKeyedLoad<T>(
  key: string | null,
  load: (key: string) => Promise<T>,
  /** Bump to force a reload of the same key. */
  nonce = 0,
): { loading: boolean; value: T | null } {
  const [snapshot, setSnapshot] = useState<{ key: string; nonce: number; value: T } | null>(null);

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    void load(key).then((value) => {
      if (!cancelled) setSnapshot({ key, nonce, value });
    });
    return () => {
      cancelled = true;
    };
  }, [key, nonce, load]);

  const fresh = snapshot !== null && snapshot.key === key && snapshot.nonce === nonce;
  return { loading: key !== null && !fresh, value: fresh ? snapshot.value : null };
}
