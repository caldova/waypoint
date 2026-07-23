import type { MetaFunction } from "react-router";
import type { ComponentType, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  HiChevronDown,
  HiChevronRight,
  HiClock,
  HiCube,
  HiDatabase,
  HiDocumentText,
  HiGlobeAlt,
  HiLightningBolt,
  HiMinus,
  HiPlus,
  HiRefresh,
  HiSearch,
  HiUserGroup,
  HiX,
} from "react-icons/hi";
import { authFetch } from "../../lib/msalAuth";
import { AppHeader } from "../components/AppHeader";
import { useAuth } from "../components/AuthProvider";
import { RequireAuth } from "../components/RequireAuth";

export const meta: MetaFunction = () => [
  { title: "Runs - Waypoint" },
  {
    name: "description",
    content: "Aggregated agent work: per-invoice runs, IQ usage, and the evidence each run found",
  },
];

interface FanoutEvidence {
  claim?: string;
  source_ref?: string;
  classification?: string;
  confidence?: number;
  supports?: string;
}

interface FanoutLane {
  agent?: string;
  plane?: string;
  summary?: string;
  evidence?: FanoutEvidence[];
}

interface RunMetadata {
  invoice_id?: string;
  invoice_number?: string;
  decision?: string;
  confidence?: number;
  confidence_calibrated?: boolean;
  money_at_risk?: number;
  finding_count?: number;
  experts_consulted?: string[];
  fanout?: FanoutLane[];
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

async function tracedFetch(
  name: string,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const { traced } = await import("../../lib/telemetry");
  return traced(name, () => authFetch(input, init, { requireToken: true }));
}

function formatMoney(value: number | undefined): string {
  const amount = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `$${amount.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

// Strip the internal knowledge-base chunk anchor from an evidence source_ref,
// keeping the human-citable document title. Handles both the bracketed
// ("[ref_id:2]") and the unbracketed, separator-prefixed ("; ref_id:0") forms.
function cleanSourceRef(ref: string): string {
  const cleaned = ref.replace(/\s*;?\s*\[?ref_id:\s*\d+\]?/gi, "").trim();
  return cleaned.length > 0 ? cleaned : ref;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

const DECISION_STYLES: Record<string, string> = {
  recover: "bg-orange-50 text-orange-800 ring-orange-100",
  recovery: "bg-orange-50 text-orange-800 ring-orange-100",
  escalate: "bg-red-50 text-red-800 ring-red-100",
  review: "bg-blue-50 text-blue-700 ring-blue-100",
  approve: "bg-emerald-50 text-emerald-800 ring-emerald-100",
  approved: "bg-emerald-50 text-emerald-800 ring-emerald-100",
};

function decisionStyle(decision: string | undefined): string {
  return DECISION_STYLES[(decision ?? "").toLowerCase()] ?? "bg-slate-100 text-slate-700 ring-slate-200";
}

// ---------------------------------------------------------------------------
// IQ planes ("the IQ logos")
// ---------------------------------------------------------------------------

type IqKey = "workiq" | "webiq" | "foundryiq" | "fabriciq" | "other";

interface IqMeta {
  key: IqKey;
  /** Microsoft tool brand (FabricIQ, WorkIQ, …) — kept for compact chips and the run graph. */
  label: string;
  /** New forge agent/persona name surfaced on the Expert Usage panel. */
  agent: string;
  /** Microsoft tool the agent is connected to, shown as a "Connected to …" sub-label. */
  tool: string;
  /** Lane returns placeholder evidence (no live data source bound yet). */
  stub?: boolean;
  icon: ComponentType<{ className?: string }>;
  img?: string;
  ring: string;
  badge: string;
  text: string;
  dot: string;
  hex: string;
}

const IQ_META: Record<IqKey, IqMeta> = {
  fabriciq: {
    key: "fabriciq",
    label: "FabricIQ",
    agent: "Operations Data Expert",
    tool: "Microsoft Fabric",
    icon: HiDatabase,
    img: "/iq/fabric-iq.png",
    ring: "ring-emerald-200",
    badge: "bg-emerald-50 text-emerald-700",
    text: "text-emerald-700",
    dot: "bg-emerald-500",
    hex: "#10b981",
  },
  foundryiq: {
    key: "foundryiq",
    label: "FoundryIQ",
    agent: "Contract Policy Expert",
    tool: "Azure AI Foundry",
    icon: HiLightningBolt,
    img: "/iq/foundry-iq.png",
    ring: "ring-blue-200",
    badge: "bg-blue-50 text-blue-700",
    text: "text-blue-700",
    dot: "bg-blue-500",
    hex: "#2e6cfc",
  },
  webiq: {
    key: "webiq",
    label: "WebIQ",
    agent: "Market Evidence Expert",
    tool: "Web / WebIQ",
    icon: HiGlobeAlt,
    img: "/iq/web-iq.png",
    ring: "ring-indigo-200",
    badge: "bg-indigo-50 text-indigo-700",
    text: "text-indigo-700",
    dot: "bg-indigo-500",
    hex: "#6366f1",
  },
  workiq: {
    key: "workiq",
    label: "WorkIQ",
    agent: "Collaboration Evidence Expert",
    tool: "Microsoft 365",
    icon: HiDocumentText,
    img: "/iq/work-iq.png",
    ring: "ring-violet-200",
    badge: "bg-violet-50 text-violet-700",
    text: "text-violet-700",
    dot: "bg-violet-500",
    hex: "#8b5cf6",
  },
  other: {
    key: "other",
    label: "Expert",
    agent: "Expert",
    tool: "",
    icon: HiDocumentText,
    ring: "ring-slate-200",
    badge: "bg-slate-100 text-slate-600",
    text: "text-slate-600",
    dot: "bg-slate-400",
    hex: "#94a3b8",
  },
};

// Order the canonical IQs deterministically for the sidebar.
const IQ_ORDER: IqKey[] = ["fabriciq", "foundryiq", "webiq", "workiq"];

function iqKeyForLane(lane: FanoutLane): IqKey {
  const raw = `${lane.plane ?? ""} ${lane.agent ?? ""}`.toLowerCase();
  if (raw.includes("fabric") || raw.includes("operations-data")) return "fabriciq";
  if (raw.includes("foundry") || raw.includes("contract-policy")) return "foundryiq";
  if (raw.includes("webiq") || raw.includes("market-evidence") || raw.includes("regulator")) {
    return "webiq";
  }
  if (
    raw.includes("workiq") ||
    raw.includes("collaboration-evidence") ||
    raw.includes("microsoft 365")
  ) {
    return "workiq";
  }
  return "other";
}

function isAnalystLane(lane: FanoutLane): boolean {
  return [lane.agent, lane.plane].some((value) => {
    const identifier = (value ?? "").trim().toLowerCase().replace(/[\s_]+/g, "-");
    return identifier === "invoice-analyst" || identifier === "assurance-analyst";
  });
}

function isPipelineControlLane(lane: FanoutLane): boolean {
  const agent = (lane.agent ?? "").trim().toLowerCase().replace(/[\s_]+/g, "-");
  return agent === "assurance-orchestrator" || agent === "waypoint-recorder";
}

function citedEvidence(lane: FanoutLane): FanoutEvidence[] {
  return Array.isArray(lane.evidence)
    ? lane.evidence.filter(
        (item) => typeof item.source_ref === "string" && item.source_ref.trim().length > 0,
      )
    : [];
}

function isEvidenceLane(lane: FanoutLane): boolean {
  return !isAnalystLane(lane) && !isPipelineControlLane(lane) && citedEvidence(lane).length > 0;
}

function evidenceFanout(metadata: RunMetadata): FanoutLane[] {
  return Array.isArray(metadata.fanout) ? metadata.fanout.filter(isEvidenceLane) : [];
}

function laneClaimCount(lane: FanoutLane): number {
  return citedEvidence(lane).length;
}

function laneAvgConfidence(lane: FanoutLane): number | null {
  const items = citedEvidence(lane).filter((item) => typeof item.confidence === "number");
  if (items.length === 0) {
    return null;
  }
  const sum = items.reduce((acc, item) => acc + (item.confidence ?? 0), 0);
  return sum / items.length;
}

// ---------------------------------------------------------------------------
// Aggregation
// ---------------------------------------------------------------------------

interface InvoiceGroup {
  key: string;
  label: string;
  runs: AgentRun[];
  latestRun: AgentRun;
  runCount: number;
  decision: string;
  moneyAtRisk: number;
  findingCount: number;
  confidence: number | null;
  iqKeys: IqKey[];
  lastRunAt: string;
}

function groupConfidence(latestMeta: RunMetadata, fanout: FanoutLane[]): number | null {
  if (latestMeta.confidence_calibrated !== true) {
    return null;
  }
  if (typeof latestMeta.confidence === "number") {
    return latestMeta.confidence;
  }
  const confidences = fanout
    .map((lane) => laneAvgConfidence(lane))
    .filter((value): value is number => typeof value === "number");
  if (confidences.length === 0) {
    return null;
  }
  return confidences.reduce((acc, value) => acc + value, 0) / confidences.length;
}

function invoiceKeyFor(run: AgentRun): string {
  const meta = run.metadata ?? {};
  return (
    meta.invoice_id ||
    meta.invoice_number ||
    run.case_id ||
    run.name ||
    run.id
  );
}

function invoiceLabelFor(run: AgentRun): string {
  const meta = run.metadata ?? {};
  return meta.invoice_number || meta.invoice_id || run.name || run.id;
}

function buildInvoiceGroups(runs: AgentRun[]): InvoiceGroup[] {
  const map = new Map<string, AgentRun[]>();
  for (const run of runs) {
    const key = invoiceKeyFor(run);
    const list = map.get(key);
    if (list) {
      list.push(run);
    } else {
      map.set(key, [run]);
    }
  }

  const groups: InvoiceGroup[] = [];
  for (const [key, groupRuns] of map.entries()) {
    const sorted = [...groupRuns].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
    const latestRun = sorted[0];
    const latestMeta = latestRun.metadata ?? {};
    const fanout = evidenceFanout(latestMeta);
    const iqKeys = Array.from(new Set(fanout.map(iqKeyForLane)));
    groups.push({
      key,
      label: invoiceLabelFor(latestRun),
      runs: sorted,
      latestRun,
      runCount: sorted.length,
      decision: latestMeta.decision || latestRun.status,
      moneyAtRisk: typeof latestMeta.money_at_risk === "number" ? latestMeta.money_at_risk : 0,
      findingCount:
        typeof latestMeta.finding_count === "number"
          ? latestMeta.finding_count
          : fanout.reduce((acc, lane) => acc + laneClaimCount(lane), 0),
      confidence: groupConfidence(latestMeta, fanout),
      iqKeys,
      lastRunAt: latestRun.created_at,
    });
  }

  groups.sort((a, b) => new Date(b.lastRunAt).getTime() - new Date(a.lastRunAt).getTime());
  return groups;
}

interface IqStat {
  meta: IqMeta;
  runCount: number;
  claimCount: number;
  moneyAtRisk: number;
  avgConfidence: number | null;
}

function buildIqStats(runs: AgentRun[], groups: InvoiceGroup[]): IqStat[] {
  const runCount: Record<IqKey, number> = {
    fabriciq: 0,
    foundryiq: 0,
    webiq: 0,
    workiq: 0,
    other: 0,
  };
  const claimCount: Record<IqKey, number> = { ...runCount };
  const moneyAtRisk: Record<IqKey, number> = { ...runCount };
  const confidenceSum: Record<IqKey, number> = { ...runCount };
  const confidenceCount: Record<IqKey, number> = { ...runCount };

  // How many times each IQ ran + claims it contributed, across every run.
  for (const run of runs) {
    const fanout = evidenceFanout(run.metadata ?? {});
    const seen = new Set<IqKey>();
    for (const lane of fanout) {
      const key = iqKeyForLane(lane);
      claimCount[key] += laneClaimCount(lane);
      const confidence = laneAvgConfidence(lane);
      if (typeof confidence === "number") {
        confidenceSum[key] += confidence;
        confidenceCount[key] += 1;
      }
      if (!seen.has(key)) {
        seen.add(key);
        runCount[key] += 1;
      }
    }
  }

  // Money attribution: each invoice's representative (latest) money counts once
  // per IQ that participated in that latest run — keeps it consistent with the
  // left-panel money total (no double-counting reruns).
  for (const group of groups) {
    for (const key of group.iqKeys) {
      moneyAtRisk[key] += group.moneyAtRisk;
    }
  }

  return IQ_ORDER.map((key) => ({
    meta: IQ_META[key],
    runCount: runCount[key],
    claimCount: claimCount[key],
    moneyAtRisk: moneyAtRisk[key],
    avgConfidence: confidenceCount[key] > 0 ? confidenceSum[key] / confidenceCount[key] : null,
  })).filter((stat) => stat.runCount > 0);
}

// ---------------------------------------------------------------------------
// Filtering / sorting
// ---------------------------------------------------------------------------

type TimeRangeKey = "7d" | "30d" | "90d" | "all";

const TIME_RANGES: { key: TimeRangeKey; label: string; days: number | null }[] = [
  { key: "7d", label: "7d", days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "90d", label: "90d", days: 90 },
  { key: "all", label: "All", days: null },
];

type SortKey = "recent" | "money" | "confidence";

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "recent", label: "Most recent" },
  { key: "money", label: "Money at risk" },
  { key: "confidence", label: "Lowest confidence" },
];

const DAY_MS = 86_400_000;

function withinDays(iso: string, days: number | null, now: number): boolean {
  if (days == null) {
    return true;
  }
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) {
    return true;
  }
  return now - time <= days * DAY_MS;
}

function monthKeyOf(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabelOf(key: string): string {
  const [year, month] = key.split("-").map(Number);
  if (!year || !month) {
    return key;
  }
  return new Date(year, month - 1, 1).toLocaleString(undefined, {
    month: "short",
    year: "numeric",
  });
}

interface TrendPoint {
  day: string;
  value: number;
}

// Bucket the money assured per day (by each invoice's representative run) so the
// totals strip can show a simple at-risk trend line.
function buildMoneyTrend(groups: InvoiceGroup[]): TrendPoint[] {
  const buckets = new Map<string, number>();
  for (const group of groups) {
    const date = new Date(group.lastRunAt);
    if (Number.isNaN(date.getTime())) {
      continue;
    }
    const day = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
      date.getDate(),
    ).padStart(2, "0")}`;
    buckets.set(day, (buckets.get(day) ?? 0) + group.moneyAtRisk);
  }
  return Array.from(buckets.entries())
    .map(([day, value]) => ({ day, value }))
    .sort((a, b) => a.day.localeCompare(b.day));
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Agent() {
  const auth = useAuth();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [lightboxRunId, setLightboxRunId] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("all");
  const [monthFilter, setMonthFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("recent");
  const [cashKey, setCashKey] = useState(0);

  const fetchRuns = useCallback(async () => {
    if (auth.status !== "authenticated") {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await tracedFetch("fetchAgentRuns", "/api/runs");
      if (!response.ok) {
        throw new Error(`Failed to fetch agent runs: ${response.statusText}`);
      }
      const data: AgentRun[] = await response.json();
      data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch agent runs");
    } finally {
      setLoading(false);
    }
  }, [auth.status]);

  useEffect(() => {
    if (auth.status === "authenticated") {
      void fetchRuns();
    }
  }, [auth.status, fetchRuns]);

  const months = useMemo(() => {
    const set = new Set<string>();
    for (const run of runs) {
      const key = monthKeyOf(run.created_at);
      if (key) {
        set.add(key);
      }
    }
    return Array.from(set).sort().reverse();
  }, [runs]);

  // 1) Narrow by time (a chosen month overrides the quick range).
  const timeFilteredRuns = useMemo(() => {
    const now = Date.now();
    const days = TIME_RANGES.find((range) => range.key === timeRange)?.days ?? null;
    return runs.filter((run) => {
      if (monthFilter !== "all") {
        return monthKeyOf(run.created_at) === monthFilter;
      }
      return withinDays(run.created_at, days, now);
    });
  }, [runs, timeRange, monthFilter]);

  const allGroups = useMemo(() => buildInvoiceGroups(timeFilteredRuns), [timeFilteredRuns]);

  // Decision chips reflect whatever decisions exist in the time-filtered data.
  const decisions = useMemo(() => {
    const set = new Set<string>();
    for (const group of allGroups) {
      set.add(group.decision.toLowerCase());
    }
    return Array.from(set).sort();
  }, [allGroups]);

  // 2) Narrow by decision + search, then 3) sort.
  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = allGroups.filter((group) => {
      if (decisionFilter !== "all" && group.decision.toLowerCase() !== decisionFilter) {
        return false;
      }
      if (needle) {
        const haystack = `${group.label} ${group.key} ${group.latestRun.summary ?? ""}`.toLowerCase();
        if (!haystack.includes(needle)) {
          return false;
        }
      }
      return true;
    });
    return [...filtered].sort((a, b) => {
      if (sort === "money") {
        return b.moneyAtRisk - a.moneyAtRisk;
      }
      if (sort === "confidence") {
        return (a.confidence ?? 1) - (b.confidence ?? 1);
      }
      return new Date(b.lastRunAt).getTime() - new Date(a.lastRunAt).getTime();
    });
  }, [allGroups, decisionFilter, query, sort]);

