/**
 * Theme selection: light by default, dark as its inverse.
 *
 * Three states: an explicit `light`, an explicit `dark`, and `system` —
 * which is not a colour but a deferral to the OS when explicitly chosen.
 * When no preference is stored, PACTRA defaults strictly to `light`.
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
 * cosmetic.
 *
 * Default contract:
 * - Stored "dark" -> dark
 * - Stored "system" -> OS preference
 * - Stored "light" / no stored preference / corrupted key -> light
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{
var s=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
var d=s==="dark"||(s==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);
document.documentElement.setAttribute("data-theme",d?"dark":"light");
}catch(e){document.documentElement.setAttribute("data-theme","light");}})();`;

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === "system") return systemPrefersDark ? "dark" : "light";
  return preference;
}

// --------------------------------------------------------------------------- //
// The stored preference, as an external store
// --------------------------------------------------------------------------- //

const listeners = new Set<() => void>();
let cachedRaw: string | null = null;
let cached: ThemePreference = "light";

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
    return "light";
  }
  if (raw === cachedRaw) return cached;
  cachedRaw = raw;
  cached = isThemePreference(raw) ? raw : "light";
  return cached;
}

/** The default theme contract is light when no preference exists. */
export function getServerThemePreference(): ThemePreference {
  return "light";
}

export function setThemePreference(next: ThemePreference): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    // Storage failure is survivable by design.
  }
  const systemPrefersDark =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  document.documentElement.setAttribute("data-theme", resolveTheme(next, systemPrefersDark));
  for (const listener of listeners) listener();
}
