import type { MetaFunction } from "react-router";
import { Link } from "react-router";
import {
  HiChartBar,
  HiChevronRight,
  HiDocumentSearch,
  HiLightningBolt,
  HiShieldCheck,
} from "react-icons/hi";
import { AppHeader } from "../components/AppHeader";
import { RequireAuth } from "../components/RequireAuth";
import { useTranslation } from "react-i18next";
import { pageMeta } from "../i18n/meta";

export const meta: MetaFunction = ({ matches }) => pageMeta(matches, "home");

const destinations = [
  { key: "invoices", icon: HiDocumentSearch, to: "/invoices" },
  { key: "activity", icon: HiLightningBolt, to: "/activity" },
  { key: "agent", icon: HiShieldCheck, to: "/agent" },
  { key: "quality", icon: HiChartBar, to: "/quality" },
] as const;

const principles = ["showWork", "keepControl", "reduceLoad"] as const;

export default function Home() {
  const { t } = useTranslation("home");

  return (
    <RequireAuth>
      <div className="min-h-screen bg-slate-50 text-slate-950">
        <AppHeader />

        <main
          id="main-content"
          className="mx-auto max-w-[1500px] px-3 py-4 2xl:px-4"
        >
          <section
            aria-labelledby="home-heading"
            className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
          >
            <div className="p-5 lg:p-8">
              <h1
                id="home-heading"
                className="max-w-4xl text-2xl font-semibold tracking-tight text-balance sm:text-3xl"
              >
                {t("hero.heading")}
              </h1>
              <p className="mt-3 max-w-[65ch] text-base leading-7 text-slate-600">
                {t("hero.body")}
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <Link
                  to="/invoices"
                  className="inline-flex min-h-10 items-center gap-2 rounded-md bg-blue-700 px-3.5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-800 max-md:min-h-11"
                >
                  {t("hero.reviewInvoices")}
                </Link>
                <Link
                  to="/agent"
                  className="inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-800 shadow-sm hover:bg-slate-50 max-md:min-h-11"
                >
                  {t("hero.viewAgentRuns")}
                </Link>
              </div>
            </div>

            <nav
              aria-label={t("areasLabel")}
              className="border-t border-slate-200"
            >
              <ul className="grid gap-px bg-slate-100 md:grid-cols-2 xl:grid-cols-4">
                {destinations.map((destination) => (
                  <li key={destination.to} className="bg-white">
                    <Link
                      to={destination.to}
                      className="group flex h-full items-start gap-3 p-5 transition-colors hover:bg-slate-50 focus-visible:bg-slate-50"
                    >
                      <destination.icon
                        className="mt-0.5 h-5 w-5 shrink-0 text-blue-600"
                        aria-hidden="true"
                      />
                      <span className="min-w-0">
                        <span className="flex items-center gap-1 text-base font-semibold text-slate-950 group-hover:text-blue-700">
                          {t(`destinations.${destination.key}.title`)}
                          <HiChevronRight
                            className="h-4 w-4 text-slate-500 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-700"
                            aria-hidden="true"
                          />
                        </span>
                        <span className="mt-1 block text-sm leading-6 text-slate-600">
                          {t(`destinations.${destination.key}.description`)}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </section>

          <section
            aria-labelledby="principles-heading"
            className="mt-8 grid gap-6 px-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)] lg:px-2"
          >
            <h2 id="principles-heading" className="text-lg font-semibold">
              {t("principles.heading")}
            </h2>
            <dl className="grid gap-5 md:grid-cols-3">
              {principles.map((principle) => (
                <div key={principle}>
                  <dt className="font-semibold">{t(`principles.${principle}.title`)}</dt>
                  <dd className="mt-1 text-sm leading-6 text-slate-600">
                    {t(`principles.${principle}.detail`)}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        </main>
      </div>
    </RequireAuth>
  );
}