  const visibleRuns = useMemo(() => groups.flatMap((group) => group.runs), [groups]);
  const iqStats = useMemo(() => buildIqStats(visibleRuns, groups), [visibleRuns, groups]);

  const totals = useMemo(() => {
    const moneyAtRisk = groups.reduce((acc, group) => acc + group.moneyAtRisk, 0);
    return { moneyAtRisk, invoices: groups.length, runs: visibleRuns.length };
  }, [groups, visibleRuns.length]);

  const moneyTrend = useMemo(() => buildMoneyTrend(groups), [groups]);

  const filtersActive =
    timeRange !== "all" || monthFilter !== "all" || decisionFilter !== "all" || query.trim() !== "";

  const resetFilters = useCallback(() => {
    setTimeRange("all");
    setMonthFilter("all");
    setDecisionFilter("all");
    setQuery("");
  }, []);

  // Auto-expand the most recent invoice on first load.
  useEffect(() => {
    setExpanded((prev) => {
      if (Object.keys(prev).length > 0 || groups.length === 0) {
        return prev;
      }
      return { [groups[0].key]: true };
    });
  }, [groups]);

  const lightboxRun = useMemo(
    () => runs.find((run) => run.id === lightboxRunId) ?? null,
    [runs, lightboxRunId],
  );

