import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";

/**
 * A `localStorage` for the test environment.
 *
 * Node 26 defines a global `localStorage` that is unavailable without
 * `--localstorage-file`, and it shadows the one jsdom would otherwise install —
 * so `window.localStorage` is `undefined` under this toolchain. The mission
 * register is storage-backed, so the tests need a working Storage to exercise
 * it rather than to skip past it.
 *
 * This is deliberately a plain in-memory implementation: the production code
 * already treats storage as unreliable (every read and write is wrapped, because
 * private mode and blocked site data are real), and a polyfill that threw would
 * be testing the fallback instead of the behaviour.
 */
class MemoryStorage implements Storage {
  #entries = new Map<string, string>();

  get length() {
    return this.#entries.size;
  }
  clear() {
    this.#entries.clear();
  }
  getItem(key: string) {
    return this.#entries.get(key) ?? null;
  }
  key(index: number) {
    return [...this.#entries.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.#entries.delete(key);
  }
  setItem(key: string, value: string) {
    this.#entries.set(key, String(value));
  }
}

if (typeof window !== "undefined" && !window.localStorage) {
  Object.defineProperty(window, "localStorage", {
    value: new MemoryStorage(),
    configurable: true,
  });
}

beforeEach(() => {
  window.localStorage?.clear();
});
