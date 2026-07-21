/**
 * Route definitions for React Router v7.
 */

import { type RouteConfig, index, route } from "@react-router/dev/routes";

export default [
  index("routes/home.tsx"),
  route("login", "routes/login.tsx"),
  route("auth/msal/callback", "routes/auth.msal.callback.tsx"),
  route("client-telemetry", "routes/client-telemetry.tsx"),
  route("agent", "routes/agent.tsx"),
  route("activity", "routes/activity.tsx"),
  route("invoices", "routes/invoices.tsx"),
] satisfies RouteConfig;
