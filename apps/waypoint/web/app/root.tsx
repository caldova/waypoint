/**
 * Root component - the application shell.
 *
 * Handles:
 * - HTML document structure
 * - Global styles and meta tags
 * - OpenTelemetry initialization
 * - Theme setup
 */

import {
  Links,
  Meta,
  Outlet,
  Scripts,
  ScrollRestoration,
  useLoaderData,
  useRouteLoaderData,
} from "react-router";
import { useEffect } from "react";
import type { HeadersFunction, LinksFunction } from "react-router";
import { useTranslation } from "react-i18next";
import { AuthProvider } from "./components/AuthProvider";
import { DEFAULT_LOCALE, isSupportedLocale } from "./i18n/config";
import { LocaleProvider, useLocale } from "./i18n/LocaleProvider";
import type { loader } from "./root.loader";

import "./app.css";

export { loader } from "./root.loader";

export const links: LinksFunction = () => [
  { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
  { rel: "apple-touch-icon", href: "/favicon.svg" },
  { rel: "manifest", href: "/site.webmanifest" },
  { rel: "mask-icon", href: "/favicon.svg", color: "#2e6cfc" },
];

// The rendered language depends on these request headers; child routes inherit this.
export const headers: HeadersFunction = () => ({
  Vary: "Accept-Language, Cookie",
});

/**
 * Document layout component. Wraps both the app and the error boundary so
 * both render in the user's language.
 */
export function Layout({ children }: { children: React.ReactNode }) {
  const rootData = useRouteLoaderData<typeof loader>("root");
  const initialLocale = isSupportedLocale(rootData?.locale) ? rootData.locale : DEFAULT_LOCALE;

  return (
    <LocaleProvider initialLocale={initialLocale}>
      <Document>{children}</Document>
    </LocaleProvider>
  );
}

function Document({ children }: { children: React.ReactNode }) {
  const { locale } = useLocale();

  return (
    <html lang={locale}>
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body className="bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 min-h-screen">
        {children}
        <ScrollRestoration />
        <Scripts />
      </body>
    </html>
  );
}

/**
 * Root application component.
 */
export default function App() {
  const { otelConfig, msalConfig, env, qualityOperations, buildVersion } =
    useLoaderData<typeof loader>();

  // Initialize telemetry on mount
  useEffect(() => {
    let cancelled = false;

    void import("../lib/telemetry").then(
      ({ initTelemetry, isTelemetryInitialized }) => {
        if (cancelled || isTelemetryInitialized()) {
          return;
        }

        initTelemetry({
          serviceName: otelConfig.serviceName,
          serviceVersion: buildVersion,
          otlpHttpEndpoint: otelConfig.otlpHttpEndpoint,
          otlpHeaders: otelConfig.otlpHeaders,
          consoleExport: env.DEV,
        });
      },
      (error) => {
        console.error("Failed to initialize telemetry", error);
      },
    );

    return () => {
      cancelled = true;
    };
  }, [otelConfig, env, buildVersion]);

  return (
    <AuthProvider localMode={env.localMode} msalConfig={msalConfig}>
      <Outlet context={{ env, qualityOperations, buildVersion }} />
    </AuthProvider>
  );
}

/**
 * Error boundary for the root route. Rendered inside `Layout`, which already
 * provides the document shell.
 */
export function ErrorBoundary() {
  const { t } = useTranslation();

  return (
    <div className="flex min-h-screen items-center justify-center">
      <title>{t("error.documentTitle")}</title>
      <div className="text-center p-8">
        <h1 className="text-4xl font-bold mb-4">{t("error.title")}</h1>
        <p className="text-lg text-zinc-600 dark:text-zinc-400 mb-6">{t("error.body")}</p>
        <a
          href="/"
          className="inline-block px-6 py-3 bg-blue-700 text-white rounded-lg hover:bg-blue-800 transition-colors"
        >
          {t("error.goHome")}
        </a>
      </div>
    </div>
  );
}