  const toggle = (key: string) => setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <RequireAuth>
      <div className="flex h-screen overflow-hidden bg-slate-50 text-slate-950">
        <div className="flex min-h-0 w-full flex-col">
          <AppHeader />

          <main
            id="main-content"
            className="relative mx-auto grid min-h-0 w-full max-w-[1500px] flex-1 grid-cols-1 gap-2 px-3 py-3 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:px-4"
          >
            <section
              className="flex min-h-0 flex-col rounded-lg border border-slate-200 bg-white p-3 shadow-sm"
              aria-labelledby="agent-heading"
            >
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">
                    Foundry agent runs
                  </p>
                  <h1 id="agent-heading" className="mt-1 text-xl font-semibold tracking-tight">
                    Work done by invoice
                  </h1>
                  <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">
                    Every Assurance Orchestrator run is grouped by the invoice it assured. Each row rolls
                    up how many times the experts ran, the current decision, and money at risk.
                    Open a run to see the IQ-by-IQ evidence trail of what it found.
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void fetchRuns()}
                    className="inline-flex min-h-9 items-center gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    <HiRefresh className="h-4 w-4" aria-hidden="true" />
                    Refresh
                  </button>
                </div>
              </div>

              {error ? (
                <div className="mt-3 rounded-md border border-red-100 bg-red-50/60 p-3 text-sm text-red-800">
                  {error}
                </div>
              ) : null}

              {!loading && runs.length > 0 ? (
                <FilterBar
                  timeRange={timeRange}
                  onTimeRange={(key) => {
                    setTimeRange(key);
                    setMonthFilter("all");
                  }}
                  months={months}
                  monthFilter={monthFilter}
                  onMonthFilter={(key) => {
                    setMonthFilter(key);
                    if (key !== "all") {
                      setTimeRange("all");
                    }
                  }}
                  decisions={decisions}
                  decisionFilter={decisionFilter}
                  onDecisionFilter={setDecisionFilter}
                  query={query}
                  onQuery={setQuery}
                  sort={sort}
                  onSort={setSort}
                />
              ) : null}

              <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
                {loading ? (
                  <p className="px-1 py-6 text-sm text-slate-500">Loading runs…</p>
                ) : runs.length === 0 ? (
                  <EmptyState />
                ) : groups.length === 0 ? (
                  <NoMatches onReset={resetFilters} />
                ) : (
                  <ol className="space-y-3">
                    {groups.map((group) => (
                      <InvoiceCard
                        key={group.key}
                        group={group}
                        expanded={Boolean(expanded[group.key])}
                        onToggle={() => toggle(group.key)}
                        onOpenRun={(runId) => setLightboxRunId(runId)}
                      />
                    ))}
                  </ol>
                )}
              </div>
            </section>

            <aside className="flex min-h-0 flex-col gap-2 overflow-auto">
              <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Expert usage (IQ)
                </p>
                <p className="mt-1 text-xs leading-5 text-slate-400">
                  How often each expert ran across all work, and the evidence each
                  contributed to the decision.
                </p>
                {iqStats.length > 0 ? (
                  <ul className="mt-2.5 space-y-2">
                    {iqStats.map((stat) => (
                      <IqUsageTile key={stat.meta.key} stat={stat} />
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2.5 rounded-md border border-dashed border-slate-200 bg-slate-50/60 p-2.5 text-xs leading-5 text-slate-500">
                    No expert contributed cited evidence in the selected runs.
                  </p>
                )}
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
                  Across all runs
                </p>
                <dl className="mt-2 grid grid-cols-3 gap-2">
                  <Stat label="Invoices" value={String(totals.invoices)} />
                  <Stat label="Runs" value={String(totals.runs)} />
                  <Stat
                    label="At risk"
                    value={formatMoney(totals.moneyAtRisk)}
                    tone="text-emerald-700"
                    onClick={() => setCashKey((key) => key + 1)}
                    hint="Make it rain"
                  />
                </dl>
                {moneyTrend.length > 1 ? (
                  <div className="mt-2.5 rounded-md border border-slate-200 p-2">
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span className="uppercase tracking-wide">Money at risk over time</span>
                      <span>{moneyTrend.length} days</span>
                    </div>
                    <Sparkline points={moneyTrend} className="mt-1.5" />
                  </div>
                ) : null}
              </section>
            </aside>

            {lightboxRun ? (
              <RunLightbox run={lightboxRun} onClose={() => setLightboxRunId(null)} />
            ) : null}
          </main>
        </div>
        {cashKey > 0 ? <DollarRain key={cashKey} /> : null}
      </div>
    </RequireAuth>
  );
}

function Stat({
  label,
  value,
  tone,
  onClick,
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  onClick?: () => void;
  hint?: string;
}) {
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={hint}
        className="group rounded-md border border-slate-200 p-2 text-left transition-colors hover:border-emerald-300 hover:bg-emerald-50/50 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
      >
        <span className="block text-[11px] uppercase tracking-wide text-slate-400">{label}</span>
        <span className={`mt-0.5 block text-sm font-semibold ${tone ?? ""}`}>{value}</span>
      </button>
    );
  }
  return (
    <div className="rounded-md border border-slate-200 p-2">
      <dt className="text-[11px] uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className={`mt-0.5 text-sm font-semibold ${tone ?? ""}`}>{value}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

function FilterBar({
  timeRange,
  onTimeRange,
  months,
  monthFilter,
  onMonthFilter,
  decisions,
  decisionFilter,
  onDecisionFilter,
  query,
  onQuery,
  sort,
  onSort,
}: {
  timeRange: TimeRangeKey;
  onTimeRange: (key: TimeRangeKey) => void;
  months: string[];
  monthFilter: string;
  onMonthFilter: (key: string) => void;
  decisions: string[];
  decisionFilter: string;
  onDecisionFilter: (key: string) => void;
  query: string;
  onQuery: (value: string) => void;
  sort: SortKey;
  onSort: (key: SortKey) => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 pb-3">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
          When
        </span>
        <div className="inline-flex rounded-md border border-slate-200 p-0.5">
          {TIME_RANGES.map((range) => {
            const active = monthFilter === "all" && timeRange === range.key;
            return (
              <button
                key={range.key}
                type="button"
                onClick={() => onTimeRange(range.key)}
                className={`rounded px-2 py-1 text-xs font-semibold transition-colors ${
                  active ? "bg-blue-600 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {range.label}
              </button>
            );
          })}
        </div>
        {months.length > 0 ? (
          <select
            value={monthFilter}
            onChange={(event) => onMonthFilter(event.target.value)}
            className="min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus:border-blue-300 focus:outline-none"
            aria-label="Filter by month"
          >
            <option value="all">Any month</option>
            {months.map((month) => (
              <option key={month} value={month}>
                {monthLabelOf(month)}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {decisions.length > 1 ? (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Decision
          </span>
          <div className="flex flex-wrap items-center gap-1">
            <DecisionChip
              label="All"
              active={decisionFilter === "all"}
              onClick={() => onDecisionFilter("all")}
            />
            {decisions.map((decision) => (
              <DecisionChip
                key={decision}
                label={decision}
                active={decisionFilter === decision}
                onClick={() => onDecisionFilter(decision)}
              />
            ))}
          </div>
        </div>
      ) : null}

      <div className="ml-auto flex items-center gap-2">
        <div className="relative">
          <HiSearch
            className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Search invoice…"
            className="min-h-8 w-44 rounded-md border border-slate-200 bg-white pl-7 pr-2 py-1 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:outline-none"
            aria-label="Search invoices"
          />
        </div>
        <select
          value={sort}
          onChange={(event) => onSort(event.target.value as SortKey)}
          className="min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus:border-blue-300 focus:outline-none"
          aria-label="Sort invoices"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function DecisionChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-[11px] font-semibold capitalize ring-1 transition-colors ${
        active
          ? "bg-slate-900 text-white ring-slate-900"
          : "bg-white text-slate-600 ring-slate-200 hover:bg-slate-50"
      }`}
    >
      {label}
    </button>
  );
}

function Sparkline({ points, className }: { points: TrendPoint[]; className?: string }) {
  const width = 100;
  const height = 28;
  const values = points.map((point) => point.value);
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = points.length > 1 ? width / (points.length - 1) : width;
  const coords = points.map((point, index) => {
    const x = index * step;
    const y = height - ((point.value - min) / span) * (height - 4) - 2;
    return { x, y };
  });
  const line = coords.map((coord) => `${coord.x.toFixed(1)},${coord.y.toFixed(1)}`).join(" ");
  const area = `0,${height} ${line} ${width},${height}`;
  const last = coords[coords.length - 1];
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={`h-8 w-full ${className ?? ""}`}
      role="img"
      aria-label="Money at risk trend"
    >
      <polygon points={area} fill="rgba(16,185,129,0.12)" />
      <polyline
        points={line}
        fill="none"
        stroke="#10b981"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      {last ? <circle cx={last.x} cy={last.y} r={1.8} fill="#10b981" /> : null}
    </svg>
  );
}

function NoMatches({ onReset }: { onReset: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-1 py-12 text-center">
      <p className="text-sm font-medium text-slate-600">No invoices match these filters.</p>
      <button
        type="button"
        onClick={onReset}
        className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
      >
        <HiX className="h-3.5 w-3.5" aria-hidden="true" />
        Clear filters
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// "Make it rain" — falling dollar bills when the At-risk total is clicked
// ---------------------------------------------------------------------------

interface CashBill {
  id: number;
  left: number;
  delay: number;
  duration: number;
  size: number;
  drift: number;
  glyph: string;
}

const CASH_GLYPHS = ["💵", "💵", "💵", "💴", "💶", "💷", "🤑"];

function DollarRain() {
  const [show, setShow] = useState(true);

  const prefersReducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const bills = useMemo<CashBill[]>(() => {
    if (prefersReducedMotion) {
      return [];
    }
    const count = 42;
    return Array.from({ length: count }, (_, index) => ({
      id: index,
      left: Math.random() * 100,
      delay: Math.random() * 0.8,
      duration: 2.4 + Math.random() * 1.8,
      size: 18 + Math.random() * 26,
      drift: (Math.random() - 0.5) * 120,
      glyph: CASH_GLYPHS[Math.floor(Math.random() * CASH_GLYPHS.length)],
    }));
  }, [prefersReducedMotion]);

  useEffect(() => {
    if (bills.length === 0) {
      return;
    }
    const longest = Math.max(...bills.map((bill) => bill.delay + bill.duration));
    const timer = window.setTimeout(() => setShow(false), longest * 1000 + 200);
    return () => window.clearTimeout(timer);
  }, [bills]);

  useEffect(() => {
    if (prefersReducedMotion || typeof Audio === "undefined") {
      return;
    }
    const cheer = new Audio("/cheer.wav");
    cheer.volume = 0.6;
    void cheer.play().catch(() => {
      // Autoplay may be blocked until the user interacts; ignore.
    });
    return () => {
      cheer.pause();
      cheer.currentTime = 0;
    };
  }, [prefersReducedMotion]);

  if (!show || bills.length === 0) {
    return null;
  }

  return (
    <div
      className="pointer-events-none fixed inset-0 z-[100] overflow-hidden"
      aria-hidden="true"
    >
      <style>{`
        @keyframes cash-fall {
          0% { transform: translate3d(0, -12vh, 0) rotate(0deg); opacity: 0; }
          8% { opacity: 1; }
          100% { transform: translate3d(var(--cash-drift), 112vh, 0) rotate(720deg); opacity: 1; }
        }
      `}</style>
      {bills.map((bill) => (
        <span
          key={bill.id}
          className="absolute top-0 select-none will-change-transform"
          style={{
            left: `${bill.left}%`,
            fontSize: `${bill.size}px`,
            ["--cash-drift" as string]: `${bill.drift}px`,
            animation: `cash-fall ${bill.duration}s cubic-bezier(0.45,0.05,0.55,0.95) ${bill.delay}s forwards`,
          }}
        >
          {bill.glyph}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// IQ "logo" tile
// ---------------------------------------------------------------------------

function IqLogo({ meta, size = "h-9 w-9" }: { meta: IqMeta; size?: string }) {
  const Icon = meta.icon;
  return (
    <span
      className={`inline-flex ${size} shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white p-0.5 ring-1 ${meta.ring}`}
      aria-hidden="true"
    >
      {meta.img ? (
        <img src={meta.img} alt="" loading="lazy" className="h-full w-full object-contain" />
      ) : (
        <Icon className={`h-5 w-5 ${meta.text}`} />
      )}
    </span>
  );
}

function IqUsageTile({ stat }: { stat: IqStat }) {
  const { meta } = stat;
  const idle = stat.runCount === 0;
  return (
    <li
      className={`flex items-center gap-3 rounded-md border border-slate-200 p-2.5 ${idle ? "opacity-60" : ""}`}
    >
      <IqLogo meta={meta} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <span className="flex min-w-0 flex-wrap items-start gap-x-1.5 gap-y-1">
            <span className="text-sm font-semibold leading-5 text-slate-800">
              {meta.agent}
            </span>
            {meta.stub ? (
              <span className="shrink-0 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 ring-1 ring-amber-200">
                Stub
              </span>
            ) : null}
          </span>
          <span className={`shrink-0 text-xs font-semibold ${meta.text}`}>
            {idle ? "—" : `Ran ${stat.runCount}×`}
          </span>
        </div>
        {meta.tool ? (
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            Connected to {meta.tool}
          </p>
        ) : null}
        <div className="mt-0.5 text-xs text-slate-500">
          {stat.claimCount} {stat.claimCount === 1 ? "citation" : "citations"} contributed
        </div>
        {!idle && stat.avgConfidence != null ? (
          <div className="mt-1.5 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full ${meta.dot}`}
                style={{ width: `${Math.round(Math.min(Math.max(stat.avgConfidence, 0), 1) * 100)}%` }}
              />
            </div>
            <span className="text-[11px] tabular-nums text-slate-400">
              {Math.round(stat.avgConfidence * 100)}%
            </span>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function IqChip({ iqKey }: { iqKey: IqKey }) {
  const meta = IQ_META[iqKey];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${meta.ring} ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden="true" />
      {meta.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Invoice (aggregated) card
// ---------------------------------------------------------------------------

function InvoiceCard({
  group,
  expanded,
  onToggle,
  onOpenRun,
}: {
  group: InvoiceGroup;
  expanded: boolean;
  onToggle: () => void;
  onOpenRun: (runId: string) => void;
}) {
  return (
    <li className="rounded-md border border-slate-200 bg-white">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-3 px-3 py-2.5 text-left"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-md px-2 py-0.5 text-xs font-semibold uppercase capitalize ring-1 ${decisionStyle(
                group.decision,
              )}`}
            >
              {group.decision}
            </span>
            <h3 className="text-base font-semibold leading-6">{group.label}</h3>
            {group.moneyAtRisk > 0 ? (
              <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-100">
                {formatMoney(group.moneyAtRisk)} at risk
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">
              <HiRefresh className="h-3.5 w-3.5" aria-hidden="true" />
              Ran {group.runCount}×
            </span>
            {group.confidence != null ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
                {Math.round(group.confidence * 100)}% confidence
              </span>
            ) : null}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {group.iqKeys.length > 0 ? (
              group.iqKeys.map((iqKey) => <IqChip key={iqKey} iqKey={iqKey} />)
            ) : (
              <span className="text-xs text-slate-400">No expert evidence recorded.</span>
            )}
          </div>
          <p className="mt-1.5 flex items-center gap-1 text-xs text-slate-400">
            <HiClock className="h-3.5 w-3.5" aria-hidden="true" />
            Last run {formatTimestamp(group.lastRunAt)}
            {group.findingCount > 0 ? (
              <span>
                {" "}
                · {group.findingCount} {group.findingCount === 1 ? "finding" : "findings"}
              </span>
            ) : null}
          </p>
        </div>
        <span className="mt-1 shrink-0 text-slate-400">
          {expanded ? (
            <HiChevronDown className="h-5 w-5" aria-hidden="true" />
          ) : (
            <HiChevronRight className="h-5 w-5" aria-hidden="true" />
          )}
        </span>
      </button>

      {expanded ? (
        <div className="border-t border-slate-100 px-3 py-2.5">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
            Run history
          </p>
          <ol className="space-y-1.5">
            {group.runs.map((run, index) => (
              <RunRow
                key={run.id}
                run={run}
                index={group.runs.length - index}
                latest={index === 0}
                onOpen={() => onOpenRun(run.id)}
              />
            ))}
          </ol>
        </div>
      ) : null}
    </li>
  );
}

function RunRow({
  run,
  index,
  latest,
  onOpen,
}: {
  run: AgentRun;
  index: number;
  latest: boolean;
  onOpen: () => void;
}) {
  const meta = run.metadata ?? {};
  const fanout = evidenceFanout(meta);
  const iqKeys = Array.from(new Set(fanout.map(iqKeyForLane)));
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full items-center gap-3 rounded-md border border-slate-200 bg-white px-2.5 py-2 text-left hover:border-blue-200 hover:bg-blue-50/40"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-600">
          #{index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={`rounded px-1.5 py-0.5 text-[11px] font-semibold capitalize ring-1 ${decisionStyle(
                meta.decision || run.status,
              )}`}
            >
              {meta.decision || run.status}
            </span>
            {latest ? (
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold text-blue-700 ring-1 ring-blue-100">
                Latest
              </span>
            ) : null}
            <span className="truncate text-xs text-slate-400">{formatTimestamp(run.created_at)}</span>
          </div>
          <p className="mt-0.5 line-clamp-1 text-sm text-slate-600">
            {run.summary || "No summary recorded."}
          </p>
          {iqKeys.length > 0 ? (
            <div className="mt-1 flex items-center gap-1">
              {iqKeys.map((iqKey) => (
                <IqLogo key={iqKey} meta={IQ_META[iqKey]} size="h-5 w-5" />
              ))}
            </div>
          ) : null}
        </div>
        <span className="shrink-0 text-xs font-semibold text-blue-700">View run →</span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Run lightbox
// ---------------------------------------------------------------------------

function RunLightbox({ run, onClose }: { run: AgentRun; onClose: () => void }) {
  const meta = run.metadata ?? {};
  const fanout = evidenceFanout(meta);
  const invoiceLabel = meta.invoice_number || meta.invoice_id || run.name;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center bg-slate-950/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Run detail for ${invoiceLabel}`}
      onClick={onClose}
    >
      <section
        className="flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 p-4">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">
              Agent run · what it found
            </p>
            <h2 className="mt-1 flex flex-wrap items-center gap-2 text-xl font-semibold">
              {invoiceLabel}
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-semibold uppercase capitalize ring-1 ${decisionStyle(
                  meta.decision || run.status,
                )}`}
              >
                {meta.decision || run.status}
              </span>
            </h2>
            <p className="mt-1 text-xs text-slate-400">
              {formatTimestamp(run.created_at)} · {run.created_by}
            </p>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-50"
            onClick={onClose}
          >
            <HiX className="h-5 w-5" />
            <span className="sr-only">Close run detail</span>
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat
              label="At risk"
              value={formatMoney(meta.money_at_risk)}
              tone="text-emerald-700"
            />
            <Stat
              label="Confidence"
              value={
                typeof meta.confidence === "number"
                  ? `${Math.round(meta.confidence * 100)}%`
                  : "—"
              }
            />
            <Stat label="Experts" value={String(fanout.length)} />
            <Stat
              label="Findings"
              value={String(
                typeof meta.finding_count === "number"
                  ? meta.finding_count
                  : fanout.reduce((acc, lane) => acc + laneClaimCount(lane), 0),
              )}
            />
          </dl>

          {run.summary ? (
            <p className="rounded-md border border-slate-200 bg-slate-50/60 p-3 text-sm leading-6 text-slate-700">
              {run.summary}
            </p>
          ) : null}

          <FanoutGraph
            fanout={fanout}
            decision={meta.decision || run.status}
            moneyAtRisk={meta.money_at_risk}
            confidence={meta.confidence}
          />

          <div>
            <h3 className="text-sm font-semibold text-slate-800">Per-expert (IQ) evidence</h3>
            {fanout.length > 0 ? (
              <ol className="mt-2 space-y-2.5">
                {fanout.map((lane, index) => (
                  <ExpertLane key={`${lane.agent ?? lane.plane ?? "lane"}-${index}`} lane={lane} />
                ))}
              </ol>
            ) : (
              <p className="mt-2 rounded-md border border-dashed border-slate-300 bg-slate-50/60 p-3 text-sm text-slate-500">
                No per-expert evidence was recorded for this run.
              </p>
            )}
          </div>

          {run.foundry_agent_name ||
          run.foundry_conversation_id ||
          run.app_insights_operation_id ? (
            <div className="rounded-md border border-slate-200 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Telemetry
              </p>
              <dl className="mt-1.5 space-y-1 text-xs text-slate-500">
                {run.foundry_agent_name ? (
                  <TelemetryRow label="Foundry agent" value={run.foundry_agent_name} />
                ) : null}
                {run.foundry_conversation_id ? (
                  <TelemetryRow label="Conversation" value={run.foundry_conversation_id} />
                ) : null}
                {run.app_insights_operation_id ? (
                  <TelemetryRow label="Operation" value={run.app_insights_operation_id} />
                ) : null}
                <TelemetryRow label="Run id" value={run.id} />
              </dl>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function TelemetryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-400">{label}</dt>
      <dd>
        <code className="rounded bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">
          {value}
        </code>
      </dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fan-out graph — invoice intake → Assurance Orchestrator → evidence experts → Waypoint Recorder
// ---------------------------------------------------------------------------

interface ExpertNode {
  key: string;
  meta: IqMeta;
  agentLabel: string;
  planeLabel: string;
  claims: number;
  confidence: number | null;
}

const INTAKE_X = 8;
const ORCHESTRATOR_X = 30;
const EXPERT_X = 58;
const RECORDER_X = 89;
const MID_Y = 50;
const BACKBONE = "#2563eb";

// Logical pipeline stage bounds, scaled and panned as a unit.
const STAGE_W = 1040;
const BASE_STAGE_H = 380;
const EXPERT_ROW_H = 96;
const MIN_SCALE = 0.4;
const MAX_SCALE = 2.5;

const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

type ViewTransform = { scale: number; x: number; y: number };

function usePanZoom(stageHeight: number) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<ViewTransform>({ scale: 1, x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number; ox: number; oy: number } | null>(null);
  const didFit = useRef(false);

  const fitToViewport = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const w = el.clientWidth;
    const h = el.clientHeight;
    if (!w || !h) return;
    const scale = Math.min(1, w / STAGE_W, h / stageHeight);
    setView({
      scale,
      x: (w - STAGE_W * scale) / 2,
      y: (h - stageHeight * scale) / 2,
    });
  }, [stageHeight]);

  // Fit once on mount (and when the viewport first gets a real size).
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const maybeFit = () => {
      if (didFit.current) return;
      if (!el.clientWidth || !el.clientHeight) return;
      fitToViewport();
      didFit.current = true;
    };
    maybeFit();
    const ro = new ResizeObserver(maybeFit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fitToViewport]);

  // Zoom around a point (px, py) expressed in viewport-local pixels.
  const zoomAt = useCallback((factor: number, px: number, py: number) => {
    setView((v) => {
      const nextScale = clampScale(v.scale * factor);
      const k = nextScale / v.scale;
      return {
        scale: nextScale,
        x: px - (px - v.x) * k,
        y: py - (py - v.y) * k,
      };
    });
  }, []);

  const zoomByButton = useCallback(
    (factor: number) => {
      const el = viewportRef.current;
      if (!el) return;
      zoomAt(factor, el.clientWidth / 2, el.clientHeight / 2);
    },
    [zoomAt],
  );

  const resetView = useCallback(() => {
    didFit.current = true;
    fitToViewport();
  }, [fitToViewport]);

  // Non-passive wheel listener so we can preventDefault the page scroll.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
      dragRef.current = { startX: e.clientX, startY: e.clientY, ox: view.x, oy: view.y };
      setIsDragging(true);
    },
    [view.x, view.y],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    setView((v) => ({
      ...v,
      x: d.ox + (e.clientX - d.startX),
      y: d.oy + (e.clientY - d.startY),
    }));
  }, []);

  const endDrag = useCallback((e: React.PointerEvent) => {
    if (dragRef.current) {
      try {
        (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {
        /* pointer may already be released */
      }
    }
    dragRef.current = null;
    setIsDragging(false);
  }, []);

  return {
    viewportRef,
    view,
    isDragging,
    zoomIn: () => zoomByButton(1.2),
    zoomOut: () => zoomByButton(1 / 1.2),
    resetView,
    onPointerDown,
    onPointerMove,
    endDrag,
  };
}

function FanoutGraph({
  fanout,
  decision,
  moneyAtRisk,
  confidence,
}: {
  fanout: FanoutLane[];
  decision: string;
  moneyAtRisk: number | undefined;
  confidence: number | undefined;
}) {
  const experts: ExpertNode[] = useMemo(
    () =>
      fanout.map((lane, index) => {
        const meta = IQ_META[iqKeyForLane(lane)];
        const rawLabel = lane.agent || lane.plane || `Evidence expert ${index + 1}`;
        const humanizedLabel = rawLabel
          .replace(/[-_]+/g, " ")
          .replace(/\b\w/g, (letter) => letter.toUpperCase())
          .replace(/\bIq\b/g, "IQ");
        return {
          key: `${lane.agent ?? lane.plane ?? "lane"}-${index}`,
          meta,
          agentLabel: meta.key === "other" ? humanizedLabel : meta.agent,
          planeLabel:
            meta.key === "other"
              ? (lane.plane || "Evidence source")
                  .replace(/[-_]+/g, " ")
                  .replace(/\b\w/g, (letter) => letter.toUpperCase())
                  .replace(/\bIq\b/g, "IQ")
              : meta.label,
          claims: laneClaimCount(lane),
          confidence: laneAvgConfidence(lane),
        };
      }),
    [fanout],
  );

  const stageHeight = Math.max(BASE_STAGE_H, experts.length * EXPERT_ROW_H + 80);
  const expertY = useMemo(() => {
    if (experts.length === 0) return [];
    if (experts.length === 1) return [MID_Y];
    const edgePadding = 56;
    const usableHeight = stageHeight - edgePadding * 2;
    return experts.map(
      (_, index) => ((edgePadding + (usableHeight * index) / (experts.length - 1)) / stageHeight) * 100,
    );
  }, [experts, stageHeight]);
  const pz = usePanZoom(stageHeight);
  const expertNames = experts.map((expert) => expert.agentLabel).join(", ");

  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">Assurance pipeline</h3>
        <span className="text-xs text-slate-400">
          {experts.length === 0
            ? "No experts contributed cited evidence"
            : `${experts.length} ${experts.length === 1 ? "expert" : "experts"} contributed evidence`}
        </span>
      </div>

      <div className="relative mt-2 overflow-hidden rounded-lg border border-slate-200 bg-slate-50/60">
        {/* Zoom / pan controls */}
        <div className="absolute right-2 top-2 z-20 flex flex-col overflow-hidden rounded-md border border-slate-200 bg-white/95 shadow-sm">
          <button
            type="button"
            onClick={pz.zoomIn}
            aria-label="Zoom in"
            className="flex h-7 w-7 items-center justify-center text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
          >
            <HiPlus className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={pz.zoomOut}
            aria-label="Zoom out"
            className="flex h-7 w-7 items-center justify-center border-t border-slate-200 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
          >
            <HiMinus className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={pz.resetView}
            aria-label="Reset view"
            className="flex h-7 w-7 items-center justify-center border-t border-slate-200 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
          >
            <HiRefresh className="h-3.5 w-3.5" />
          </button>
        </div>
        <span className="pointer-events-none absolute bottom-2 left-3 z-20 text-[10px] text-slate-400">
          scroll to zoom · drag to pan
        </span>

        <div
          ref={pz.viewportRef}
          className="relative h-[420px] touch-none select-none"
          style={{ cursor: pz.isDragging ? "grabbing" : "grab" }}
          onPointerDown={pz.onPointerDown}
          onPointerMove={pz.onPointerMove}
          onPointerUp={pz.endDrag}
          onPointerCancel={pz.endDrag}
          role="img"
          aria-label={`Invoice intake feeds Assurance Orchestrator, which ${
            experts.length > 0
              ? `uses cited evidence from ${expertNames}`
              : "recorded no cited expert evidence"
          }; Waypoint Recorder writes the governed result to Waypoint`}
        >
          <div
            className="absolute left-0 top-0 origin-top-left"
            style={{
              width: STAGE_W,
              height: stageHeight,
              transform: `translate(${pz.view.x}px, ${pz.view.y}px) scale(${pz.view.scale})`,
            }}
          >
            <style>{`
            @keyframes fg-dash { to { stroke-dashoffset: -28; } }
            @keyframes fg-pulse {
              0%,100% { box-shadow: 0 0 0 0 rgba(37,99,235,0); }
              50% { box-shadow: 0 0 0 5px rgba(37,99,235,0.16); }
            }
            @keyframes fg-blink { 0%,100% { opacity: .4; } 50% { opacity: 1; } }
            @media (prefers-reduced-motion: no-preference) {
              .fg-flow { animation: fg-dash 1.1s linear infinite; }
              .fg-flow-in { animation-delay: .55s; }
              .fg-flow-out { animation-delay: 1.1s; }
              .fg-pulse { animation: fg-pulse 1.9s ease-in-out infinite; }
              .fg-blink { animation: fg-blink 1.1s ease-in-out infinite; }
            }
          `}</style>

          <svg
            className="absolute inset-0 h-full w-full"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {/* invoice intake → orchestrator */}
            <path
              d={`M ${INTAKE_X} ${MID_Y} L ${ORCHESTRATOR_X} ${MID_Y}`}
              fill="none"
              stroke={BACKBONE}
              strokeWidth={2}
              strokeOpacity={0.85}
              strokeDasharray="5 7"
              vectorEffect="non-scaling-stroke"
              className="fg-flow"
            />
            {/* orchestrator → evidence experts → recorder */}
            {experts.map((expert, index) => {
              const ey = expertY[index];
              return (
                <g key={expert.key}>
                  <path
                    d={`M ${ORCHESTRATOR_X} ${MID_Y} C 42 ${MID_Y}, 43 ${ey}, ${EXPERT_X} ${ey}`}
                    fill="none"
                    stroke={expert.meta.hex}
                    strokeWidth={2}
                    strokeOpacity={0.9}
                    strokeDasharray="5 7"
                    vectorEffect="non-scaling-stroke"
                    className="fg-flow"
                  />
                  <path
                    d={`M ${EXPERT_X} ${ey} C 73 ${ey}, 76 ${MID_Y}, ${RECORDER_X} ${MID_Y}`}
                    fill="none"
                    stroke={expert.meta.hex}
                    strokeWidth={2}
                    strokeOpacity={0.9}
                    strokeDasharray="5 7"
                    vectorEffect="non-scaling-stroke"
                    className="fg-flow fg-flow-in"
                  />
                </g>
              );
            })}
            {experts.length === 0 ? (
              <path
                d={`M ${ORCHESTRATOR_X} ${MID_Y} L ${RECORDER_X} ${MID_Y}`}
                fill="none"
                stroke={BACKBONE}
                strokeWidth={2}
                strokeOpacity={0.85}
                strokeDasharray="5 7"
                vectorEffect="non-scaling-stroke"
                className="fg-flow fg-flow-out"
              />
            ) : null}
          </svg>

          {/* invoice intake */}
          <GraphNodePositioned x={INTAKE_X} y={MID_Y}>
            <div className="flex w-[134px] flex-col items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-center shadow-sm">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                <HiDocumentText className="h-5 w-5" />
              </span>
              <span className="text-xs font-semibold leading-tight text-slate-800">Invoice intake</span>
              <span className="text-[10px] uppercase tracking-wide text-slate-400">
                Content Understanding
              </span>
              <span className="text-[10px] text-slate-400">prebuilt-invoice</span>
            </div>
          </GraphNodePositioned>

          {/* Assurance Orchestrator coordinator */}
          <GraphNodePositioned x={ORCHESTRATOR_X} y={MID_Y}>
            <div className="fg-pulse flex w-[154px] flex-col items-center gap-1 rounded-lg border border-blue-200 bg-white px-2.5 py-2 text-center shadow-sm ring-1 ring-blue-100">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <HiCube className="h-5 w-5" />
              </span>
              <span className="text-xs font-semibold leading-tight text-slate-800">
                Assurance Orchestrator
              </span>
              <span className="text-[10px] uppercase tracking-wide text-blue-700">coordinator</span>
              <span
                className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase capitalize ring-1 ${decisionStyle(decision)}`}
              >
                {decision}
              </span>
              {typeof moneyAtRisk === "number" && moneyAtRisk > 0 ? (
                <span className="text-[11px] font-semibold text-emerald-700">
                  {formatMoney(moneyAtRisk)} at risk
                </span>
              ) : null}
              {typeof confidence === "number" ? (
                <span className="text-[10px] text-slate-400">
                  {Math.round(confidence * 100)}% confidence
                </span>
              ) : null}
            </div>
          </GraphNodePositioned>

          {/* Evidence experts */}
          {experts.map((expert, index) => (
            <GraphNodePositioned key={expert.key} x={EXPERT_X} y={expertY[index]}>
              <ExpertGraphNode expert={expert} />
            </GraphNodePositioned>
          ))}

          {/* Waypoint Recorder — sole Waypoint writer */}
          <GraphNodePositioned x={RECORDER_X} y={MID_Y}>
            <div className="flex w-[142px] flex-col items-center gap-1 rounded-lg border border-emerald-200 bg-white px-2.5 py-2 text-center shadow-sm ring-1 ring-emerald-100">
              <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                <HiDatabase className="h-5 w-5" />
              </span>
              <span className="text-xs font-semibold leading-tight text-slate-800">
                Waypoint Recorder
              </span>
              <span className="text-[10px] uppercase tracking-wide text-emerald-700">
                sole Waypoint writer
              </span>
              <span className="text-[10px] leading-tight text-slate-400">
                run · case · recommendation
              </span>
            </div>
          </GraphNodePositioned>
          </div>
        </div>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-slate-400">
        This diagram reflects cited evidence recorded for this run. Invoice intake is coordinated by
        Assurance Orchestrator, which uses the experts shown above to gather evidence and fuse a
        decision. Waypoint Recorder is the sole writer of the governed run, case, and recommendation.
        Experts without cited run evidence are not shown.
      </p>
    </div>
  );
}

function GraphNodePositioned({
  x,
  y,
  children,
}: {
  x: number;
  y: number;
  children: ReactNode;
}) {
  return (
    <div
      className="absolute z-10 -translate-x-1/2 -translate-y-1/2"
      style={{ left: `${x}%`, top: `${y}%` }}
    >
      {children}
    </div>
  );
}

function ExpertGraphNode({ expert }: { expert: ExpertNode }) {
  const { meta } = expert;
  return (
    <div
      className={`flex w-[224px] flex-col gap-1.5 rounded-lg border bg-white px-2.5 py-2 shadow-sm ring-1 ${meta.ring}`}
      style={{ borderColor: meta.hex }}
    >
      {/* Agent (forge expert persona) */}
      <div className="flex items-center gap-2">
        <span className="relative inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
          <HiUserGroup className="h-4 w-4" />
          <span
            className="fg-blink absolute -right-1 -top-1 h-2 w-2 rounded-full ring-2 ring-white"
            style={{ backgroundColor: meta.hex }}
          />
        </span>
        <div className="min-w-0">
          <div className="text-xs font-semibold leading-snug text-slate-800">{expert.agentLabel}</div>
          <div className="text-[10px] uppercase tracking-wide text-slate-400">expert</div>
        </div>
      </div>

      {/* Connected tool (IQ plane) */}
      <div
        className="flex items-center gap-1.5 rounded-md border border-slate-100 bg-slate-50/70 px-1.5 py-1"
        title={`Connected to ${meta.tool || expert.planeLabel}`}
      >
        <IqLogo meta={meta} size="h-5 w-5" />
        <div className="min-w-0 leading-tight">
          <div className={`text-[11px] font-semibold ${meta.text}`}>{expert.planeLabel}</div>
          <div className="truncate text-[10px] text-slate-400">
            {expert.claims} {expert.claims === 1 ? "citation" : "citations"}
            {expert.confidence !== null ? ` · ${Math.round(expert.confidence * 100)}%` : ""}
          </div>
        </div>
      </div>
    </div>
  );
}

function ExpertLane({ lane }: { lane: FanoutLane }) {
  const evidence = citedEvidence(lane);
  const meta = IQ_META[iqKeyForLane(lane)];
  return (
    <li className="rounded-md border border-slate-200 bg-white p-2.5">
      <div className="flex items-center gap-2 font-semibold">
        <IqLogo meta={meta} size="h-7 w-7" />
        <span>{meta.key === "other" ? lane.agent || lane.plane || "Expert" : meta.label}</span>
        <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-500">
          {evidence.length} {evidence.length === 1 ? "citation" : "citations"}
        </span>
      </div>
      {lane.summary ? <p className="mt-1.5 text-sm text-slate-600">{lane.summary}</p> : null}
      {evidence.length > 0 ? (
        <ul className="mt-2 space-y-2 border-l border-slate-200 pl-3">
          {evidence.map((item, index) => (
            <li key={index} className="text-sm text-slate-600">
              <span className="block">{item.claim || "(no citation text)"}</span>
              <span className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                {item.source_ref ? (
                  <code className="rounded bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">
                    {cleanSourceRef(item.source_ref)}
                  </code>
                ) : null}
                {item.supports ? <span>· supports {item.supports}</span> : null}
                {item.classification ? <span>· {item.classification}</span> : null}
                {typeof item.confidence === "number" ? (
                  <span>· {Math.round(item.confidence * 100)}%</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50/60 p-6 text-center">
      <h3 className="text-base font-semibold text-slate-700">No agent runs yet</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
        Open an invoice and choose Run assurance, or dispatch the repository operations
        workflow. Completed runs appear here with a grounded decision and per-expert
        evidence trail.
      </p>
    </div>
  );
}
