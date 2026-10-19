import { reactRouter } from "@react-router/dev/vite";
import { defineConfig, type Plugin } from "vite";
import tsconfigPaths from "vite-tsconfig-paths";
import tailwindcss from "@tailwindcss/vite";
import { isStaticBuild, staticBasePath } from "./static-build";

// Build version from environment or generate from timestamp
const now = new Date();
const buildVersion =
  process.env.BUILD_VERSION ||
  `dev-${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}-${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;

const otlpEndpoint =
  process.env.OTEL_EXPORTER_OTLP_HTTP_ENDPOINT ||
  process.env.ASPIRE_DASHBOARD_OTLP_HTTP_ENDPOINT_URL ||
  process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
const otlpHeaders = parseOtlpHeaders(process.env.OTEL_EXPORTER_OTLP_HEADERS);

export default defineConfig({
  ...(isStaticBuild ? { base: staticBasePath } : {}),
  define: {
    __BUILD_VERSION__: JSON.stringify(buildVersion),
    __IS_DEV__: JSON.stringify(!process.env.BUILD_VERSION),
    __WAYPOINT_STATIC__: JSON.stringify(isStaticBuild),
  },
  resolve: {
    dedupe: ["react", "react-dom", "react-router"],
  },
  optimizeDeps: {
    include: ["react", "react-dom/client", "react-router"],
  },
  ssr: {
    noExternal: ["react-router"],
  },
  plugins: [
    ...(isStaticBuild ? [dropServerOnlyRootExports()] : []),
    tailwindcss(),
    reactRouter(),
    tsconfigPaths(),
  ],
  server: {
    proxy: {
      // Proxy API requests to the FastAPI backend during development
      "/api": {
        target: process.env.API_ENDPOINT_HTTP || "http://localhost:8000",
        changeOrigin: true,
        secure: false,
        ws: true, // Enable WebSocket proxying
      },
      ...(otlpEndpoint
        ? {
            "/otlp": {
              target: otlpEndpoint,
              changeOrigin: true,
              secure: false,
              rewrite: (path) => path.replace(/^\/otlp/, ""),
              configure: (proxy) => {
                proxy.on("proxyReq", (proxyReq) => {
                  proxyReq.removeHeader("authorization");
                  proxyReq.removeHeader("cookie");
                  for (const [key, value] of Object.entries(otlpHeaders)) {
                    proxyReq.setHeader(key, value);
                  }
                });
              },
            },
          }
        : {}),
    },
  },
});

function parseOtlpHeaders(value: string | undefined) {
  const headers: Record<string, string> = {};
  if (!value) {
    return headers;
  }

  for (const pair of value.split(",")) {
    const [key, headerValue] = pair.split("=").map((part) => part.trim());
    if (key && headerValue) {
      headers[key] = headerValue;
    }
  }

  return headers;
}

/**
 * The static build prerenders with `ssr: false`, where React Router rejects
 * response `headers` exports. The root's `headers` only matters for the SSR
 * server, so the static build un-exports it.
 */
function dropServerOnlyRootExports(): Plugin {
  return {
    name: "waypoint-static-drop-root-headers",
    enforce: "pre",
    transform(code, id) {
      if (!/[\\/]app[\\/]root\.tsx$/.test(id.split("?")[0])) {
        return null;
      }
      return code.replace(/^export const headers\b/m, "const headers");
    },
  };
}
