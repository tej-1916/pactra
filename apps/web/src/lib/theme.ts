/**
 * Theme selection: light by default, dark as its inverse.
 *
 * Three states, and they are genuinely three: an explicit `light`, an explicit
 * `dark`, and `system` — which is not a colour but a deferral to the OS. The
 * stored value is only ever one of these, and anything else in storage is
 * treated as absent rather than coerced, because a corrupted key must not
 * silently pin a theme a user never chose.
 */

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "pactra.theme.v1";

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "light" || value === "dark" || value === "system";
}

/**
 * The script that runs BEFORE first paint.
 *
 * It exists so the palette is settled by the time the document renders: a page
 * that paints light and then flips to dark is a flash of the wrong answer, and
 * on a console whose colours carry security meaning that is worse than
 * cosmetic. `data-theme` is stamped explicitly for both outcomes, which is also
 * why `globals.css` needs exactly one dark block rather than a
 * `prefers-color-scheme` copy of it that could drift.
 *
 * Storage access is wrapped: private mode and blocked site data both throw on
 * read, and a theme script must never be the reason a page fails to render.
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{
var s=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
var d=s==="dark"||((s===null||s==="system")&&window.matchMedia("(prefers-color-scheme: dark)").matches);
document.documentElement.setAttribute("data-theme",d?"dark":"light");
}catch(e){document.documentElement.setAttribute("data-theme","light");}})();`;

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

// --------------------------------------------------------------------------- //
// The stored preference, as an external store
// --------------------------------------------------------------------------- //

/**
 * `localStorage` IS an external store, so it is read through
 * `useSyncExternalStore` rather than copied into React state by an effect.
 *
 * That buys three things at once: a correct server snapshot (`system`, the only
 * thing a server can honestly claim about a preference it cannot see), a
 * tear-free client read, and propagation to every mounted consumer — including
 * from another tab, via the `storage` event. Copying it in with `useEffect`
 * would give a cascading render and a preference that silently diverges between
 * two open tabs.
 */

const listeners = new Set<() => void>();
let cachedRaw: string | null = null;
let cached: ThemePreference = "system";

export function subscribeToThemePreference(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function getThemePreference(): ThemePreference {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(THEME_STORAGE_KEY);
  } catch {
    // Private mode and blocked site data both throw. The theme still works; it
    // just is not remembered.
    return "system";
  }
  if (raw === cachedRaw) return cached;
  cachedRaw = raw;
  cached = isThemePreference(raw) ? raw : "system";
  return cached;
}

/** The server cannot know the OS preference, so it claims nothing. */
export function getServerThemePreference(): ThemePreference {
  return "system";
}

export function setThemePreference(next: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // See getThemePreference.
  }
  const systemPrefersDark =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  document.documentElement.setAttribute("data-theme", resolveTheme(next, systemPrefersDark));
  for (const listener of listeners) listener();
}
