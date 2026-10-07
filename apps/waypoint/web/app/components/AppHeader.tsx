import { NavLink } from "react-router";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useOutletContext } from "react-router";
import type { ReactNode } from "react";
import { HiChevronDown, HiLogout, HiMenu, HiX } from "react-icons/hi";
import { useTranslation } from "react-i18next";
import { useAuth, type UserProfile } from "./AuthProvider";
import { LanguageSwitcher } from "./LanguageSwitcher";

interface RootOutletContext {
  env: {
    localMode: boolean;
  };
  buildVersion: string;
}

export function AppHeader() {
  const { env, buildVersion } = useOutletContext<RootOutletContext>();
  const auth = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false);
  const [isNavOpen, setIsNavOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const navToggleRef = useRef<HTMLButtonElement>(null);
  const { pathname } = useLocation();
  const user = auth.user;

  useEffect(() => {
    setIsNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!isNavOpen) {
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsNavOpen(false);
        navToggleRef.current?.focus();
      }
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isNavOpen]);

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
        {t("app.skipToContent")}
      </a>
      <header className="relative z-40 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between gap-3 px-3 py-1.5 2xl:px-4">
          <div className="flex items-center gap-3">
            <img
              src="/caldova-logo.png"
              alt={t("app.logoAlt")}
              className="h-8 w-auto"
            />
            <span
              className="h-7 w-px bg-slate-200"
              aria-hidden="true"
            />
            <p className="text-sm font-semibold text-blue-900">{t("app.name")}</p>
          </div>
          <div className="flex items-center gap-1.5">
            <nav
              className="hidden items-center gap-1.5 lg:flex"
              aria-label={t("app.primaryNavigation")}
            >
              {NAV_ITEMS.map((item) => (
                <AppNavLink key={item.to} to={item.to}>
                  {t(item.labelKey)}
                </AppNavLink>
              ))}
            </nav>
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
            <button
              ref={navToggleRef}
              type="button"
              onClick={() => setIsNavOpen((value) => !value)}
              aria-expanded={isNavOpen}
              aria-controls="app-nav-menu"
              className="flex h-11 w-11 items-center justify-center rounded-md text-slate-700 hover:bg-slate-100 lg:hidden"
            >
              {isNavOpen ? (
                <HiX className="h-5 w-5" aria-hidden="true" />
              ) : (
                <HiMenu className="h-5 w-5" aria-hidden="true" />
              )}
              <span className="sr-only">{t("app.menu")}</span>
            </button>
          </div>
        </div>
        <nav
          id="app-nav-menu"
          hidden={!isNavOpen}
          className="border-t border-slate-200 px-3 py-2 lg:hidden"
          aria-label={t("app.primaryNavigation")}
        >
          <ul className="mx-auto grid max-w-[1500px] gap-1 sm:grid-cols-2">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <AppNavLink to={item.to} block>
                  {t(item.labelKey)}
                </AppNavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
    </>
  );
}

const NAV_ITEMS = [
  { to: "/", labelKey: "nav.overview" },
  { to: "/invoices", labelKey: "nav.invoices" },
  { to: "/activity", labelKey: "nav.activity" },
  { to: "/agent", labelKey: "nav.agent" },
  { to: "/quality", labelKey: "nav.quality" },
] as const;

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
  const { t } = useTranslation();
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
        className="flex items-center gap-2 rounded-md px-1.5 py-0.5 text-left hover:bg-slate-50 max-lg:min-h-11"
        aria-haspopup="menu"
        aria-expanded={isOpen}
      >
        <span className="hidden min-w-0 text-left sm:block">
          <span className="block max-w-44 truncate text-xs font-semibold leading-4 text-slate-900">
            {user.name}
          </span>
          <span className="block max-w-44 truncate type-meta">
            {user.email}
          </span>
        </span>
        <span className="flex h-7 w-7 items-center justify-center overflow-hidden rounded-full bg-blue-100 text-xs font-semibold text-blue-800">
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
                <p className="text-xs font-semibold text-emerald-800">{t("userMenu.devMode")}</p>
                <p className="text-xs text-emerald-700">{t("userMenu.devModeDetail")}</p>
              </div>
            ) : null}
          </div>
          <LanguageSwitcher className="border-b border-slate-100 px-2 py-2" />
          <button
            type="button"
            role="menuitem"
            onClick={onSignOut}
            className="mt-1 flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            <HiLogout className="h-4 w-4 text-slate-500" aria-hidden="true" />
            {isLocalMode ? t("userMenu.backToLogin") : t("userMenu.signOut")}
          </button>
          <p className="border-t border-slate-100 pr-2 pt-1.5 text-right type-meta">
            {buildVersion}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function AppNavLink({
  to,
  block = false,
  children,
}: {
  to: string;
  block?: boolean;
  children: ReactNode;
}) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        [
          block
            ? "flex min-h-11 items-center rounded-md px-3 text-base font-medium transition"
            : "rounded-md px-2.5 py-1 text-sm font-medium transition",
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
