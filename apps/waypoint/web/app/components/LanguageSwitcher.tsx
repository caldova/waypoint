import { useId } from "react";
import { useTranslation } from "react-i18next";
import { HiTranslate } from "react-icons/hi";
import { LOCALE_NAMES, SUPPORTED_LOCALES, isSupportedLocale } from "../i18n/config";
import { useLocale } from "../i18n/LocaleProvider";

/** Compact language picker. The choice is saved in a cookie for future visits. */
export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  const { locale, setLocale } = useLocale();
  const id = useId();

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <HiTranslate className="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
      <label htmlFor={id} className="sr-only">
        {t("language.label")}
      </label>
      <select
        id={id}
        value={locale}
        onChange={(event) => {
          if (isSupportedLocale(event.target.value)) {
            setLocale(event.target.value);
          }
        }}
        className="min-h-8 w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 max-lg:min-h-11"
      >
        {SUPPORTED_LOCALES.map((option) => (
          <option key={option} value={option} lang={option}>
            {LOCALE_NAMES[option]}
          </option>
        ))}
      </select>
    </div>
  );
}
