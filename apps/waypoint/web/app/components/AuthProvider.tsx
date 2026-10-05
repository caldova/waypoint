import {
  SpanStatusCode,
  trace,
  type Span,
} from "@opentelemetry/api";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  authFetch,
  authStateChangedEvent,
  configureMsal,
  getMsalUserPhotoUrl,
  isMsalLogoutInProgress,
  signOutWithMsal,
  type MsalRuntimeConfig,
} from "../../lib/msalAuth";

export interface UserProfile {
  email: string;
  name: string;
  source: string;
  avatarUrl?: string;
}

export type AuthStatus = "checking" | "authenticated" | "unauthenticated";

export interface AuthState {
  status: AuthStatus;
  user: UserProfile | null;
  error: string | null;
  isConfigured: boolean;
  isSigningOut: boolean;
  refresh: (options?: RefreshOptions) => Promise<UserProfile | null>;
  signIn: () => Promise<UserProfile>;
  signOut: () => Promise<void>;
}

export interface RefreshOptions {
  force?: boolean;
}

interface AuthProviderProps {
  children: ReactNode;
  localMode: boolean;
  msalConfig: MsalRuntimeConfig;
}

const emailDomainRewrites: Record<string, string> = {
  "notareal.co": "caldova.com",
};

function rewriteEmailDomain(email: string): string {
  const atIndex = email.lastIndexOf("@");
  if (atIndex === -1) {
    return email;
  }
  const local = email.slice(0, atIndex);
  const domain = email.slice(atIndex + 1);
  const replacement = emailDomainRewrites[domain.toLowerCase()];
  return replacement ? `${local}@${replacement}` : email;
}

function normalizeProfile(profile: UserProfile | null): UserProfile | null {
  if (!profile) {
    return profile;
  }
  return { ...profile, email: rewriteEmailDomain(profile.email) };
}

const devUser: UserProfile = {
  email: "analyst@caldova.example",
  name: "Caldova Analyst",
  source: "local-dev",
  avatarUrl: "",
};

