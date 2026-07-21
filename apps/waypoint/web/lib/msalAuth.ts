import type {
  AccountInfo,
  AuthenticationResult,
  PublicClientApplication,
} from "@azure/msal-browser";

export interface MsalRuntimeConfig {
  enabled: boolean;
  tenantId?: string;
  clientId?: string;
  apiScope?: string;
  redirectUri?: string;
}

const disabledConfig: MsalRuntimeConfig = { enabled: false };

let runtimeConfig = disabledConfig;
let activeConfigKey = "";
let clientPromise: Promise<PublicClientApplication> | null = null;
let tokenPromises = new Map<string, Promise<string | null>>();
let interactiveTokenPromises = new Map<string, Promise<string | null>>();
let graphPhotoPromise: Promise<string | null> | null = null;
let logoutPromise: Promise<void> | null = null;

export type MsalInteractionMode = "none" | "popup" | "redirect";
export const authStateChangedEvent = "waypoint:auth-state-changed";
export const msalLogoutPopupStorageKey = "waypoint:msal:logout-popup";
const graphUserReadScope = "User.Read";
const graphMePhotoUrl = "https://graph.microsoft.com/v1.0/me/photo/$value";

interface MsalTokenOptions {
  interactive?: MsalInteractionMode;
  requireToken?: boolean;
  scopes?: string[];
}

export function configureMsal(config: MsalRuntimeConfig) {
  const nextConfig = normalizeConfig(config);
  const nextConfigKey = JSON.stringify(nextConfig);
  if (nextConfigKey !== activeConfigKey) {
    runtimeConfig = nextConfig;
    activeConfigKey = nextConfigKey;
    clientPromise = null;
    tokenPromises = new Map();
    interactiveTokenPromises = new Map();
    graphPhotoPromise = null;
    logoutPromise = null;
  }
}

export function isMsalEnabled() {
  return runtimeConfig.enabled;
}

export async function authFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
  options: MsalTokenOptions = {},
) {
  if (!runtimeConfig.enabled) {
    return fetch(input, init);
  }

  const accessToken = await getMsalAccessToken(options);
  if (!accessToken) {
    if (options.requireToken) {
      throw new Error("Your Waypoint session needs to be refreshed.");
    }
    return fetch(input, init);
  }

  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  return fetch(input, { ...init, headers });
}

export async function getMsalAccessToken(options: MsalTokenOptions = {}) {
  if (!runtimeConfig.enabled) {
    return null;
  }

  if (options.interactive && options.interactive !== "none") {
    const logoutFinished = await waitForPendingMsalLogout(5_000);
    if (!logoutFinished) {
      throw new Error("Sign-out is still finishing. Please try again in a moment.");
    }
    tokenPromises.clear();
    const tokenKey = getTokenCacheKey(options);
    if (!interactiveTokenPromises.has(tokenKey)) {
      interactiveTokenPromises.set(
        tokenKey,
        acquireAccessToken(options).finally(() => {
          interactiveTokenPromises.delete(tokenKey);
        }),
      );
    }
    return interactiveTokenPromises.get(tokenKey) ?? null;
  }

  const tokenKey = getTokenCacheKey(options);
  if (!tokenPromises.has(tokenKey)) {
    tokenPromises.set(
      tokenKey,
      acquireAccessToken(options).finally(() => {
        tokenPromises.delete(tokenKey);
      }),
    );
  }
  return tokenPromises.get(tokenKey) ?? null;
}

function getTokenCacheKey(options: MsalTokenOptions) {
  const scopes = [...(options.scopes ?? [runtimeConfig.apiScope ?? ""])].sort();
  return scopes.join(" ");
}

export async function getMsalUserPhotoUrl(options: MsalTokenOptions = {}) {
  if (!runtimeConfig.enabled) {
    return null;
  }

  graphPhotoPromise ??= fetchMsalUserPhotoUrl(options).finally(() => {
    graphPhotoPromise = null;
  });
  return graphPhotoPromise;
}

export function notifyAuthStateChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(authStateChangedEvent));
  }
}

export async function signOutWithMsal() {
  if (!runtimeConfig.enabled) {
    notifyAuthStateChanged();
    return;
  }

  logoutPromise ??= performMsalSignOut().finally(() => {
    logoutPromise = null;
  });
  return logoutPromise;
}

export function isMsalLogoutInProgress() {
  return Boolean(logoutPromise);
}

async function waitForPendingMsalLogout(timeoutMs: number) {
  if (!logoutPromise) {
    return true;
  }

  const result = await Promise.race([
    logoutPromise.then(
      () => "done" as const,
      () => "done" as const,
    ),
    new Promise<"timeout">((resolve) => {
      window.setTimeout(() => resolve("timeout"), timeoutMs);
    }),
  ]);

  return result === "done";
}

