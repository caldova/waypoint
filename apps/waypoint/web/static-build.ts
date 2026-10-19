/**
 * Build settings for the static, sign-in-free copy of the app (GitHub Pages).
 *
 * `WAYPOINT_STATIC=true` switches the build to a prerendered SPA that serves its
 * data from `public/static-data/` instead of the Waypoint API. The normal SSR
 * build is untouched when the flag is unset.
 */

export const isStaticBuild = process.env.WAYPOINT_STATIC === "true";

/** URL prefix the static site is served from, e.g. `/waypoint/` for caldova.github.io/waypoint. */
export const staticBasePath = normalizeBasePath(process.env.WAYPOINT_STATIC_BASE ?? "/waypoint/");

function normalizeBasePath(value: string): string {
  const trimmed = value.trim().replace(/^\/+|\/+$/g, "");
  return trimmed ? `/${trimmed}/` : "/";
}
