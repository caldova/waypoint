/**
 * Localization settings shared by the server (locale detection) and the
 * browser (language switcher).
 */

export const SUPPORTED_LOCALES = ["en", "es", "zh-TW"] as const;
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
  "zh-TW": "中文（台灣）",
};

export function isSupportedLocale(value: unknown): value is Locale {
  return typeof value === "string" && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

/** Regions whose Chinese readers use Traditional characters. */
const TRADITIONAL_CHINESE_REGIONS = ["tw", "hk", "mo"];

/**
 * Map a BCP 47 tag such as `es-MX`, `en_US`, or `zh-Hant-TW` onto a supported
 * locale. Traditional Chinese (`zh-TW`, `zh-HK`, `zh-Hant`) maps to `zh-TW`;
 * Simplified Chinese (`zh`, `zh-CN`, `zh-Hans`) has no translation yet.
 */
export function matchLocale(tag: string | null | undefined): Locale | null {
  if (!tag) {
    return null;
  }
  const [language, ...subtags] = tag.trim().toLowerCase().split(/[-_]/);
  if (language === "zh") {
    const traditional =
      subtags.includes("hant") ||
      (!subtags.includes("hans") && subtags.some((subtag) => TRADITIONAL_CHINESE_REGIONS.includes(subtag)));
    return traditional ? "zh-TW" : null;
  }
  return isSupportedLocale(language) ? language : null;
}
