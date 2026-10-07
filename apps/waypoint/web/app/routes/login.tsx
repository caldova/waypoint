import type { MetaFunction } from "react-router";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useEffect, useState } from "react";
import { HiArrowRight } from "react-icons/hi";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { useAuth } from "../components/AuthProvider";
import { LanguageSwitcher } from "../components/LanguageSwitcher";
import { pageMeta } from "../i18n/meta";
import { SignOutPendingError } from "../../lib/msalAuth";

export const meta: MetaFunction = ({ matches }) => pageMeta(matches, "login");

export default function Login() {
  const auth = useAuth();
  const { t } = useTranslation(["auth", "common"]);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const returnTo = sanitizeReturnTo(searchParams.get("returnTo"));

  useEffect(() => {
    if (auth.status === "authenticated") {
      navigate(returnTo, { replace: true });
    }
  }, [auth.status, navigate, returnTo]);

  const handleSignIn = async () => {
    setIsSigningIn(true);
    setMessage(null);
    try {
      await auth.signIn();
      navigate(returnTo, { replace: true });
    } catch (error) {
      setMessage(getSignInErrorMessage(error, t));
    } finally {
      setIsSigningIn(false);
    }
  };

  const signInDisabled =
    isSigningIn || auth.status === "checking" || auth.isSigningOut || !auth.isConfigured;

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-4 py-8 text-slate-950">
      <section className="w-full max-w-sm rounded-xl border border-white/10 bg-white p-6 shadow-2xl">
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="h-9 w-9" />
          <div>
            <p className="text-sm font-semibold text-blue-900">{t("common:app.name")}</p>
            <h1 className="text-xl font-semibold tracking-tight text-slate-950">
              {t("login.heading")}
            </h1>
          </div>
        </div>

        <p className="mt-5 text-sm leading-6 text-slate-600">
          {t("login.intro")}
        </p>

        <div className="mt-5">
          {auth.status === "authenticated" ? (
            <Link
              to={returnTo}
              className="flex min-h-11 w-full items-center justify-center rounded-md bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800"
            >
              {t("login.continue")}
            </Link>
          ) : (
            <button
              type="button"
              onClick={handleSignIn}
              disabled={signInDisabled}
              className="flex min-h-11 w-full items-center justify-center gap-2 rounded-md bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {auth.isSigningOut
                ? t("login.finishingSignOut")
                : isSigningIn || auth.status === "checking"
                ? t("login.checkingSignIn")
                : t("login.signIn")}
              <HiArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>

        {message ?? auth.error ? (
          <p className="mt-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-5 text-amber-900">
            {message ?? auth.error}
          </p>
        ) : null}

        {!auth.isConfigured ? (
          <p className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm leading-5 text-slate-600">
            {t("login.notConfigured")}
          </p>
        ) : null}

        <LanguageSwitcher className="mt-5 border-t border-slate-100 pt-4" />
      </section>
    </main>
  );
}

function sanitizeReturnTo(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/";
  }
  if (value.startsWith("/login") || value.startsWith("/auth/msal/callback")) {
    return "/";
  }
  return value;
}

function getSignInErrorMessage(error: unknown, t: TFunction<"auth">) {
  if (error instanceof SignOutPendingError) {
    return t("errors.signOutPending");
  }
  return t("login.failed");
}
