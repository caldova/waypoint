import type { MetaFunction } from "react-router";
import { Link, useSearchParams } from "react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  HiOutlineRefresh,
  HiOutlineClock,
  HiOutlineChip,
  HiOutlineCurrencyDollar,
  HiOutlineExternalLink,
} from "react-icons/hi";
import { authFetch } from "../../lib/msalAuth";
import {
  appInsightsOperationLink,
  fetchDrilldownConfig,
  type DrilldownConfig,
} from "../../lib/waypointConfig";
import { AppHeader } from "../components/AppHeader";
import { useAuth } from "../components/AuthProvider";
import { RequireAuth } from "../components/RequireAuth";

export const meta: MetaFunction = () => [
  { title: "Activity - Waypoint" },
  {
    name: "description",
    content: "Live view of active and pending agent runs and their progress",
  },
];

// ---------------------------------------------------------------------------
// Types (mirror the Waypoint /api/runs AgentRun schema)
// ---------------------------------------------------------------------------

interface FanoutLane {
  agent?: string;
  plane?: string;
  summary?: string;
  evidence?: unknown[];
}

interface RunMetadata {
  invoice_id?: string;
  invoice_number?: string;
  decision?: string;
  confidence?: number;
  money_at_risk?: number;
  finding_count?: number;
  // Older/synthetic runs stored these as plain counts (numbers); newer runs use
  // arrays. Accept both shapes so historical runs don't crash the page.
  experts_consulted?: string[] | number;
  fanout?: FanoutLane[] | number;
}

interface AgentRun {
  id: string;
  case_id: string | null;
  name: string;
  status: string;
  foundry_agent_name: string | null;
  foundry_conversation_id: string | null;
  app_insights_operation_id: string | null;
  summary: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  metadata: RunMetadata;
}

// ---------------------------------------------------------------------------
// Status buckets & helpers
// ---------------------------------------------------------------------------

type Bucket = "active" | "pending" | "done";

const ACTIVE_STATUSES = new Set(["running", "in_progress", "active", "partial"]);
const PENDING_STATUSES = new Set(["pending", "queued", "waiting", "created"]);

function bucketOf(status: string): Bucket {
  const key = (status ?? "").toLowerCase();
  if (ACTIVE_STATUSES.has(key)) return "active";
  if (PENDING_STATUSES.has(key)) return "pending";
  return "done";
}

const POLL_INTERVAL_MS = 5000;

