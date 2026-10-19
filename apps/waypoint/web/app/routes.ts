/**
 * Route definitions for React Router v7.
 *
 * Every page exists unprefixed (English) and under each other language's code,
 * e.g. `/invoices` and `/es/invoices`. See `app/i18n/paths.ts`.
 */

import { type RouteConfig, type RouteConfigEntry, index, prefix, route } from "@react-router/dev/routes";
import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from "./i18n/config";

function pages(locale?: string): RouteConfigEntry[] {
  // Route ids must be unique: keep the default ids for English and scope the
  // localized copies, e.g. "routes/invoices" and "es/routes/invoices".
  const id = (name: string) => ({ id: locale ? `${locale}/routes/${name}` : `routes/${name}` });
  return [
    index("routes/home.tsx", id("home")),
    route("login", "routes/login.tsx", id("login")),
    route("agent", "routes/agent.tsx", id("agent")),
    route("activity", "routes/activity.tsx", id("activity")),
    route("quality", "routes/quality.tsx", id("quality")),
    route("invoices", "routes/invoices.tsx", id("invoices")),
  ];
}

export default [
  // Not localized: fixed URLs used by MSAL and the telemetry beacon.
  route("auth/msal/callback", "routes/auth.msal.callback.tsx"),
  route("client-telemetry", "routes/client-telemetry.tsx"),
  // English is unprefixed; `/en/...` redirects there.
  route(`${DEFAULT_LOCALE}/*`, "routes/default-locale-redirect.ts"),
  ...pages(),
  ...SUPPORTED_LOCALES.filter((locale) => locale !== DEFAULT_LOCALE).flatMap((locale) =>
    prefix(locale, pages(locale)),
  ),
] satisfies RouteConfig;
