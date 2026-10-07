import type { MetaDescriptor } from "react-router";
import { DEFAULT_LOCALE, isSupportedLocale, type Locale } from "./config";
import { getI18n } from "./i18n";

type PageKey = "home" | "login" | "activity" | "agent" | "invoices" | "quality";

interface MatchLike {
  id: string;
  data?: unknown;
  loaderData?: unknown;
}

function localeFromMatches(matches: ReadonlyArray<MatchLike | undefined>): Locale {
  const root = matches.find((match) => match?.id === "root");
  const data = (root?.loaderData ?? root?.data) as { locale?: unknown } | undefined;
  return isSupportedLocale(data?.locale) ? data.locale : DEFAULT_LOCALE;
}

/** Localized `<title>` and description for a route's `meta` export. */
export function pageMeta(matches: ReadonlyArray<MatchLike | undefined>, page: PageKey): MetaDescriptor[] {
  const t = getI18n(localeFromMatches(matches)).getFixedT(null, "common");
  return [
    { title: t(`meta.${page}.title`) },
    { name: "description", content: t(`meta.${page}.description`) },
  ];
}
