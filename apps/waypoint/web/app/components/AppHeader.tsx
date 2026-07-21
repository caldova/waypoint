import { NavLink } from "react-router";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useOutletContext } from "react-router";
import type { ReactNode } from "react";
import { HiChevronDown, HiLogout } from "react-icons/hi";
import { useAuth, type UserProfile } from "./AuthProvider";

interface RootOutletContext {
  env: {
    localMode: boolean;
  };
  buildVersion: string;
}

export function AppHeader() {
  const { env, buildVersion } = useOutletContext<RootOutletContext>();
  const auth = useAuth();
  const navigate = useNavigate();
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const user = auth.user;

  useEffect(() => {
    if (!isUserMenuOpen) {
      return;
    }

    function closeOnOutsideClick(event: MouseEvent) {
      if (!userMenuRef.current?.contains(event.target as Node)) {
        setIsUserMenuOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsUserMenuOpen(false);
      }
    }

    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [isUserMenuOpen]);

  const handleSignOut = async () => {
    await auth.signOut();
    setIsUserMenuOpen(false);
    navigate("/login", { replace: true });
  };

  return (
    <>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:font-semibold focus:text-blue-700 focus:shadow-lg"
      >
        Skip to main content
      </a>
      <header className="relative z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-3 px-3 py-1.5 2xl:px-4">
          <div className="flex items-center gap-3">
            <img
              src="/caldova-logo.png"
              alt="Caldova"
              className="h-8 w-auto"
            />
            <span
              className="h-7 w-px bg-slate-200"
              aria-hidden="true"
            />
            <p className="text-[11px] font-semibold uppercase tracking-[0.32em] text-blue-700">
              Waypoint
            </p>
          </div>
          <nav
            className="flex flex-wrap items-center gap-1.5"
            aria-label="Primary navigation"
          >
            <AppNavLink to="/">Overview</AppNavLink>
            <AppNavLink to="/invoices">Invoices</AppNavLink>
            <AppNavLink to="/activity">Activity</AppNavLink>
            <AppNavLink to="/agent">Agent Details</AppNavLink>
            <AppNavLink to="/quality">Quality</AppNavLink>
            {user ? (
              <UserMenu
                user={user}
                isLocalMode={env.localMode}
                isOpen={isUserMenuOpen}
                buildVersion={buildVersion}
                onToggle={() => setIsUserMenuOpen((value) => !value)}
                onSignOut={handleSignOut}
                ref={userMenuRef}
              />
            ) : null}
          </nav>
        </div>
      </header>
    </>
  );
}

function UserMenu({
  user,
  isLocalMode,
  isOpen,
  buildVersion,
  onToggle,
  onSignOut,
  ref,
}: {
  user: UserProfile;
  isLocalMode: boolean;
  isOpen: boolean;
  buildVersion: string;
  onToggle: () => void;
  onSignOut: () => void;
  ref: React.RefObject<HTMLDivElement | null>;
}) {
  const initials = user.name
    .split(/\s+/)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-slate-50"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        <span className="hidden min-w-0 text-left sm:block">
          <span className="block max-w-44 truncate text-xs font-semibold leading-4 text-slate-900">
            {user.name}
          </span>
          <span className="block max-w-44 truncate text-[11px] leading-3 text-slate-500">
            {user.email}
          </span>
        </span>
        <span className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-blue-100 text-[10px] font-semibold text-blue-700">
          {user.avatarUrl ? (
            <img src={user.avatarUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            initials
          )}
        </span>
        <HiChevronDown className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
      </button>

      {isOpen ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-64 rounded-md border border-slate-200 bg-white p-1 shadow-lg"
        >
          <div className="border-b border-slate-100 px-2 py-2">
            <p className="truncate text-sm font-semibold text-slate-950">{user.name}</p>
            <p className="truncate text-xs text-slate-500">{user.email}</p>
            {isLocalMode ? (
              <div className="mt-2 rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-800">
                  Dev mode
                </p>
                <p className="text-xs text-emerald-700">
                  Authentication is bypassed locally.
                </p>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={onSignOut}
            className="mt-1 flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            <HiLogout className="h-4 w-4 text-slate-500" aria-hidden="true" />
            {isLocalMode ? "Back to login" : "Sign out"}
          </button>
          <p className="border-t border-slate-100 pr-2 pt-1.5 text-right text-[9px] text-slate-400/40">
            {buildVersion}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function AppNavLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        [
          "rounded-md px-2.5 py-1 text-sm font-medium transition",
          isActive
            ? "bg-blue-100 text-blue-900 ring-1 ring-blue-200"
            : "text-slate-600 hover:bg-slate-100 hover:text-slate-950",
        ].join(" ")
      }
    >
      {children}
    </NavLink>
  );
}