const authRevalidateMs = 60_000;

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({
  children,
  localMode,
  msalConfig,
}: AuthProviderProps) {
  configureMsal(msalConfig);
  const isConfigured = localMode || msalConfig.enabled;
  const [status, setStatus] = useState<AuthStatus>(
    localMode ? "authenticated" : "checking",
  );
  const [user, setUser] = useState<UserProfile | null>(
    localMode ? normalizeProfile(devUser) : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const statusRef = useRef<AuthStatus>(localMode ? "authenticated" : "checking");
  const userRef = useRef<UserProfile | null>(
    localMode ? normalizeProfile(devUser) : null,
  );
  const lastValidatedAtRef = useRef(localMode ? Date.now() : 0);
  const refreshPromiseRef = useRef<Promise<UserProfile | null> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const setAuthState = useCallback(
    (
      nextStatus: AuthStatus,
      rawNextUser: UserProfile | null,
      nextError: string | null,
      reason: string,
    ) => {
      const nextUser = normalizeProfile(rawNextUser);
      const previousStatus = statusRef.current;
      statusRef.current = nextStatus;
      userRef.current = nextUser;
      setStatus(nextStatus);
      setUser(nextUser);
      setError(nextError);
      if (nextStatus === "authenticated") {
        lastValidatedAtRef.current = Date.now();
      }
      emitClientAuthEvent("client_auth_state", {
        previousStatus,
        nextStatus,
        reason,
        userPresent: Boolean(nextUser),
        errorPresent: Boolean(nextError),
      });
    },
    [],
  );

  const refresh = useCallback(async (options: RefreshOptions = {}) => {
    return traceClientAuthOperation(
      "auth_refresh",
      {
        "auth.local_mode": localMode,
        "auth.configured": isConfigured,
        "auth.refresh.force": Boolean(options.force),
        "auth.status.current": statusRef.current,
        "auth.user.present": Boolean(userRef.current),
      },
      async (span) => {
        if (localMode) {
          setAuthState("authenticated", devUser, null, "local_mode");
          span?.setAttribute("auth.refresh.result", "local_mode");
          return normalizeProfile(devUser);
        }

        if (!isConfigured) {
          setAuthState(
            "unauthenticated",
            null,
            "Microsoft sign-in is not configured.",
            "not_configured",
          );
          span?.setAttribute("auth.refresh.result", "not_configured");
          return null;
        }

        if (
          !options.force &&
          statusRef.current === "authenticated" &&
          userRef.current &&
          Date.now() - lastValidatedAtRef.current < authRevalidateMs
        ) {
          span?.setAttribute("auth.refresh.result", "cached_authenticated");
          return userRef.current;
        }

        if (refreshPromiseRef.current) {
          span?.setAttribute("auth.refresh.result", "coalesced");
          return refreshPromiseRef.current;
        }

        if (statusRef.current !== "authenticated") {
          setAuthState("checking", userRef.current, null, "refresh_start");
        }

        refreshPromiseRef.current = loadUserProfile()
          .then((profile) => {
            setAuthState(
              profile ? "authenticated" : "unauthenticated",
              profile,
              null,
              profile ? "profile_loaded" : "profile_missing",
            );
            span?.setAttribute(
              "auth.refresh.result",
              profile ? "authenticated" : "unauthenticated",
            );
            return profile;
          })
          .catch((error) => {
            setAuthState("unauthenticated", null, null, "profile_error");
            span?.setAttribute("auth.refresh.result", "profile_error");
            span?.setAttribute(
              "auth.refresh.error_name",
              error instanceof Error ? error.name : "UnknownError",
            );
            throw error;
          })
          .finally(() => {
            refreshPromiseRef.current = null;
          });

        return refreshPromiseRef.current;
      },
    ).catch(() => null);
  }, [isConfigured, localMode, setAuthState]);

  const signIn = useCallback(async () => {
    return traceClientAuthOperation(
      "auth_sign_in",
      {
        "auth.local_mode": localMode,
        "auth.configured": isConfigured,
        "auth.status.current": statusRef.current,
      },
      async (span) => {
        if (localMode) {
          setAuthState("authenticated", devUser, null, "local_mode_sign_in");
          span?.setAttribute("auth.sign_in.result", "local_mode");
          return normalizeProfile(devUser) as UserProfile;
        }

        if (!isConfigured) {
          span?.setAttribute("auth.sign_in.result", "not_configured");
          throw new Error("Microsoft sign-in is not configured.");
        }

        setAuthState("checking", userRef.current, null, "sign_in_start");
        try {
          const profile = await loadUserProfile({ interactive: "popup" });
          if (!profile) {
            throw new Error("Caldova could not load your profile.");
          }
          setAuthState("authenticated", profile, null, "sign_in_success");
          span?.setAttribute("auth.sign_in.result", "authenticated");
          return profile;
        } catch (err) {
          setAuthState(
            "unauthenticated",
            null,
            getUserFacingAuthError(err),
            "sign_in_error",
          );
          const errorDetails = getAuthErrorDetails(err);
          span?.setAttribute("auth.sign_in.result", "error");
          span?.setAttribute("auth.sign_in.error_name", errorDetails.errorName);
          if (errorDetails.errorCode) {
            span?.setAttribute("auth.sign_in.error_code", errorDetails.errorCode);
          }
          throw err;
        }
      },
    );
  }, [isConfigured, localMode, setAuthState]);

  const signOut = useCallback(async () => {
    setIsSigningOut(!localMode);
    setAuthState(
      localMode ? "authenticated" : "unauthenticated",
      localMode ? devUser : null,
      null,
      "sign_out",
    );
    if (!localMode) {
      const timeoutId = window.setTimeout(() => {
        if (mountedRef.current) {
          setIsSigningOut(false);
        }
      }, 7_000);
      void signOutWithMsal()
        .catch((error: unknown) => {
          console.warn("Microsoft sign-out could not be completed", getAuthErrorDetails(error));
        })
        .finally(() => {
          window.clearTimeout(timeoutId);
          if (mountedRef.current) {
            setIsSigningOut(isMsalLogoutInProgress());
          }
        });
    }
  }, [localMode, setAuthState]);

  useEffect(() => {
    void refresh();
    const forceRefresh = () => {
      void refresh({ force: true });
    };
    window.addEventListener(authStateChangedEvent, forceRefresh);
    return () => {
      window.removeEventListener(authStateChangedEvent, forceRefresh);
    };
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({
      status,
      user,
      error,
      isConfigured,
      isSigningOut,
      refresh,
      signIn,
      signOut,
    }),
    [error, isConfigured, isSigningOut, refresh, signIn, signOut, status, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const auth = useContext(AuthContext);
  if (!auth) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return auth;
}

async function loadUserProfile(options: { interactive?: "popup" } = {}) {
  return traceClientAuthOperation(
    "auth_load_user_profile",
    {
      "auth.interactive": options.interactive ?? "none",
    },
    async (span) => {
      const response = await authFetch("/api/user/me", undefined, {
        interactive: options.interactive,
        requireToken: true,
      });
      span?.setAttribute("http.status_code", response.status);
      if (!response.ok) {
        if (response.status === 401) {
          span?.setAttribute("auth.profile.result", "unauthorized");
          return null;
        }
        span?.setAttribute("auth.profile.result", "failed");
        throw new Error(`Caldova profile returned ${response.status}.`);
      }

      const profile = (await response.json()) as UserProfile;
      span?.setAttribute("auth.profile.result", "loaded");
      span?.setAttribute("auth.profile.source", profile.source);
      try {
        const avatarUrl = await getMsalUserPhotoUrl();
        span?.setAttribute("auth.profile.avatar_present", Boolean(avatarUrl));
        if (avatarUrl) {
          profile.avatarUrl = avatarUrl;
        }
      } catch (error) {
        span?.setAttribute("auth.profile.avatar_error", true);
        span?.setAttribute(
          "auth.profile.avatar_error_name",
          error instanceof Error ? error.name : "UnknownError",
        );
        console.warn("Microsoft Graph profile photo could not be loaded", {
          errorName: error instanceof Error ? error.name : "UnknownError",
        });
      }
      return normalizeProfile(profile) as UserProfile;
    },
  );
}

async function traceClientAuthOperation<T>(
  name: string,
  attributes: Record<string, string | number | boolean>,
  fn: (span: Span | null) => Promise<T>,
) {
  emitClientAuthEvent("client_auth_span_start", {
    name,
    ...attributes,
  });

  return trace.getTracer("auth").startActiveSpan(name, { attributes }, async (span) => {
    try {
      const result = await fn(span);
      span.setStatus({ code: SpanStatusCode.OK });
      emitClientAuthEvent("client_auth_span_end", {
        name,
        result: "ok",
      });
      return result;
    } catch (error) {
      const errorDetails = getAuthErrorDetails(error);
      span.recordException(error as Error);
      span.setAttribute("auth.error_name", errorDetails.errorName);
      if (errorDetails.errorCode) {
        span.setAttribute("auth.error_code", errorDetails.errorCode);
      }
      if (errorDetails.subError) {
        span.setAttribute("auth.sub_error", errorDetails.subError);
      }
      span.setStatus({
        code: SpanStatusCode.ERROR,
        message: errorDetails.errorCode ?? errorDetails.errorName,
      });
      emitClientAuthEvent("client_auth_span_end", {
        name,
        result: "error",
        errorName: errorDetails.errorName,
        errorCode: errorDetails.errorCode,
        subError: errorDetails.subError,
      });
      throw error;
    } finally {
      span.end();
    }
  });
}

function getUserFacingAuthError(error: unknown) {
  const details = getAuthErrorDetails(error);
  if (details.errorMessage?.startsWith("Sign-out is still finishing.")) {
    return details.errorMessage;
  }
  return "Sign-in failed.";
}

function getAuthErrorDetails(error: unknown) {
  const errorObject =
    error && typeof error === "object" ? (error as Record<string, unknown>) : {};
  const errorName =
    error instanceof Error
      ? error.name
      : typeof errorObject.name === "string"
        ? errorObject.name
        : "UnknownError";
  const errorMessage =
    error instanceof Error
      ? error.message
      : typeof errorObject.message === "string"
        ? errorObject.message
        : undefined;

  return {
    errorName,
    errorCode: getStringProperty(errorObject, "errorCode"),
    subError: getStringProperty(errorObject, "subError"),
    errorMessage: errorMessage ? errorMessage.slice(0, 240) : undefined,
  };
}

function getStringProperty(source: Record<string, unknown>, key: string) {
  const value = source[key];
  return typeof value === "string" && value ? value.slice(0, 120) : undefined;
}

function emitClientAuthEvent(
  event: string,
  details: Record<string, string | number | boolean | null | undefined>,
) {
  if (typeof window === "undefined") {
    return;
  }

  const body = JSON.stringify({
    event,
    details,
    path: window.location.pathname,
    timestamp: new Date().toISOString(),
  });

  try {
    if (navigator.sendBeacon) {
      const queued = navigator.sendBeacon(
        "/client-telemetry",
        new Blob([body], { type: "application/json" }),
      );
      if (queued) {
        return;
      }
    }
    void fetch("/client-telemetry", {
      body,
      headers: { "content-type": "application/json" },
      keepalive: true,
      method: "POST",
    }).catch(() => {});
  } catch {
    // Diagnostics should never affect auth flow.
  }
}
