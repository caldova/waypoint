/**
 * Production server for React Router v7 with API proxy.
 *
 * This server:
 * 1. Proxies /api requests to the FastAPI backend
 * 2. Serves the React Router SSR application
 *
 * Environment variables:
 * - API_ENDPOINT_HTTP: Backend API URL (default: http://localhost:8000)
 * - PORT: Server port (default: 3000)
 */

import { existsSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { createRequestHandler } from "@react-router/express";
import compression from "compression";
import express from "express";
import { createProxyMiddleware, fixRequestBody } from "http-proxy-middleware";

const app = express();

function getOtlpHttpTarget() {
  const endpoint =
    process.env.OTEL_EXPORTER_OTLP_HTTP_ENDPOINT ||
    process.env.ASPIRE_DASHBOARD_OTLP_HTTP_ENDPOINT_URL ||
    process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  if (!endpoint) {
    return "";
  }

  return endpoint
    .replace(":4317", ":4318")
    .replace(":21021", ":21022")
    .replace(":19140", ":19141")
    .replace(/\/v1\/traces\/?$/, "");
}

function getOtlpHeaders() {
  const headers = {};
  const rawHeaders = process.env.OTEL_EXPORTER_OTLP_HEADERS;
  if (!rawHeaders) {
    return headers;
  }

  for (const pair of rawHeaders.split(",")) {
    const [key, value] = pair.split("=");
    if (key?.trim() && value?.trim()) {
      headers[key.trim()] = value.trim();
    }
  }
  return headers;
}

function logProxyEvent(event, req, extra = {}) {
  const hasAuthorization = Boolean(req.headers?.authorization);
  const traceparent = req.headers?.traceparent;
  console.log(
    JSON.stringify({
      event,
      method: req.method,
      path: req.originalUrl || req.url,
      target: apiTarget,
      hasAuthorization,
      traceparentPresent: Boolean(traceparent),
      traceId: typeof traceparent === "string" ? traceparent.split("-")[1] : undefined,
      ...extra,
    }),
  );
}

// Parse larger admin seed/import payloads before proxying API requests.
app.use("/api", express.json({ limit: "10mb" }));

// API proxy configuration
const apiTarget = process.env.API_ENDPOINT_HTTP || "http://localhost:8000";
console.log(`Proxying /api requests to: ${apiTarget}`);

// Reuse connections to the API. Without an agent, http-proxy opens a new
// TCP + TLS connection for every request, which intermittently added seconds
// to calls like the sign-in check (/api/user/me).
const apiAgent = apiTarget.startsWith("https:")
  ? new https.Agent({ keepAlive: true, maxSockets: 64 })
  : new http.Agent({ keepAlive: true, maxSockets: 64 });
const proxyStartedAt = new WeakMap();

const otlpTarget = getOtlpHttpTarget();
const otlpHeaders = getOtlpHeaders();
if (otlpTarget) {
  console.log(`Proxying browser OTLP traces to: ${otlpTarget}`);
}

const apiProxy = createProxyMiddleware({
  target: apiTarget,
  changeOrigin: true,
  agent: apiAgent,
  pathFilter: (path) => path.startsWith("/api"),
  ws: true, // Enable WebSocket proxying
  on: {
    proxyReq: (proxyReq, req) => {
      // Fix request body for JSON requests
      fixRequestBody(proxyReq, req);
      proxyStartedAt.set(req, Date.now());
      logProxyEvent("api_proxy_request", req);
    },
    proxyRes: (proxyRes, req) => {
      const startedAt = proxyStartedAt.get(req);
      logProxyEvent("api_proxy_response", req, {
        statusCode: proxyRes.statusCode,
        durationMs: startedAt ? Date.now() - startedAt : undefined,
      });
    },
    error: (err, req, res) => {
      logProxyEvent("api_proxy_error", req, {
        errorName: err.name,
        errorMessage: err.message,
      });
      if (res.writeHead) {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Bad Gateway", message: err.message }));
      }
    },
  },
});

app.post("/client-telemetry", express.json({ limit: "32kb" }), (req, res) => {
  const body = req.body && typeof req.body === "object" ? req.body : {};
  console.log(
    JSON.stringify({
      event: "client_telemetry",
      clientEvent: typeof body.event === "string" ? body.event : "unknown",
      details: body.details && typeof body.details === "object" ? body.details : {},
      path: typeof body.path === "string" ? body.path : undefined,
      timestamp: typeof body.timestamp === "string" ? body.timestamp : undefined,
    }),
  );
  res.status(204).end();
});

if (otlpTarget) {
  app.post(
    "/otlp/v1/traces",
    createProxyMiddleware({
      target: otlpTarget,
      changeOrigin: true,
      pathRewrite: { "^/otlp": "" },
      on: {
        proxyReq: (proxyReq, req) => {
          proxyReq.removeHeader("authorization");
          proxyReq.removeHeader("cookie");
          for (const [key, value] of Object.entries(otlpHeaders)) {
            proxyReq.setHeader(key, value);
          }
          console.log(
            JSON.stringify({
              event: "browser_otlp_proxy_request",
              method: req.method,
              path: req.originalUrl || req.url,
              target: otlpTarget,
            }),
          );
        },
        proxyRes: (proxyRes, req) => {
          console.log(
            JSON.stringify({
              event: "browser_otlp_proxy_response",
              method: req.method,
              path: req.originalUrl || req.url,
              statusCode: proxyRes.statusCode,
            }),
          );
        },
        error: (err, req, res) => {
          console.log(
            JSON.stringify({
              event: "browser_otlp_proxy_error",
              method: req.method,
              path: req.originalUrl || req.url,
              errorName: err.name,
              errorMessage: err.message,
            }),
          );
          if (res.writeHead) {
            res.writeHead(502).end();
          }
        },
      },
    }),
  );
}

// Mount API proxy
app.use(apiProxy);

// MSAL popup and hidden-iframe redirect target. MSAL v5 waits for the page at
// the redirect URI to call broadcastResponseToMainFrame(); serving the full app
// route there meant every silent token renewal booted the whole SPA inside a
// hidden iframe and often hit MSAL's 10 s timeout. This static page loads only
// MSAL's 6 KB redirect bridge. Falls back to the app route if either file is missing.
const msalCallbackPage = path.resolve("build/client/msal-callback.html");
const msalBridgeScript = path.resolve(
  "node_modules/@azure/msal-browser/lib/redirect-bridge/msal-redirect-bridge.min.js",
);
if (existsSync(msalCallbackPage) && existsSync(msalBridgeScript)) {
  app.get("/msal-redirect-bridge.js", (_req, res) => {
    res.set("Cache-Control", "public, max-age=3600");
    res.type("application/javascript").sendFile(msalBridgeScript);
  });
  app.get("/auth/msal/callback", (_req, res) => {
    res.set("Cache-Control", "no-store");
    res.type("html").sendFile(msalCallbackPage);
  });
} else {
  console.warn("Static MSAL callback unavailable; using the app route for /auth/msal/callback.");
}

// Compress pages and static files. Mounted after the API and OTLP proxies so
// proxied responses stream through untouched.
app.use(compression());

// Serve static assets from the build. Files under /assets/ have a content hash
// in their name, so browsers can cache them for a year; every deploy produces
// new names. Everything else keeps the default revalidation.
app.use(
  express.static("build/client", {
    setHeaders: (res, filePath) => {
      if (filePath.includes(`${path.sep}assets${path.sep}`)) {
        res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
      }
    },
  }),
);

// Handle all other requests with React Router
const build = await import("./build/server/index.js");
app.all("*", createRequestHandler({ build }));

// Start server
const port = process.env.PORT || 3000;
app.listen(port, () => {
  console.log(`Server running at http://localhost:${port}`);
});
