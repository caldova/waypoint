import { DEFAULT_LOCALE, SUPPORTED_LOCALES, type Locale } from "./config";

/**
 * Locale-prefixed URLs. English, the default, is unprefixed (`/invoices`);
 * every other language lives under its code (`/es/invoices`).
 */

/** App paths that must never be prefixed or redirected (e.g. the MSAL redirect URI). */
export const UNLOCALIZED_PATHS = ["/auth/msal/callback", "/client-telemetry"];

export interface LocalePath {
  locale: Locale;
  /** The path without its locale prefix, always starting with `/`. */
  path: string;
  /** True when the URL started with a locale code (including an explicit `/en`). */
  prefixed: boolean;
}

/** Split `/es/invoices` into `{ locale: "es", path: "/invoices" }`. Codes match case-insensitively (`/zh-tw`). */
export function splitLocalePath(pathname: string): LocalePath {
  const match = /^\/([^/]+)(\/.*)?$/.exec(pathname);
  const locale = localeFromSegment(match?.[1]);
  if (match && locale) {
    return { locale, path: match[2] || "/", prefixed: true };
  }
  return { locale: DEFAULT_LOCALE, path: pathname || "/", prefixed: false };
}

function localeFromSegment(segment: string | undefined): Locale | null {
  const lower = segment?.toLowerCase();
  return SUPPORTED_LOCALES.find((locale) => locale.toLowerCase() === lower) ?? null;
}

/** `/invoices?x=1` → `/es/invoices?x=1` for Spanish; unchanged for English. */
export function localizePath(path: string, locale: Locale): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  if (locale === DEFAULT_LOCALE) {
    return clean;
  }
  // Home: `/es`, not `/es/`.
  if (clean === "/" || clean.startsWith("/?") || clean.startsWith("/#")) {
    return `/${locale}${clean.slice(1)}`;
  }
  return `/${locale}${clean}`;
}

export function isUnlocalizedPath(path: string): boolean {
  return UNLOCALIZED_PATHS.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
}