function formatMoney(value: number | undefined): string {
  const amount = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `$${amount.toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

function statusStyle(status: string): { dot: string; badge: string; label: string } {
  const key = (status ?? "").toLowerCase();
  switch (bucketOf(key)) {
    case "active":
      return {
        dot: "bg-blue-500",
        badge: "border-blue-200 bg-blue-50 text-blue-700",
        label: key || "running",
      };
    case "pending":
      return {
        dot: "bg-amber-500",
        badge: "border-amber-200 bg-amber-50 text-amber-700",
        label: key || "pending",
      };
    default:
      if (key === "failed" || key === "error") {
        return {
          dot: "bg-rose-500",
          badge: "border-rose-200 bg-rose-50 text-rose-700",
          label: key,
        };
      }
      return {
        dot: "bg-emerald-500",
        badge: "border-emerald-200 bg-emerald-50 text-emerald-700",
        label: key || "completed",
      };
  }
}

function relativeTime(iso: string, now: number): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

/** Coerce a metadata field that may be an array, a plain count, or missing. */
function toCount(value: unknown): number {
  if (Array.isArray(value)) return value.length;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return 0;
}

/** Progress = fanout lanes that reported a summary / experts expected. */
function runProgress(run: AgentRun): { done: number; total: number } {
  const meta = run.metadata ?? {};
  const experts = meta.experts_consulted;
  const fanout = meta.fanout;
  const total = Math.max(toCount(experts), toCount(fanout));
  if (total === 0) return { done: 0, total: 0 };
  // When fanout is a real array we can measure completed lanes by their summary;
  // for legacy count-based metadata fall back to the experts_consulted count.
  const done = Array.isArray(fanout)
    ? fanout.filter((lane) => (lane?.summary ?? "").trim().length > 0).length
    : toCount(experts);
  return { done: Math.min(done, total), total };
}

async function tracedFetch(
  name: string,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const { traced } = await import("../../lib/telemetry");
  return traced(name, () => authFetch(input, init, { requireToken: true }));
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Activity() {
  const auth = useAuth();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [searchParams] = useSearchParams();
  const focusInvoice = searchParams.get("invoice");
  const focusedRunId = searchParams.get("run");
  const reused = searchParams.get("reused") === "true";
  const [drilldownConfig, setDrilldownConfig] = useState<DrilldownConfig | null>(null);
  // A ticking clock so elapsed timers on active runs stay live between polls.
  const [nowTick, setNowTick] = useState(() => Date.now());

  const fetchRuns = useCallback(
    async (opts?: { silent?: boolean }) => {
      if (auth.status !== "authenticated") {
        return;
      }
      if (!opts?.silent) {
        setLoading(true);
      }
      try {
        const response = await tracedFetch("fetchActivityRuns", "/api/runs");
        if (!response.ok) {
          throw new Error(`Failed to fetch runs: ${response.statusText}`);
        }
        const data: AgentRun[] = await response.json();
        data.sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        );
        setRuns(data);
        setError(null);
        setLastUpdated(Date.now());
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch runs");
      } finally {
        setLoading(false);
      }
    },
    [auth.status],
  );

  // Initial load.
  useEffect(() => {
    if (auth.status === "authenticated") {
      void fetchRuns();
      void fetchDrilldownConfig().then(setDrilldownConfig);
    }
  }, [auth.status, fetchRuns]);

  // Poll for live updates while the tab is visible.
  useEffect(() => {
    if (auth.status !== "authenticated") {
      return;
    }
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void fetchRuns({ silent: true });
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [auth.status, fetchRuns]);

  // 1s clock so "elapsed" timers advance smoothly.
  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const { active, pending, done } = useMemo(() => {
    const groups: Record<Bucket, AgentRun[]> = { active: [], pending: [], done: [] };
    for (const run of runs) {
      groups[bucketOf(run.status)].push(run);
    }
    return groups;
  }, [runs]);

  const activeMoney = useMemo(
    () =>
      active.reduce((acc, run) => acc + (run.metadata?.money_at_risk ?? 0), 0),
    [active],
  );

  return (
    <RequireAuth>
      <div className="min-h-screen bg-slate-50 text-slate-950">
        <AppHeader />

        <main id="main-content" className="mx-auto max-w-[1500px] px-3 py-4 2xl:px-4">
          {/* Header row */}
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">
                Live agent activity
              </p>
              <h1 className="mt-1 text-2xl font-semibold tracking-tight">
                Active &amp; pending runs
              </h1>
              <p className="mt-1 max-w-2xl text-sm text-slate-600">
                Runs opened by the assurance pipeline, refreshed automatically. Open a
                run to inspect the full expert fan-out in Agent Details.
              </p>
            </div>
            <div className="flex items-center gap-3">
              {lastUpdated ? (
                <span className="text-xs text-slate-500">
                  Updated {relativeTime(new Date(lastUpdated).toISOString(), nowTick)} ago
                </span>
              ) : null}
              <button
                type="button"
                onClick={() => void fetchRuns()}
                className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
              >
                <HiOutlineRefresh className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                Refresh
              </button>
            </div>
          </div>

          {focusInvoice ? (
            <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
              {reused
                ? `Reused the active assurance run for invoice ${focusInvoice}; no duplicate Foundry run was started.`
                : `Assurance was accepted for invoice ${focusInvoice}. This page refreshes while the hosted run completes.`}
            </div>
          ) : null}

          {/* Summary strip */}
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <SummaryStat label="Active" value={active.length} tone="blue" pulse={active.length > 0} />
            <SummaryStat label="Pending" value={pending.length} tone="amber" />
            <SummaryStat
              label="Money at risk (active)"
              value={formatMoney(activeMoney)}
              tone="slate"
            />
          </div>

          {error ? (
            <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              {error}
            </div>
          ) : null}

          {/* Active */}
          <Section title="Active" count={active.length} accent="blue">
            {active.length === 0 ? (
              <EmptyRow
                loading={loading}
                message="No runs are executing right now."
              />
            ) : (
              <div className="grid gap-2">
                {active.map((run) => (
                  <RunCard
                    key={run.id}
                    run={run}
                    now={nowTick}
                    live
                    highlight={run.id === focusedRunId || runMatchesInvoice(run, focusInvoice)}
                    drilldownConfig={drilldownConfig}
                  />
                ))}
              </div>
            )}
          </Section>

          {/* Pending */}
          <Section title="Pending" count={pending.length} accent="amber">
            {pending.length === 0 ? (
              <EmptyRow loading={loading} message="Nothing queued." />
            ) : (
              <div className="grid gap-2">
                {pending.map((run) => (
                  <RunCard
                    key={run.id}
                    run={run}
                    now={nowTick}
                    highlight={run.id === focusedRunId || runMatchesInvoice(run, focusInvoice)}
                    drilldownConfig={drilldownConfig}
                  />
                ))}
              </div>
            )}
          </Section>

          {/* Recently completed (collapsed by default) */}
          {done.length > 0 ? (
            <div className="mt-6">
              <button
                type="button"
                onClick={() => setShowDone((v) => !v)}
                className="text-sm font-semibold text-slate-600 hover:text-slate-900"
              >
                {showDone ? "Hide" : "Show"} recently completed ({done.length})
              </button>
              {showDone ? (
                <div className="mt-2 grid gap-2">
                  {done.slice(0, 25).map((run) => (
                    <RunCard
                      key={run.id}
                      run={run}
                      now={nowTick}
                      drilldownConfig={drilldownConfig}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </main>
      </div>
    </RequireAuth>
  );
}

// ---------------------------------------------------------------------------
// Presentational components
// ---------------------------------------------------------------------------

function SummaryStat({
  label,
  value,
  tone,
  pulse,
}: {
  label: string;
  value: number | string;
  tone: "blue" | "amber" | "slate";
  pulse?: boolean;
}) {
  const toneClass =
    tone === "blue"
      ? "text-blue-700"
      : tone === "amber"
        ? "text-amber-700"
        : "text-slate-900";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-center gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          {label}
        </p>
        {pulse ? (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500" />
          </span>
        ) : null}
      </div>
      <p className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}

function Section({
  title,
  count,
  accent,
  children,
}: {
  title: string;
  count: number;
  accent: "blue" | "amber";
  children: React.ReactNode;
}) {
  const bar = accent === "blue" ? "bg-blue-500" : "bg-amber-500";
  return (
    <section className="mt-6">
      <div className="mb-2 flex items-center gap-2">
        <span className={`h-4 w-1 rounded-full ${bar}`} />
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
          {title}
        </h2>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
          {count}
        </span>
      </div>
      {children}
    </section>
  );
}

function EmptyRow({ loading, message }: { loading: boolean; message: string }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
      {loading ? "Loading…" : message}
    </div>
  );
}

function runMatchesInvoice(run: AgentRun, focusInvoice: string | null): boolean {
  if (!focusInvoice) return false;
  const meta = run.metadata ?? {};
  const invoice = meta.invoice_number ?? meta.invoice_id;
  return typeof invoice === "string" && invoice === focusInvoice;
}

function RunCard({
  run,
  now,
  live,
  highlight,
  drilldownConfig,
}: {
  run: AgentRun;
  now: number;
  live?: boolean;
  highlight?: boolean;
  drilldownConfig: DrilldownConfig | null;
}) {
  const style = statusStyle(run.status);
  const meta = run.metadata ?? {};
  const progress = runProgress(run);
  const invoice = meta.invoice_number ?? meta.invoice_id;
  const startedAgo = relativeTime(run.created_at, now);
  const cardRef = useRef<HTMLDivElement>(null);
  const traceLink = drilldownConfig
    ? appInsightsOperationLink(drilldownConfig, run.app_insights_operation_id)
    : null;

  useEffect(() => {
    if (highlight && cardRef.current) {
      cardRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlight]);

  return (
    <div
      ref={cardRef}
      className={`rounded-lg border bg-white p-3 shadow-sm transition ${
        highlight
          ? "border-indigo-400 ring-2 ring-indigo-300 ring-offset-1"
          : "border-slate-200"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${style.dot}`} />
            <h3 className="truncate text-sm font-semibold text-slate-900">{run.name}</h3>
            <span
              className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold capitalize ${style.badge}`}
            >
              {style.label}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            {run.foundry_agent_name ? (
              <span className="inline-flex items-center gap-1">
                <HiOutlineChip className="h-3.5 w-3.5" />
                {run.foundry_agent_name}
              </span>
            ) : null}
            {invoice ? <span>Invoice {invoice}</span> : null}
            {meta.decision ? (
              <span className="capitalize">Decision: {meta.decision}</span>
            ) : null}
            <span className="inline-flex items-center gap-1">
              <HiOutlineClock className="h-3.5 w-3.5" />
              {live ? `${startedAgo} elapsed` : `started ${startedAgo} ago`}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {typeof meta.money_at_risk === "number" && meta.money_at_risk > 0 ? (
            <span className="inline-flex items-center gap-1 text-sm font-semibold text-slate-700">
              <HiOutlineCurrencyDollar className="h-4 w-4 text-slate-400" />
              {formatMoney(meta.money_at_risk)}
            </span>
          ) : null}
          <Link
            to="/agent"
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
          >
            Details
            <HiOutlineExternalLink className="h-3.5 w-3.5" />
          </Link>
          {traceLink ? (
            <a
              href={traceLink}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-2.5 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
            >
              Open trace
              <HiOutlineExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </div>
      </div>

      {run.summary ? (
        <p className="mt-2 line-clamp-2 text-sm text-slate-600">{run.summary}</p>
      ) : null}

      {/* Progress: determinate when we know the expert fan-out, else indeterminate for live runs. */}
      {progress.total > 0 ? (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
            <span>Experts</span>
            <span>
              {progress.done}/{progress.total}
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-blue-500 transition-all"
              style={{ width: `${(progress.done / progress.total) * 100}%` }}
            />
          </div>
        </div>
      ) : live ? (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-400" />
        </div>
      ) : null}
    </div>
  );
}
