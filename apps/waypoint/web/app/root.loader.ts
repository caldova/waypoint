/**
 * Root loader - provides configuration to the client.
 *
 * This loader runs on the server and exposes:
 * - OpenTelemetry configuration for browser tracing
 * - Environment flags
 */

export function loader() {
  // Browsers send spans to a same-origin proxy when the web container has an
  // OTLP endpoint. Server-side proxying keeps exporter headers out of the page.
  const hasOtlpEndpoint = Boolean(
    process.env.OTEL_EXPORTER_OTLP_HTTP_ENDPOINT ||
      process.env.ASPIRE_DASHBOARD_OTLP_HTTP_ENDPOINT_URL ||
      process.env.OTEL_EXPORTER_OTLP_ENDPOINT,
  );
  const isDev = process.env.NODE_ENV === "development";

  const otelConfig = {
    serviceName: process.env.OTEL_SERVICE_NAME || "waypoint-web",
    resourceAttributes: process.env.OTEL_RESOURCE_ATTRIBUTES || undefined,
    tracesSampler: process.env.OTEL_TRACES_SAMPLER || undefined,
    otlpHttpEndpoint: hasOtlpEndpoint ? "/otlp/v1/traces" : undefined,
    otlpHeaders: undefined,
  };

  return {
    otelConfig,
    msalConfig: {
      enabled: parseBoolean(process.env.WAYPOINT_MSAL_ENABLED),
      tenantId: process.env.WAYPOINT_MSAL_TENANT_ID || undefined,
      clientId: process.env.WAYPOINT_MSAL_CLIENT_ID || undefined,
      apiScope: process.env.WAYPOINT_MSAL_API_SCOPE || undefined,
      redirectUri: process.env.WAYPOINT_MSAL_REDIRECT_URI || undefined,
    },
    env: {
      DEV: isDev,
      localMode: isDev,
    },
    buildVersion: typeof __BUILD_VERSION__ !== "undefined" ? __BUILD_VERSION__ : "unknown",
  };
}

function parseBoolean(value: string | undefined) {
  return ["1", "true", "yes", "on"].includes(value?.trim().toLowerCase() ?? "");
}
