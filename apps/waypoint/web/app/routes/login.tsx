import type { MetaFunction } from "react-router";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useEffect, useState } from "react";
import { HiArrowRight } from "react-icons/hi";
import { useAuth } from "../components/AuthProvider";

export const meta: MetaFunction = () => [
  { title: "Sign in - Caldova" },
  {
    name: "description",
    content: "Sign in to Caldova",
  },
];

export default function Login() {
  const auth = useAuth();
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
      setMessage(getSignInErrorMessage(error));
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
            <p className="text-sm font-semibold text-blue-900">Waypoint</p>
            <h1 className="text-xl font-semibold tracking-tight text-slate-950">
              Sign in
            </h1>
          </div>
        </div>

        <p className="mt-5 text-sm leading-6 text-slate-600">
          Use your Microsoft account to continue.
        </p>

        <div className="mt-5">
          {auth.status === "authenticated" ? (
            <Link
              to={returnTo}
              className="flex min-h-11 w-full items-center justify-center rounded-md bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800"
            >
              Continue
            </Link>
          ) : (
            <button
              type="button"
              onClick={handleSignIn}
              disabled={signInDisabled}
              className="flex min-h-11 w-full items-center justify-center gap-2 rounded-md bg-blue-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {auth.isSigningOut
                ? "Finishing sign-out..."
                : isSigningIn || auth.status === "checking"
                ? "Checking sign-in..."
                : "Sign in"}
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
            Microsoft sign-in is not configured for this environment.
          </p>
        ) : null}
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

function getSignInErrorMessage(error: unknown) {
  if (error instanceof Error && error.message.startsWith("Sign-out is still finishing.")) {
    return error.message;
  }
  return "We couldn't sign you in. Please try again.";
}
