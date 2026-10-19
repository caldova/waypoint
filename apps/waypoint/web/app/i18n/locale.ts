import { DEFAULT_LOCALE, LOCALE_COOKIE, matchLocale, type Locale } from "./config";
import { isUnlocalizedPath, localizePath, splitLocalePath } from "./paths";

/** The visitor's preferred language: saved cookie choice, then Accept-Language, then English. */
export function preferredLocale(request: Request): Locale {
  return (
    matchLocale(readCookie(request.headers.get("cookie"), LOCALE_COOKIE)) ??
    pickAcceptLanguage(request.headers.get("accept-language")) ??
    DEFAULT_LOCALE
  );
}

/**
 * Where an unprefixed URL should go so the address always shows the language:
 * `/x` → `/es/x` for visitors who prefer Spanish. Returns null when the URL is
 * already right. (`/en/...` is handled by its own redirect route.)
 */
export function localeRedirect(request: Request): string | null {
  const url = new URL(request.url);
  // Client navigations fetch `/path.data?_routes=…` (or `/_root.data` for `/`).
  const pathname = url.pathname === "/_root.data" ? "/" : url.pathname.replace(/\.data$/, "");
  url.searchParams.delete("_routes");
  const search = url.searchParams.size ? `?${url.searchParams}` : "";
  const { path, prefixed } = splitLocalePath(pathname);

  if (prefixed || isUnlocalizedPath(path)) {
    return null;
  }
  const preferred = preferredLocale(request);
  return preferred === DEFAULT_LOCALE ? null : `${localizePath(path, preferred)}${search}`;
}

export function pickAcceptLanguage(header: string | null | undefined): Locale | null {
  if (!header) {
    return null;
  }

  const ranked = header
    .split(",")
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(";");
      const qParam = params.map((param) => param.trim()).find((param) => param.startsWith("q="));
      const quality = qParam ? Number.parseFloat(qParam.slice(2)) : 1;
      return { tag, quality: Number.isFinite(quality) ? quality : 0, index };
    })
    .filter((entry) => entry.tag && entry.quality > 0)
    .sort((a, b) => b.quality - a.quality || a.index - b.index);

  for (const entry of ranked) {
    const locale = matchLocale(entry.tag);
    if (locale) {
      return locale;
    }
  }
  return null;
}

function readCookie(header: string | null, name: string): string | null {
  if (!header) {
    return null;
  }
  for (const pair of header.split(";")) {
    const separator = pair.indexOf("=");
    if (separator === -1) {
      continue;
    }
    if (pair.slice(0, separator).trim() === name) {
      try {
        return decodeURIComponent(pair.slice(separator + 1).trim());
      } catch {
        return null;
      }
    }
  }
  return null;
}
