#!/usr/bin/env node
/**
 * Build the static, sign-in-free copy of the app for GitHub Pages.
 *
 *   npm run build:static                       # served from /waypoint/
 *   WAYPOINT_STATIC_BASE=/ npm run build:static  # served from the domain root
 *
 * Output: build/client (upload as-is). Data comes from ./static-data, written by
 * scripts/snapshot-static-data.mjs.
 */

import { spawnSync } from "node:child_process";
import { cpSync, copyFileSync, existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const clientDir = join(webDir, "build", "client");
const dataDir = join(webDir, "static-data");

const base = normalizeBase(process.env.WAYPOINT_STATIC_BASE ?? "/waypoint/");
const env = {
  ...process.env,
  WAYPOINT_STATIC: "true",
  WAYPOINT_STATIC_BASE: base,
  // Same format the production deploy stamps (shown in the user menu).
  BUILD_VERSION: process.env.BUILD_VERSION || new Date().toISOString().replace(/[-:]/g, "").replace("T", ".").slice(0, 15),
};

if (!existsSync(join(dataDir, "snapshot.json"))) {
  console.error(
    "static-data/snapshot.json is missing. Run scripts/snapshot-static-data.mjs first (see docs/static-clone.md).",
  );
  process.exit(1);
}

const build = spawnSync("npx", ["react-router", "build"], {
  cwd: webDir,
  env,
  stdio: "inherit",
  shell: process.platform === "win32",
});
if (build.status !== 0) {
  process.exit(build.status ?? 1);
}

// Prerendered pages are written under build/client/<base>/, while Pages serves
// the artifact root at <base>. Flatten so both line up.
const baseSegments = base.split("/").filter(Boolean);
if (baseSegments.length > 0) {
  const prerenderDir = join(clientDir, ...baseSegments);
  if (existsSync(prerenderDir)) {
    cpSync(prerenderDir, clientDir, { recursive: true });
    rmSync(join(clientDir, baseSegments[0]), { recursive: true, force: true });
  }
}

// Data the in-browser API reads.
cpSync(dataDir, join(clientDir, "static-data"), { recursive: true });

// GitHub Pages serves 404.html for unknown paths; let the app route them.
const fallback = ["__spa-fallback.html", "index.html"]
  .map((name) => join(clientDir, name))
  .find((file) => existsSync(file));
if (fallback) {
  copyFileSync(fallback, join(clientDir, "404.html"));
}

// Serve files as-is (no Jekyll processing of underscore-prefixed assets).
writeFileSync(join(clientDir, ".nojekyll"), "");

// The web manifest uses root-relative URLs; point them at the base path.
const manifestPath = join(clientDir, "site.webmanifest");
if (existsSync(manifestPath)) {
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  manifest.start_url = base;
  manifest.icons = (manifest.icons ?? []).map((icon) => ({
    ...icon,
    src: icon.src?.startsWith("/") ? `${base}${icon.src.slice(1)}` : icon.src,
  }));
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
}

console.log(`Static site ready in build/client (base ${base}).`);

function normalizeBase(value) {
  const trimmed = value.trim().replace(/^\/+|\/+$/g, "");
  return trimmed ? `/${trimmed}/` : "/";
}
