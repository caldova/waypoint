import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { I18nextProvider } from "react-i18next";
import { useLocation, useNavigate } from "react-router";
import { LOCALE_COOKIE, LOCALE_COOKIE_MAX_AGE_SECONDS, type Locale } from "./config";
import { getI18n } from "./i18n";
import { localizePath, splitLocalePath } from "./paths";

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** Prefix an app path for the active language: `/invoices` → `/es/invoices`. */
  localize: (path: string) => string;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

function saveLocaleCookie(locale: Locale) {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=${LOCALE_COOKIE_MAX_AGE_SECONDS}; SameSite=Lax${secure}`;
}

/**
 * Provides the active UI language, which always comes from the URL: English is
 * unprefixed and other languages live under their code (`/es/...`). The root
 * loader sends visitors to their preferred prefix; `setLocale` saves an
 * explicit choice in a cookie and moves to the same page in that language.
 */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { locale, path } = splitLocalePath(location.pathname);

  const setLocale = useCallback(
    (next: Locale) => {
      saveLocaleCookie(next);
      if (next !== locale) {
        navigate(`${localizePath(path, next)}${location.search}${location.hash}`, {
          replace: true,
          preventScrollReset: true,
        });
      }
    },
    [locale, path, location.search, location.hash, navigate],
  );

  const localize = useCallback((target: string) => localizePath(target, locale), [locale]);

  const value = useMemo(() => ({ locale, setLocale, localize }), [locale, setLocale, localize]);

  return (
    <LocaleContext.Provider value={value}>
      <I18nextProvider i18n={getI18n(locale)}>{children}</I18nextProvider>
    </LocaleContext.Provider>
  );
}

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);
  if (!value) {
    throw new Error("useLocale must be used within LocaleProvider.");
  }
  return value;
}
