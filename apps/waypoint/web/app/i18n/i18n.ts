import { createInstance, type i18n as I18nInstance } from "i18next";
import { initReactI18next } from "react-i18next";
import {
  DEFAULT_LOCALE,
  DEFAULT_NAMESPACE,
  NAMESPACES,
  SUPPORTED_LOCALES,
  type Locale,
} from "./config";
import { resources } from "./resources";

const instances = new Map<Locale, I18nInstance>();

/**
 * One i18next instance per locale. Each instance is pinned to its language and
 * never switched, so concurrent SSR requests in different languages can't
 * affect each other. Switching language on the client swaps the instance.
 */
export function getI18n(locale: Locale): I18nInstance {
  const existing = instances.get(locale);
  if (existing) {
    return existing;
  }

  const instance = createInstance();
  void instance.use(initReactI18next).init({
    resources,
    lng: locale,
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: [...SUPPORTED_LOCALES],
    ns: [...NAMESPACES],
    defaultNS: DEFAULT_NAMESPACE,
    initAsync: false,
    interpolation: {
      // React already escapes rendered strings.
      escapeValue: false,
    },
    react: {
      useSuspense: false,
    },
    returnNull: false,
  });
  instances.set(locale, instance);
  return instance;
}
