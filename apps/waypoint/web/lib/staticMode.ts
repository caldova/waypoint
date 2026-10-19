/**
 * Static (sign-in-free) build helpers.
 *
 * `STATIC_MODE` is a build-time constant, so the normal build drops every
 * static-only branch.
 */

export const STATIC_MODE: boolean =
  typeof __WAYPOINT_STATIC__ !== "undefined" && __WAYPOINT_STATIC__;

/** Prefix a `public/` path with the app's base path (`/waypoint/` on GitHub Pages). */
export function withBase(path: string): string {
  const base = import.meta.env.BASE_URL || "/";
  if (base === "/" || !path.startsWith("/")) {
    return path;
  }
  return `${base.replace(/\/$/, "")}${path}`;
}
