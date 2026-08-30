"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "pactra.mission-register.v1";
const MAX_ENTRIES = 50;

export interface RegisteredMission {
  id: string;
  rawQuery: string | null;
  createdAt: string;
  /**
   * The idempotency key minted for this mission's payment, held so a retry
   * presents the SAME key. A fresh key per click would make every retry a new
   * logical payment — the exact opposite of what the header is for.
   */
  idempotencyKey: string;
}

/**
 * A browser-local record of missions created from THIS browser.
 *
 * PACTRA exposes no mission-list endpoint — every mission route is
 * `/{mission_id}`-scoped — so there is no honest way to enumerate what the
 * system holds. Rather than invent an endpoint or fabricate a list, the console
 * remembers what it itself created and says so on every surface that shows it.
 *
 * This is emphatically NOT a system inventory, and no view derived from it is
 * ever labelled as one.
 *
 * Implemented over `useSyncExternalStore` because `localStorage` IS an external
 * store: that gives a correct server snapshot (empty, so the server never
 * renders a list it cannot know about), a tear-free client read, and updates
 * that propagate to every mounted consumer — including from another tab, via
 * the `storage` event.
 */

let cache: RegisteredMission[] = [];
let cacheRaw: string | null = null;
const listeners = new Set<() => void>();

/** Stable empty snapshot: a new array each call would loop the store forever. */
const SERVER_SNAPSHOT: RegisteredMission[] = [];

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function emit() {
  for (const listener of listeners) listener();
}

function getSnapshot(): RegisteredMission[] {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable (private mode, blocked site data). The register
    // is a convenience, not a source of truth, so losing it costs correctness
    // nothing — every value it points at is re-read from the API.
    return SERVER_SNAPSHOT;
  }
  if (raw === cacheRaw) return cache;
  cacheRaw = raw;
  cache = parse(raw);
  return cache;
}

function getServerSnapshot(): RegisteredMission[] {
  return SERVER_SNAPSHOT;
}

function parse(raw: string | null): RegisteredMission[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter(isRegisteredMission) : [];
  } catch {
    return [];
  }
}

function isRegisteredMission(value: unknown): value is RegisteredMission {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return typeof record.id === "string" && typeof record.idempotencyKey === "string";
}

function write(entries: RegisteredMission[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // See getSnapshot: storage failure is survivable by design.
  }
  emit();
}

export function useMissionRegister() {
  const missions = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const register = useCallback((entry: RegisteredMission) => {
    const current = getSnapshot();
    write([entry, ...current.filter((item) => item.id !== entry.id)].slice(0, MAX_ENTRIES));
  }, []);

  const forget = useCallback((id: string) => {
    write(getSnapshot().filter((item) => item.id !== id));
  }, []);

  const clear = useCallback(() => {
    write([]);
  }, []);

  /**
   * True once the client snapshot is in use. Consumers render a skeleton until
   * then rather than briefly showing "no missions", which would read as a
   * statement about the system rather than about hydration.
   */
  const hydrated = typeof window !== "undefined";

  return { missions, hydrated, register, forget, clear };
}

export function readRegister(): RegisteredMission[] {
  if (typeof window === "undefined") return [];
  return getSnapshot();
}

/** A per-mission idempotency key. Opaque, client-generated, and reused on retry. */
export function newIdempotencyKey(missionId: string): string {
  return `pactra-console-${missionId}`;
}
