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

export const meta: MetaFunction = () => [
  { title: "Waypoint" },
  {
    name: "description",
    content: "Contract manufacturing supplier oversight workspace",
  },
];

const destinations = [
  {
    title: "Invoices",
    description:
      "Review invoice findings against purchase orders, MSAs, batch records, quality logs, and IP-sensitive process terms, then run assurance on the ones not yet reviewed.",
    icon: HiDocumentSearch,
    to: "/invoices",
  },
  {
    title: "Activity",
    description:
      "Follow assurance runs while they execute and see what is queued next.",
    icon: HiLightningBolt,
    to: "/activity",
  },
  {
    title: "Agent Details",
    description:
      "Every Foundry Assurance Orchestrator run grouped by invoice, with the per-expert evidence behind each decision.",
    icon: HiShieldCheck,
    to: "/agent",
  },
  {
    title: "Quality",
    description:
      "Measure and improve the assurance agent, with approval required before any release.",
    icon: HiChartBar,
    to: "/quality",
  },
];

const principles = [
  {
    title: "Show the work",
    detail: "Expose sources, intermediate steps, and why an action is recommended.",
  },
  {
    title: "Keep control visible",
    detail: "Make approval boundaries explicit before agents publish or mutate data.",
  },
  {
    title: "Reduce review load",
    detail: "Prioritize high-impact exceptions while keeping drill-down paths available.",
  },
];

export default function Home() {
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
                Waypoint helps Caldova investigate supplier invoices,
                protect IP-sensitive manufacturing commitments, and control
                escalation of supplier-caused quality deviations.
              </h1>
              <p className="mt-3 max-w-[65ch] text-base leading-7 text-slate-600">
                Start the question in Teams or Copilot, then use Waypoint to
                inspect invoice evidence, supplier behavior, batch records,
                quality logs, and agent decisions before finance, procurement,
                legal, or quality teams act.
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <Link
                  to="/invoices"
                  className="inline-flex min-h-9 items-center gap-2 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
                >
                  Review invoices
                </Link>
                <Link
                  to="/agent"
                  className="inline-flex min-h-9 items-center gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  View agent runs
                </Link>
              </div>
            </div>

            <nav
              aria-label="Waypoint areas"
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
                          {destination.title}
                          <HiChevronRight
                            className="h-4 w-4 text-slate-500 transition-transform group-hover:translate-x-0.5 group-hover:text-blue-700"
                            aria-hidden="true"
                          />
                        </span>
                        <span className="mt-1 block text-sm leading-6 text-slate-600">
                          {destination.description}
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
              Built for trust under data pressure
            </h2>
            <dl className="grid gap-5 md:grid-cols-3">
              {principles.map((principle) => (
                <div key={principle.title}>
                  <dt className="font-semibold">{principle.title}</dt>
                  <dd className="mt-1 text-sm leading-6 text-slate-600">
                    {principle.detail}
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
