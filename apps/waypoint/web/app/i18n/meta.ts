import type { MetaDescriptor } from "react-router";
import { getI18n } from "./i18n";
import { splitLocalePath } from "./paths";

type PageKey = "home" | "login" | "activity" | "agent" | "invoices" | "quality";

/** Localized `<title>` and description for a route's `meta` export. */
export function pageMeta(location: { pathname: string }, page: PageKey): MetaDescriptor[] {
  const t = getI18n(splitLocalePath(location.pathname).locale).getFixedT(null, "common");
  return [
    { title: t(`meta.${page}.title`) },
    { name: "description", content: t(`meta.${page}.description`) },
  ];
}
