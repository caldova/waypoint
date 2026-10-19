import type { Config } from "@react-router/dev/config";
import { isStaticBuild, staticBasePath } from "./static-build";

const serverConfig = {
  // Enable server-side rendering
  ssr: true,
  // Runtime auth and telemetry config comes from the root loader; do not
  // prerender routes that would freeze container environment values at build time.
  prerender: [],
} satisfies Config;

// Static copy for GitHub Pages: every page is prerendered to HTML at build time.
const staticConfig = {
  ssr: false,
  basename: staticBasePath,
  prerender: true,
} satisfies Config;

export default (isStaticBuild ? staticConfig : serverConfig) satisfies Config;
