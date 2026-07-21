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
} from "react-router";
import { useEffect } from "react";
import type { LinksFunction } from "react-router";
import { AuthProvider } from "./components/AuthProvider";

import "./app.css";

export { loader } from "./root.loader";

export const links: LinksFunction = () => [
  { rel: "icon", href: "/favicon.svg", type: "image/svg+xml" },
  { rel: "apple-touch-icon", href: "/favicon.svg" },
  { rel: "manifest", href: "/site.webmanifest" },
  { rel: "mask-icon", href: "/favicon.svg", color: "#2e6cfc" },
];

/**
 * Document layout component.
 */
export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
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
    useLoaderData<typeof import("./root.loader").loader>();

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
 * Error boundary for the root route.
 */
export function ErrorBoundary() {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Error - Waypoint</title>
      </head>
      <body className="bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 min-h-screen flex items-center justify-center">
        <div className="text-center p-8">
          <h1 className="text-4xl font-bold mb-4">Oops!</h1>
          <p className="text-lg text-zinc-600 dark:text-zinc-400 mb-6">
            Something went wrong. Please try again later.
          </p>
          <a
            href="/"
            className="inline-block px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            Go Home
          </a>
        </div>
      </body>
    </html>
  );
}