async function performMsalSignOut() {
  assertBrowser();
  const config = requireEnabledConfig();
  const client = await getClient(config);
  const account = client.getActiveAccount() ?? client.getAllAccounts()[0];
  tokenPromises.clear();
  interactiveTokenPromises.clear();
  graphPhotoPromise = null;
  client.setActiveAccount(null);

  try {
    window.sessionStorage.setItem(msalLogoutPopupStorageKey, "1");
    await client.logoutPopup({
      ...(account ? { account } : {}),
      postLogoutRedirectUri: getPopupRedirectUri(config),
    });
    notifyAuthStateChanged();
  } catch (err) {
    if (!shouldFallbackToRedirectLogout(err)) {
      throw err;
    }
    await client.logoutRedirect({
      ...(account ? { account } : {}),
      postLogoutRedirectUri: getPopupRedirectUri(config),
    });
  } finally {
    window.sessionStorage.removeItem(msalLogoutPopupStorageKey);
  }
}

function normalizeConfig(config: MsalRuntimeConfig): MsalRuntimeConfig {
  return {
    enabled: config.enabled,
    tenantId: normalizeValue(config.tenantId),
    clientId: normalizeValue(config.clientId),
    apiScope: normalizeValue(config.apiScope),
    redirectUri: normalizeValue(config.redirectUri) ?? getCurrentOriginLoginUri(),
  };
}

function normalizeValue(value: string | undefined) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function getCurrentOriginLoginUri() {
  if (typeof window === "undefined") {
    return undefined;
  }
  return new URL("/login", window.location.origin).toString();
}

async function acquireAccessToken(options: MsalTokenOptions) {
  assertBrowser();
  const config = requireEnabledConfig();
  const client = await getClient(config);
  const scopes = options.scopes ?? [config.apiScope];
  const account = await ensureAccount(client, config, scopes, options);
  if (!account) {
    return null;
  }

  const { InteractionRequiredAuthError } = await import("@azure/msal-browser");
  try {
    const result = await client.acquireTokenSilent({
      account,
      scopes,
    });
    return result.accessToken;
  } catch (err) {
    if (err instanceof InteractionRequiredAuthError) {
      if (options.interactive === "popup") {
        const result = await client.acquireTokenPopup({
          account,
          redirectUri: getPopupRedirectUri(config),
          scopes,
        });
        setActiveAccount(client, result);
        return result.accessToken;
      }
      if (options.interactive === "redirect") {
        await client.acquireTokenRedirect({
          account,
          scopes,
          redirectUri: config.redirectUri,
        });
        throw new Error("MSAL interactive token acquisition was started.");
      }
      return null;
    }
    throw err;
  }
}

async function fetchMsalUserPhotoUrl(options: MsalTokenOptions) {
  return withOptionalSpan(
    "msal_graph_user_photo",
    {
      "msal.graph.scope": graphUserReadScope,
      "msal.graph.photo.endpoint": "/me/photo/$value",
    },
    async (span) => {
      const accessToken = await getMsalAccessToken({
        ...options,
        scopes: [graphUserReadScope],
      });
      span?.setAttribute("msal.graph.token.present", Boolean(accessToken));
      if (!accessToken) {
        span?.setAttribute("msal.graph.photo.result", "missing_token");
        return null;
      }

      const response = await fetch(graphMePhotoUrl, {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
      });
      span?.setAttribute("msal.graph.photo.status_code", response.status);
      if (response.status === 404) {
        span?.setAttribute("msal.graph.photo.result", "not_found");
        return null;
      }
      if (!response.ok) {
        span?.setAttribute("msal.graph.photo.result", "failed");
        throw new Error(`Microsoft Graph profile photo returned ${response.status}.`);
      }

      const blob = await response.blob();
      span?.setAttribute("msal.graph.photo.content_type", blob.type || "unknown");
      span?.setAttribute("msal.graph.photo.result", "loaded");
      return blobToDataUrl(blob);
    },
  );
}

async function getClient(config: Required<MsalRuntimeConfig>) {
  clientPromise ??= createClient(config);
  return clientPromise;
}

async function createClient(config: Required<MsalRuntimeConfig>) {
  const { PublicClientApplication } = await import("@azure/msal-browser");
  const client = new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: `https://login.microsoftonline.com/${config.tenantId}`,
      redirectUri: getPopupRedirectUri(config),
    },
    cache: {
      // Teams and Outlook deep links open Waypoint in fresh tabs/windows; keep the
      // MSAL account/token cache origin-wide so those links can reuse the session.
      cacheLocation: "localStorage",
    },
  });

  await client.initialize();
  const redirectResult = await client.handleRedirectPromise({
    navigateToLoginRequestUrl: false,
  });
  setActiveAccount(client, redirectResult);
  if (redirectResult) {
    clearAuthResponseFromUrl();
  }
  return client;
}

