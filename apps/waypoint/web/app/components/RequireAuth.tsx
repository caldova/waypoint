import { useEffect, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { useTranslation } from "react-i18next";
import { useAuth } from "./AuthProvider";
import { useLocale } from "../i18n/LocaleProvider";

export function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { t } = useTranslation("auth");
  const { localize } = useLocale();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (auth.status !== "unauthenticated") {
      return;
    }

    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    navigate(localize(`/login?returnTo=${encodeURIComponent(returnTo)}`), { replace: true });
  }, [auth.status, localize, location.hash, location.pathname, location.search, navigate]);

  if (auth.status !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 text-center text-slate-950">
        <div className="w-full max-w-sm rounded-lg border border-slate-200 bg-white px-6 py-5 shadow-sm">
          <div
            aria-hidden="true"
            className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-blue-100 border-t-blue-600"
          />
          <p className="mt-3 text-sm font-medium text-slate-700">
            {t("checkingSignIn")}
          </p>
        </div>
      </div>
    );
  }

  return children;
}
