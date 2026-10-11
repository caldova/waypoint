/**
 * Localization settings shared by the server (locale detection) and the
 * browser (language switcher).
 */

export const SUPPORTED_LOCALES = ["en", "es"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "en";

export const LOCALE_COOKIE = "waypoint_lang";
export const LOCALE_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export const NAMESPACES = [
  "common",
  "home",
  "auth",
  "activity",
  "quality",
  "agent",
  "invoices",
] as const;
export type Namespace = (typeof NAMESPACES)[number];

export const DEFAULT_NAMESPACE: Namespace = "common";

/** Native names, so each option is readable by speakers of that language. */
export const LOCALE_NAMES: Record<Locale, string> = {
  en: "English",
  es: "Español",
};

export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === "string" && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/** Map a BCP 47 tag such as `es-MX` or `en_US` onto a supported locale. */
export function matchLocale(tag: string | null | undefined): Locale | null {
  if (!tag) {
    return null;
  }
  const language = tag.trim().toLowerCase().split(/[-_]/)[0];
  return isSupportedLocale(language) ? language : null;
}
