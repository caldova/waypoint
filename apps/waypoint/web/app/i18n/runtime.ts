import { DEFAULT_LOCALE, matchLocale, type Locale, type Namespace } from "./config";
import { getI18n } from "./i18n";

/**
 * The language the page is currently rendered in. `<html lang>` follows the
 * user's choice, so non-React code (e.g. auth helpers that throw user-facing
 * errors) can translate without access to React context.
 */
export function documentLocale(): Locale {
  if (typeof document === "undefined") {
    return DEFAULT_LOCALE;
  }
  return matchLocale(document.documentElement.lang) ?? DEFAULT_LOCALE;
}

export function getDocumentT<N extends Namespace>(namespace: N) {
  return getI18n(documentLocale()).getFixedT(null, namespace);
}