async function ensureAccount(
  client: PublicClientApplication,
  config: Required<MsalRuntimeConfig>,
  scopes: string[],
  options: MsalTokenOptions,
) {
  const activeAccount = client.getActiveAccount();
  if (activeAccount) {
    return activeAccount;
  }

  const [firstAccount] = client.getAllAccounts();
  if (firstAccount) {
    client.setActiveAccount(firstAccount);
    return firstAccount;
  }

  if (!options.interactive || options.interactive === "none") {
    try {
      const result = await client.ssoSilent({
        redirectUri: getPopupRedirectUri(config),
        scopes,
      });
      setActiveAccount(client, result);
      return result.account;
    } catch {
      return null;
    }
  }

  if (options.interactive === "popup") {
    const result = await client.loginPopup({
      redirectUri: getPopupRedirectUri(config),
      scopes,
    });
    setActiveAccount(client, result);
    return result.account;
  }
  if (options.interactive === "redirect") {
    await client.loginRedirect({
      redirectStartPage: window.location.href,
      redirectUri: getPopupRedirectUri(config),
      scopes,
    });
    throw new Error("MSAL sign-in was started.");
  }
  return null;
}

function setActiveAccount(
  client: PublicClientApplication,
  redirectResult: AuthenticationResult | null,
) {
  const account = redirectResult?.account ?? client.getAllAccounts()[0];
  if (account) {
    client.setActiveAccount(account as AccountInfo);
  }
}

function requireEnabledConfig(): Required<MsalRuntimeConfig> {
  const missing = [
    ["WAYPOINT_MSAL_TENANT_ID", runtimeConfig.tenantId],
    ["WAYPOINT_MSAL_CLIENT_ID", runtimeConfig.clientId],
    ["WAYPOINT_MSAL_API_SCOPE", runtimeConfig.apiScope],
    ["WAYPOINT_MSAL_REDIRECT_URI", runtimeConfig.redirectUri],
  ]
    .filter(([, value]) => !value)
    .map(([name]) => name);

  if (missing.length) {
    throw new Error(
      `MSAL is enabled but missing required configuration: ${missing.join(", ")}.`,
    );
  }

  return runtimeConfig as Required<MsalRuntimeConfig>;
}

function assertBrowser() {
  if (typeof window === "undefined") {
    throw new Error("MSAL token acquisition is only available in the browser.");
  }
}

function getPopupRedirectUri(config: Required<MsalRuntimeConfig>) {
  return new URL("/auth/msal/callback", config.redirectUri).toString();
}

function clearAuthResponseFromUrl() {
  const nextUrl = new URL(window.location.href);
  for (const name of [
    "code",
    "client_info",
    "state",
    "session_state",
    "error",
    "error_description",
  ]) {
    nextUrl.searchParams.delete(name);
  }

  window.history.replaceState(
    {},
    "",
    `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash.startsWith("#code=") ? "" : nextUrl.hash}`,
  );
}

function shouldFallbackToRedirectLogout(err: unknown) {
  if (!err || typeof err !== "object" || !("errorCode" in err)) {
    return false;
  }

  const errorCode = String(err.errorCode);
  return errorCode === "popup_window_error" || errorCode === "empty_window_error";
}

async function blobToDataUrl(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
        return;
      }
      reject(new Error("Microsoft Graph profile photo could not be read."));
    });
    reader.addEventListener("error", () => {
      reject(reader.error ?? new Error("Microsoft Graph profile photo could not be read."));
    });
    reader.readAsDataURL(blob);
  });
}

async function withOptionalSpan<T>(
  name: string,
  attributes: Record<string, string | number | boolean>,
  fn: (span: import("@opentelemetry/api").Span | null) => Promise<T>,
) {
  let telemetry:
    | [
        typeof import("@opentelemetry/api"),
        typeof import("./telemetry"),
      ]
    | null = null;
  try {
    telemetry = await Promise.all([
      import("@opentelemetry/api"),
      import("./telemetry"),
    ]);
  } catch {
    return fn(null);
  }

  const [{ SpanStatusCode }, { getTracer }] = telemetry;
  return getTracer("msal-auth").startActiveSpan(name, { attributes }, async (span) => {
    try {
      const result = await fn(span);
      span.setStatus({ code: SpanStatusCode.OK });
      return result;
    } catch (error) {
      span.recordException(error as Error);
      span.setStatus({
        code: SpanStatusCode.ERROR,
        message: error instanceof Error ? error.message : "Unknown error",
      });
      throw error;
    } finally {
      span.end();
    }
  });
}
