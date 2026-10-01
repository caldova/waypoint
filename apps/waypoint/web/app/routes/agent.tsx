import type { MetaFunction } from "react-router";
import type { ComponentType, ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  HiArrowsExpand,
  HiChatAlt2,
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
  HiPuzzle,
  HiRefresh,
  HiSearch,
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
  confidenceCalibrated: boolean;
  iqKeys: IqKey[];
  lastRunAt: string;
}

function groupConfidence(latestMeta: RunMetadata, fanout: FanoutLane[]): number | null {
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
      confidenceCalibrated: latestMeta.confidence_calibrated === true,
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
              <span
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-600"
                title={
                  group.confidenceCalibrated
                    ? "Calibrated decision confidence."
                    : "Uncalibrated evidence score; not calibrated decision accuracy."
                }
              >
                {Math.round(group.confidence * 100)}%{" "}
                {group.confidenceCalibrated ? "confidence" : "evidence score"}
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
  const analystLanes = useMemo(
    () => (Array.isArray(meta.fanout) ? meta.fanout.filter(isAnalystLane) : []),
    [meta.fanout],
  );
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

          <EvidenceMap
            fanout={fanout}
            analystLanes={analystLanes}
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
// Agent map — each group of agents lives in its own bubble (orchestration,
// Caldova IQ, governed record, analysts). Caldova IQ is a zoomable circle pack:
// it holds a Microsoft IQ bubble (the four IQ planes) and an Integrations bubble
// (third-party connectors). Click a bubble to zoom into it; click outside to
// zoom back out.
// ---------------------------------------------------------------------------

type MapLevel = "compact" | "label" | "detail";

interface MapNode {
  key: string;
  label: string;
  title: string;
  stats: string;
  lines: string[];
  badge?: { text: string; className: string };
  active: boolean;
  /** Placeholder slot: shown softly in its accent colour rather than greyed out. */
  ghost?: boolean;
  hex: string;
  img?: string;
  icon: ComponentType<{ className?: string }>;
  iconClass: string;
  x: number;
  y: number;
}

type BubbleKey =
  | "orchestration"
  | "caldova"
  | "microsoft"
  | "integrations"
  | "record"
  | "analysts";

interface MapBubble {
  key: BubbleKey;
  /** Enclosing bubble in the circle pack; top-level bubbles have none. */
  parent?: BubbleKey;
  title: string;
  cx: number;
  cy: number;
  r: number;
  hex: string;
  background: string;
  border: string;
  shadow: string;
  titlePlacement: "above" | "below" | "none";
  titleTone: "dark" | "light";
  muted?: boolean;
  nodes: MapNode[];
}

type Circle = { cx: number; cy: number; r: number };

const MAP_W = 1700;
const MAP_H = 800;
const MAP_MID_Y = 400;
const ORCHESTRATION_BUBBLE: Circle = { cx: 250, cy: MAP_MID_Y, r: 200 };
const CALDOVA_BUBBLE: Circle = { cx: 850, cy: MAP_MID_Y, r: 300 };
const PACK_PADDING = 16;
const MICROSOFT_R = 188;
const INTEGRATIONS_R = 90;
// Pack the two children tangent to Caldova IQ's rim along one tilted axis:
// Microsoft IQ low-left, Integrations high-right.
const PACK_AXIS = { x: Math.cos((-25 * Math.PI) / 180), y: Math.sin((-25 * Math.PI) / 180) };
const MICROSOFT_BUBBLE: Circle = {
  cx: CALDOVA_BUBBLE.cx - PACK_AXIS.x * (CALDOVA_BUBBLE.r - MICROSOFT_R - PACK_PADDING),
  cy: CALDOVA_BUBBLE.cy - PACK_AXIS.y * (CALDOVA_BUBBLE.r - MICROSOFT_R - PACK_PADDING),
  r: MICROSOFT_R,
};
const INTEGRATIONS_BUBBLE: Circle = {
  cx: CALDOVA_BUBBLE.cx + PACK_AXIS.x * (CALDOVA_BUBBLE.r - INTEGRATIONS_R - PACK_PADDING),
  cy: CALDOVA_BUBBLE.cy + PACK_AXIS.y * (CALDOVA_BUBBLE.r - INTEGRATIONS_R - PACK_PADDING),
  r: INTEGRATIONS_R,
};
const SIDE_CX = 1470;
// Below this on-screen scale, labels (fixed pixel size) would collide.
const MIN_LABEL_SCALE = 0.45;
const MIN_TILE_GROWTH = 0.9;
const MAX_TILE_GROWTH = 1.2;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const FOCUS_ZOOM = 1.9;
// Relative-zoom windows over which Caldova IQ's children, then their tile
// labels, crossfade in while scrolling. Clicking a bubble jumps straight in.
const CHILDREN_FADE: [number, number] = [1.1, 1.45];
const TILES_FADE: [number, number] = [1.5, 1.85];
// Zooming back out past this clears a clicked focus.
const CLEAR_FOCUS_ZOOM = 1.08;
// A zoomed-in bubble fills this share of the viewport's short side, but a
// click never zooms past MAX_BUBBLE_ZOOM × the fitted view.
const BUBBLE_FILL = 0.9;
const MAX_BUBBLE_ZOOM = 2.2;
// Scroll zoom: scale change per pixel of wheel delta, capped per event so a
// fast trackpad flick can't leap several levels at once.
const WHEEL_ZOOM_PER_PX = 0.0018;
const WHEEL_ZOOM_MAX_STEP = 0.12;
const DRAG_THRESHOLD_PX = 4;
const MAP_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
const MAP_ANIM_MS = 700;

function smoothstep([from, to]: [number, number], value: number): number {
  const t = Math.min(1, Math.max(0, (value - from) / (to - from)));
  return t * t * (3 - 2 * t);
}

const CALDOVA_BACKGROUND = [
  "radial-gradient(circle at 30% 20%, rgb(255 255 255 / 0.22) 0%, transparent 32%)",
  "radial-gradient(circle at 24% 30%, rgb(167 139 250 / 0.85) 0%, transparent 48%)",
  "radial-gradient(circle at 80% 76%, rgb(34 211 238 / 0.6) 0%, transparent 46%)",
  "radial-gradient(circle at 72% 18%, rgb(244 114 182 / 0.45) 0%, transparent 40%)",
  "radial-gradient(circle at 50% 50%, #4c1d95 0%, #312e81 62%, #1e1b4b 100%)",
].join(", ");

const MICROSOFT_BACKGROUND = [
  "radial-gradient(circle at 50% 30%, #ffffff 0%, #f5f7ff 55%, #e8ecff 100%) padding-box",
  `conic-gradient(from 210deg, ${IQ_META.fabriciq.hex}, ${IQ_META.foundryiq.hex}, ${IQ_META.webiq.hex}, ${IQ_META.workiq.hex}, ${IQ_META.fabriciq.hex}) border-box`,
].join(", ");

type ViewTransform = { scale: number; x: number; y: number };

function humanizeIdentifier(value: string): string {
  return value
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bIq\b/g, "IQ");
}

// Few sources sit on a single ring (diagonals first so the centre label stays
// clear); larger catalogs spread with a sunflower layout.
function layoutEvidence(count: number, bubble: Circle): { x: number; y: number }[] {
  const { cx, cy, r } = bubble;
  if (count === 0) return [];
  if (count <= 6) {
    const radius = r * 0.66;
    // Four sources sit high and low (not on the diagonals) so their labels
    // clear the centre heading.
    const angles =
      count === 4
        ? [(-2 * Math.PI) / 3, -Math.PI / 3, Math.PI / 3, (2 * Math.PI) / 3]
        : Array.from(
            { length: count },
            (_, index) => -Math.PI / 2 - Math.PI / count + (index * 2 * Math.PI) / count,
          );
    return angles.map((angle) => ({
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    }));
  }
  const inner = r * 0.42;
  const outer = r * 0.8;
  return Array.from({ length: count }, (_, index) => {
    const radius = inner + (outer - inner) * Math.sqrt((index + 0.5) / count);
    const angle = index * GOLDEN_ANGLE - Math.PI / 4;
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });
}

// Small agent bubbles: one tile sits centred, two stack in flow order, more ring.
function layoutAgents(
  count: number,
  bubble: { cx: number; cy: number; r: number },
): { x: number; y: number }[] {
  // Tiles hang their label below the icon, so anchors sit above centre.
  if (count === 1) return [{ x: bubble.cx, y: bubble.cy - 22 }];
  if (count === 2) {
    return [
      { x: bubble.cx, y: bubble.cy - bubble.r * 0.58 },
      { x: bubble.cx, y: bubble.cy + bubble.r * 0.2 },
    ];
  }
  return Array.from({ length: count }, (_, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count;
    return {
      x: bubble.cx + bubble.r * 0.5 * Math.cos(angle),
      y: bubble.cy + bubble.r * 0.5 * Math.sin(angle),
    };
  });
}

type LaneGroup = { meta: IqMeta; lane: FanoutLane; evidence: FanoutEvidence[] };

function groupEvidenceLanes(fanout: FanoutLane[]): Map<string, LaneGroup> {
  const groups = new Map<string, LaneGroup>();
  fanout.forEach((lane, index) => {
    const iqKey = iqKeyForLane(lane);
    const key = iqKey === "other" ? `other:${lane.agent || lane.plane || index}` : iqKey;
    const group = groups.get(key) ?? { meta: IQ_META[iqKey], lane, evidence: [] };
    group.evidence.push(...citedEvidence(lane));
    groups.set(key, group);
  });
  return groups;
}

// Third-party (non-IQ) evidence lanes. Empty today; the Integrations bubble
// shows a placeholder until a connector contributes cited evidence.
function buildIntegrationNodes(fanout: FanoutLane[]): MapNode[] {
  const groups = groupEvidenceLanes(fanout);
  const keys = [...groups.keys()].filter((key) => key.startsWith("other:")).sort();
  const positions = layoutAgents(Math.max(keys.length, 1), INTEGRATIONS_BUBBLE);
  if (keys.length === 0) {
    return [
      {
        key: "integrations-placeholder",
        ghost: true,
        label: "None connected",
        title: "Third-party integrations",
        stats: "No integrations are connected yet",
        lines: [],
        active: false,
        hex: "#0891b2",
        icon: HiPuzzle,
        iconClass: "text-cyan-700",
        ...positions[0],
      },
    ];
  }
  return keys.map((key, index) => ({
    ...evidenceNodeFor(key, groups.get(key), positions[index]),
    hex: "#0891b2",
    icon: HiPuzzle,
    iconClass: "text-cyan-700",
  }));
}

function buildEvidenceNodes(fanout: FanoutLane[]): MapNode[] {
  const groups = groupEvidenceLanes(fanout);
  // Keep every IQ plane on the map so positions stay stable run to run.
  const positions = layoutEvidence(IQ_ORDER.length, MICROSOFT_BUBBLE);
  return IQ_ORDER.map((key, index) => evidenceNodeFor(key, groups.get(key), positions[index]));
}

function evidenceNodeFor(
  key: string,
  group: LaneGroup | undefined,
  position: { x: number; y: number },
): MapNode {
  const meta = group?.meta ?? IQ_META[key as IqKey];
  const lane = group?.lane ?? {};
  const evidence = group?.evidence ?? [];
  const scored = evidence.filter((item) => typeof item.confidence === "number");
  const avg =
    scored.length > 0
      ? scored.reduce((acc, item) => acc + (item.confidence ?? 0), 0) / scored.length
      : null;
  const active = evidence.length > 0;
  return {
    key,
    label:
      meta.key === "other" ? humanizeIdentifier(lane.plane || "Evidence source") : meta.label,
    title:
      meta.key === "other"
        ? humanizeIdentifier(lane.agent || lane.plane || "Integration")
        : meta.agent,
    stats: active
      ? `${evidence.length} ${evidence.length === 1 ? "citation" : "citations"}${
          avg !== null ? ` · ${Math.round(avg * 100)}%` : ""
        }`
      : "Not used in this run",
    lines: [
      ...new Set(evidence.map((item) => cleanSourceRef(item.source_ref ?? "")).filter(Boolean)),
    ],
    active,
    hex: meta.hex,
    img: meta.img,
    icon: meta.icon,
    iconClass: meta.text,
    ...position,
  };
}

function glassBubble(hex: string, tint: string, tintDeep: string) {
  return {
    hex,
    background: `radial-gradient(circle at 38% 26%, #ffffff 0%, ${tint} 58%, ${tintDeep} 100%)`,
    border: `4px solid ${hex}`,
    shadow: `inset 0 0 0 6px rgb(255 255 255 / 0.85), 0 28px 56px -32px ${hex}b3`,
    titleTone: "dark" as const,
  };
}

function buildMapBubbles({
  evidenceFanout,
  analystLanes,
  decision,
  moneyAtRisk,
  confidence,
}: {
  evidenceFanout: FanoutLane[];
  analystLanes: FanoutLane[];
  decision: string;
  moneyAtRisk: number | undefined;
  confidence: number | undefined;
}): MapBubble[] {
  const evidenceNodes = buildEvidenceNodes(evidenceFanout);
  const integrationNodes = buildIntegrationNodes(evidenceFanout);
  const activeIq = evidenceNodes.filter((node) => node.active).length;
  const connectedIntegrations = integrationNodes.filter((node) => node.active).length;
  const activeSources = activeIq + connectedIntegrations;
  const totalSources =
    evidenceNodes.length +
    integrationNodes.filter((node) => node.key !== "integrations-placeholder").length;

  const orchestrationPositions = layoutAgents(2, ORCHESTRATION_BUBBLE);
  const orchestratorLines = [
    typeof moneyAtRisk === "number" && moneyAtRisk > 0 ? `${formatMoney(moneyAtRisk)} at risk` : "",
    typeof confidence === "number" ? `${Math.round(confidence * 100)}% decision confidence` : "",
  ].filter(Boolean);
  const orchestration: MapBubble = {
    key: "orchestration",
    title: "Orchestration",
    ...ORCHESTRATION_BUBBLE,
    ...glassBubble("#4f46e5", "#eef2ff", "#dfe4ff"),
    titlePlacement: "below",
    nodes: [
      {
        key: "invoice-intake",
        label: "Invoice intake",
        title: "Content Understanding",
        stats: "prebuilt-invoice model",
        lines: [],
        active: true,
        hex: "#475569",
        icon: HiDocumentText,
        iconClass: "text-slate-700",
        ...orchestrationPositions[0],
      },
      {
        key: "assurance-orchestrator",
        label: "Assurance Orchestrator",
        title: "Coordinator",
        stats: `Fanned out to ${activeSources} ${activeSources === 1 ? "source" : "sources"}`,
        lines: orchestratorLines,
        badge: { text: decision, className: decisionStyle(decision) },
        active: true,
        hex: "#4f46e5",
        icon: HiCube,
        iconClass: "text-indigo-600",
        ...orchestrationPositions[1],
      },
    ],
  };

  const caldova: MapBubble = {
    key: "caldova",
    title: `Evidence (${activeSources} of ${totalSources} sources)`,
    ...CALDOVA_BUBBLE,
    hex: "#6d28d9",
    background: CALDOVA_BACKGROUND,
    border: "3px solid rgb(255 255 255 / 0.35)",
    shadow:
      "inset 0 0 80px rgb(255 255 255 / 0.10), inset 0 -40px 90px -40px rgb(34 211 238 / 0.35), 0 40px 70px -30px rgb(76 29 149 / 0.6), 0 14px 28px -14px rgb(30 27 75 / 0.4)",
    titlePlacement: "below",
    titleTone: "dark",
    nodes: [],
  };

  const microsoft: MapBubble = {
    key: "microsoft",
    parent: "caldova",
    title: "Microsoft IQ",
    ...MICROSOFT_BUBBLE,
    hex: "#2e6cfc",
    background: MICROSOFT_BACKGROUND,
    border: "5px solid transparent",
    shadow: "0 0 0 6px rgb(255 255 255 / 0.12), 0 24px 60px -24px rgb(15 23 42 / 0.55)",
    titlePlacement: "none",
    titleTone: "dark",
    nodes: evidenceNodes,
  };

  const integrations: MapBubble = {
    key: "integrations",
    parent: "caldova",
    title: `Integrations (${connectedIntegrations})`,
    ...INTEGRATIONS_BUBBLE,
    hex: "#06b6d4",
    background:
      connectedIntegrations > 0
        ? "radial-gradient(circle at 40% 28%, #ffffff 0%, #ecfeff 55%, #cffafe 100%)"
        : "radial-gradient(circle at 40% 28%, rgb(255 255 255 / 0.95) 0%, rgb(236 254 255 / 0.85) 60%, rgb(207 250 254 / 0.75) 100%)",
    border:
      connectedIntegrations > 0 ? "4px solid #22d3ee" : "3px dashed rgb(165 243 252 / 0.95)",
    shadow: "0 0 0 6px rgb(255 255 255 / 0.10), 0 18px 40px -20px rgb(8 145 178 / 0.7)",
    titlePlacement: "above",
    titleTone: "light",
    muted: connectedIntegrations === 0,
    nodes: integrationNodes,
  };

  const hasAnalysts = analystLanes.length > 0;
  const recordBubbleShape: Circle = hasAnalysts
    ? { cx: SIDE_CX, cy: 260, r: 140 }
    : { cx: SIDE_CX, cy: MAP_MID_Y, r: 150 };
  const record: MapBubble = {
    key: "record",
    title: "Governed record",
    ...recordBubbleShape,
    ...glassBubble("#059669", "#ecfdf5", "#d1fae5"),
    // Keep the title clear of the connector down to the analysts bubble.
    titlePlacement: hasAnalysts ? "above" : "below",
    nodes: [
      {
        key: "waypoint-recorder",
        label: "Waypoint Recorder",
        title: "Sole Waypoint writer",
        stats: "Writes run · case · recommendation",
        lines: [],
        active: true,
        hex: "#059669",
        icon: HiDatabase,
        iconClass: "text-emerald-600",
        ...layoutAgents(1, recordBubbleShape)[0],
      },
    ],
  };

  const bubbles = [orchestration, caldova, microsoft, integrations, record];
  if (hasAnalysts) {
    const analystShape: Circle = { cx: SIDE_CX, cy: 600, r: 130 };
    const analystPositions = layoutAgents(analystLanes.length, analystShape);
    bubbles.push({
      key: "analysts",
      title: `Analysts (${analystLanes.length})`,
      ...analystShape,
      ...glassBubble("#7c3aed", "#f5f3ff", "#ede9fe"),
      titlePlacement: "below",
      nodes: analystLanes.map((lane, index) => ({
        key: `analyst-${lane.agent || lane.plane || index}`,
        label: humanizeIdentifier(lane.agent || lane.plane || "Analyst"),
        title: "Read-only analyst",
        stats: "Answers questions over Waypoint",
        lines: lane.summary ? [lane.summary] : [],
        active: true,
        hex: "#7c3aed",
        icon: HiChatAlt2,
        iconClass: "text-violet-600",
        ...analystPositions[index],
      })),
    });
  }
  return bubbles;
}

// Point on a bubble's edge facing (tx, ty).
function edgePoint(bubble: MapBubble, tx: number, ty: number) {
  const dx = tx - bubble.cx;
  const dy = ty - bubble.cy;
  const length = Math.hypot(dx, dy) || 1;
  return { x: bubble.cx + (dx / length) * bubble.r, y: bubble.cy + (dy / length) * bubble.r };
}

function connectorPath(from: MapBubble, to: MapBubble): string {
  const a = edgePoint(from, to.cx, to.cy);
  const b = edgePoint(to, from.cx, from.cy);
  const bend = (b.x - a.x) * 0.45;
  if (Math.abs(bend) < 1) {
    return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
  }
  return `M ${a.x} ${a.y} C ${a.x + bend} ${a.y}, ${b.x - bend} ${b.y}, ${b.x} ${b.y}`;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true
  );
}

function useMapView() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<ViewTransform>({ scale: 1, x: 0, y: 0 });
  const [fitScale, setFitScale] = useState(1);
  const fitScaleRef = useRef(1);
  const [isDragging, setIsDragging] = useState(false);
  const [isAnimating, setIsAnimating] = useState(false);
  const dragRef = useRef<{
    startX: number;
    startY: number;
    ox: number;
    oy: number;
    pointerId: number;
    active: boolean;
  } | null>(null);
  const didFit = useRef(false);
  // Set when a pointer gesture turned into a pan, so the trailing click is ignored.
  const draggedRef = useRef(false);
  const animTimer = useRef<number | undefined>(undefined);

  const startAnimation = useCallback(() => {
    if (prefersReducedMotion()) return;
    setIsAnimating(true);
    window.clearTimeout(animTimer.current);
    animTimer.current = window.setTimeout(() => setIsAnimating(false), MAP_ANIM_MS);
  }, []);

  useEffect(() => () => window.clearTimeout(animTimer.current), []);

  const computeFit = useCallback((): ViewTransform | null => {
    const el = viewportRef.current;
    if (!el || !el.clientWidth || !el.clientHeight) return null;
    const w = el.clientWidth;
    const h = el.clientHeight;
    const scale = Math.min(w / MAP_W, h / MAP_H) * 0.96;
    return { scale, x: (w - MAP_W * scale) / 2, y: (h - MAP_H * scale) / 2 };
  }, []);

  const applyFit = useCallback(
    (animated: boolean) => {
      const fit = computeFit();
      if (!fit) return;
      fitScaleRef.current = fit.scale;
      setFitScale(fit.scale);
      if (animated) startAnimation();
      setView(fit);
    },
    [computeFit, startAnimation],
  );

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onResize = () => {
      if (!didFit.current) {
        if (computeFit()) {
          applyFit(false);
          didFit.current = true;
        }
        return;
      }
      const fit = computeFit();
      if (fit) {
        fitScaleRef.current = fit.scale;
        setFitScale(fit.scale);
      }
    };
    onResize();
    const ro = new ResizeObserver(onResize);
    ro.observe(el);
    return () => ro.disconnect();
  }, [applyFit, computeFit]);

  const clampZoom = useCallback((scale: number) => {
    const fit = fitScaleRef.current;
    return Math.min(fit * MAX_ZOOM, Math.max(fit * MIN_ZOOM, scale));
  }, []);

  const zoomAt = useCallback(
    (factor: number, px: number, py: number) => {
      setView((v) => {
        const nextScale = clampZoom(v.scale * factor);
        const k = nextScale / v.scale;
        return { scale: nextScale, x: px - (px - v.x) * k, y: py - (py - v.y) * k };
      });
    },
    [clampZoom],
  );

  const zoomByButton = useCallback(
    (factor: number) => {
      const el = viewportRef.current;
      if (!el) return;
      startAnimation();
      zoomAt(factor, el.clientWidth / 2, el.clientHeight / 2);
    },
    [startAnimation, zoomAt],
  );

  // Tiles hang their detail card below the icon, so centre a little above it.
  const focusOn = useCallback(
    (x: number, y: number, liftPx = 0) => {
      const el = viewportRef.current;
      if (!el) return;
      startAnimation();
      setView((v) => {
        const scale = clampZoom(Math.max(v.scale, fitScaleRef.current * FOCUS_ZOOM));
        return {
          scale,
          x: el.clientWidth / 2 - x * scale,
          y: el.clientHeight / 2 - y * scale - liftPx,
        };
      });
    },
    [clampZoom, startAnimation],
  );

  // d3 "zoomable pack" style: fit a whole bubble in view with breathing room.
  const zoomToCircle = useCallback(
    ({ cx, cy, r }: Circle) => {
      const el = viewportRef.current;
      if (!el) return;
      const scale = clampZoom(
        Math.min(
          fitScaleRef.current * MAX_BUBBLE_ZOOM,
          (Math.min(el.clientWidth, el.clientHeight) * BUBBLE_FILL) / (2 * r),
        ),
      );
      startAnimation();
      setView({ scale, x: el.clientWidth / 2 - cx * scale, y: el.clientHeight / 2 - cy * scale });
    },
    [clampZoom, startAnimation],
  );

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      // Line/page deltas (mouse wheels, some browsers) are normalised to pixels.
      const px = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? el.clientHeight : 1);
      const step = Math.max(
        -WHEEL_ZOOM_MAX_STEP,
        Math.min(WHEEL_ZOOM_MAX_STEP, -px * WHEEL_ZOOM_PER_PX),
      );
      zoomAt(Math.exp(step), e.clientX - rect.left, e.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  // Drag only starts past a small threshold so clicks still reach the tiles.
  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      draggedRef.current = false;
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        ox: view.x,
        oy: view.y,
        pointerId: e.pointerId,
        active: false,
      };
    },
    [view.x, view.y],
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (!d.active) {
      if (Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      d.active = true;
      draggedRef.current = true;
      (e.currentTarget as HTMLElement).setPointerCapture(d.pointerId);
      setIsDragging(true);
    }
    setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }));
  }, []);

  const endDrag = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (d?.active) {
      try {
        (e.currentTarget as HTMLElement).releasePointerCapture(d.pointerId);
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
    fitScale,
    isDragging,
    isAnimating,
    zoomIn: () => zoomByButton(1.25),
    zoomOut: () => zoomByButton(1 / 1.25),
    resetView: () => applyFit(true),
    focusOn,
    zoomToCircle,
    wasDragged: () => draggedRef.current,
    onPointerDown,
    onPointerMove,
    endDrag,
  };
}

const BUBBLE_NAMES: Record<BubbleKey, string> = {
  orchestration: "Orchestration",
  caldova: "Caldova IQ",
  microsoft: "Microsoft IQ",
  integrations: "Integrations",
  record: "Governed record",
  analysts: "Analysts",
};

const PACKED_KEYS: BubbleKey[] = ["caldova", "microsoft", "integrations"];

function EvidenceMap({
  fanout,
  analystLanes,
  decision,
  moneyAtRisk,
  confidence,
}: {
  fanout: FanoutLane[];
  analystLanes: FanoutLane[];
  decision: string;
  moneyAtRisk: number | undefined;
  confidence: number | undefined;
}) {
  const bubbles = useMemo(
    () =>
      buildMapBubbles({ evidenceFanout: fanout, analystLanes, decision, moneyAtRisk, confidence }),
    [fanout, analystLanes, decision, moneyAtRisk, confidence],
  );
  const bubbleByKey = new Map(bubbles.map((bubble) => [bubble.key, bubble]));
  const caldovaBubble = bubbleByKey.get("caldova");
  const microsoftBubble = bubbleByKey.get("microsoft");
  const iqNodes = microsoftBubble?.nodes ?? [];
  const sourceNodes = [
    ...iqNodes,
    ...(bubbleByKey.get("integrations")?.nodes ?? []).filter(
      (node) => node.key !== "integrations-placeholder",
    ),
  ];
  const activeSources = sourceNodes.filter((node) => node.active).length;
  const activeIq = iqNodes.filter((node) => node.active).length;
  const iqCitations = evidenceFanoutCitations(
    fanout.filter((lane) => iqKeyForLane(lane) !== "other"),
  );
  const allCitations = evidenceFanoutCitations(fanout);
  const agentCount = bubbles
    .filter((bubble) => !PACKED_KEYS.includes(bubble.key))
    .reduce((acc, bubble) => acc + bubble.nodes.length, 0);

  const connectors: { from: BubbleKey; to: BubbleKey; label?: string }[] = [
    { from: "orchestration", to: "caldova" },
    { from: "caldova", to: "record" },
  ];
  if (bubbleByKey.has("analysts")) {
    connectors.push({ from: "record", to: "analysts", label: "reads" });
  }

  const map = useMapView();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<BubbleKey | null>(null);
  const relativeZoom = map.view.scale / map.fitScale;

  useEffect(() => {
    if (focusKey && relativeZoom < CLEAR_FOCUS_ZOOM) {
      setFocusKey(null);
      setSelectedKey(null);
    }
  }, [focusKey, relativeZoom]);

  // How far into Caldova IQ a click has taken us: 0 = one bubble, 1 = its
  // children, 2 = their tiles. Scrolling crossfades the same levels gradually.
  const focusDepth =
    focusKey === "microsoft" || focusKey === "integrations" ? 2 : focusKey === "caldova" ? 1 : 0;
  const childReveal = focusDepth >= 1 ? 1 : smoothstep(CHILDREN_FADE, relativeZoom);
  const tileReveal = focusDepth >= 2 ? 1 : smoothstep(TILES_FADE, relativeZoom);
  const childrenInteractive = childReveal > 0.5;

  const outerLevel: MapLevel =
    relativeZoom < 0.8 || map.view.scale < MIN_LABEL_SCALE ? "compact" : "label";
  const innerLevel: MapLevel = tileReveal > 0.5 ? "label" : "compact";
  // Tiles start small at the fitted view and grow (sub-linearly) as you zoom in.
  const tileGrowth = Math.min(
    MAX_TILE_GROWTH,
    Math.max(MIN_TILE_GROWTH, Math.sqrt(relativeZoom)),
  );
  const counterScale = tileGrowth / map.view.scale;
  const transition = map.isAnimating ? `transform ${MAP_ANIM_MS}ms ${MAP_EASE}` : undefined;
  const fade = `opacity 450ms ${MAP_EASE}, transform 450ms ${MAP_EASE}`;
  const dotSpacing = 18 * map.view.scale;

  const resetView = () => {
    setSelectedKey(null);
    setFocusKey(null);
    map.resetView();
  };

  const zoomInto = (bubble: MapBubble) => {
    setSelectedKey(null);
    setFocusKey(bubble.key);
    map.zoomToCircle(bubble);
  };

  const zoomOut = () => {
    const current = focusKey ? bubbleByKey.get(focusKey) : undefined;
    const parent = current?.parent ? bubbleByKey.get(current.parent) : undefined;
    if (parent) zoomInto(parent);
    else resetView();
  };

  const trail: BubbleKey[] = [];
  for (let key: BubbleKey | undefined = focusKey ?? undefined; key; ) {
    trail.unshift(key);
    key = bubbleByKey.get(key)?.parent;
  }

  let tileIndex = 0;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-sm font-semibold text-slate-800">Agent map</h3>
        <p className="text-xs text-slate-500">
          {agentCount} {agentCount === 1 ? "agent" : "agents"} · {activeSources} of{" "}
          {sourceNodes.length} evidence sources used
        </p>
      </div>

      <div className="relative mt-2 overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
        <nav
          aria-label="Map zoom level"
          className="absolute left-2 top-2 z-20 flex items-center gap-0.5 rounded-md border border-slate-200 bg-white/90 px-1 py-0.5 text-xs shadow-[0_1px_2px_rgba(15,23,42,0.06),0_4px_12px_-6px_rgba(15,23,42,0.18)] backdrop-blur"
        >
          <button
            type="button"
            onClick={resetView}
            className={`rounded px-1.5 py-1 font-medium transition hover:bg-slate-100 ${
              trail.length === 0 ? "text-slate-900" : "text-slate-500"
            }`}
          >
            All agents
          </button>
          {trail.map((key, index) => {
            const bubble = bubbleByKey.get(key);
            const last = index === trail.length - 1;
            return (
              <span key={key} className="flex items-center gap-0.5">
                <HiChevronRight className="h-3 w-3 text-slate-400" aria-hidden="true" />
                <button
                  type="button"
                  onClick={() => bubble && zoomInto(bubble)}
                  aria-current={last ? "location" : undefined}
                  className={`rounded px-1.5 py-1 font-medium transition hover:bg-slate-100 ${
                    last ? "text-violet-700" : "text-slate-500"
                  }`}
                >
                  {BUBBLE_NAMES[key]}
                </button>
              </span>
            );
          })}
        </nav>
        <div className="absolute right-2 top-2 z-20 flex flex-col overflow-hidden rounded-md border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.06),0_4px_12px_-6px_rgba(15,23,42,0.18)]">
          <MapControl label="Zoom in" onClick={map.zoomIn}>
            <HiPlus className="h-4 w-4" />
          </MapControl>
          <MapControl label="Zoom out" onClick={map.zoomOut} bordered>
            <HiMinus className="h-4 w-4" />
          </MapControl>
          <MapControl label="Fit map to view" onClick={resetView} bordered>
            <HiArrowsExpand className="h-3.5 w-3.5" />
          </MapControl>
        </div>
        <span className="pointer-events-none absolute bottom-2 left-3 z-20 text-[11px] text-slate-500">
          Click a bubble to zoom in · click empty space to zoom out · scroll to zoom · drag to pan
        </span>

        <div
          ref={map.viewportRef}
          className="relative h-[500px] touch-none select-none"
          style={{
            cursor: map.isDragging ? "grabbing" : "grab",
            backgroundImage: [
              "radial-gradient(circle, rgb(203 213 225 / 0.75) 1px, transparent 1.4px)",
              "radial-gradient(ellipse 60% 70% at 50% 50%, rgb(237 233 254 / 0.8), transparent 70%)",
              "linear-gradient(180deg, #f8fafc, #f1f5f9)",
            ].join(", "),
            backgroundSize: `${dotSpacing}px ${dotSpacing}px, 100% 100%, 100% 100%`,
            backgroundPosition: `${map.view.x}px ${map.view.y}px, 0 0, 0 0`,
          }}
          onPointerDown={map.onPointerDown}
          onPointerMove={map.onPointerMove}
          onPointerUp={map.endDrag}
          onPointerCancel={map.endDrag}
          onClick={() => {
            if (!map.wasDragged()) zoomOut();
          }}
          role="group"
          aria-label={`Agent map: ${bubbles
            .filter((bubble) => bubble.nodes.length > 0)
            .map((bubble) => `${BUBBLE_NAMES[bubble.key]} with ${bubble.nodes.map((node) => node.label).join(", ")}`)
            .join("; ")}`}
        >
          <style>{`
            @keyframes em-pop {
              from { opacity: 0; transform: scale(.6); filter: blur(4px); }
              to { opacity: 1; transform: scale(1); filter: blur(0); }
            }
            @keyframes em-dash { to { stroke-dashoffset: -26; } }
            .em-bubble { transition: filter 200ms ease-out, opacity 450ms ${MAP_EASE}, transform 450ms ${MAP_EASE}; }
            .em-bubble:hover { filter: brightness(1.04) saturate(1.08); }
            .em-bubble:focus-visible { outline: 4px solid #7c3aed; outline-offset: 6px; }
            @media (prefers-reduced-motion: no-preference) {
              .em-pop { animation: em-pop 520ms ${MAP_EASE} both; }
              .em-flow { animation: em-dash 1.2s linear infinite; }
            }
          `}</style>
          <div
            className="absolute left-0 top-0 origin-top-left"
            style={{
              width: MAP_W,
              height: MAP_H,
              transform: `translate(${map.view.x}px, ${map.view.y}px) scale(${map.view.scale})`,
              transition,
            }}
          >
            <svg
              className="absolute inset-0 overflow-visible"
              width={MAP_W}
              height={MAP_H}
              viewBox={`0 0 ${MAP_W} ${MAP_H}`}
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="em-arrow"
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
                </marker>
              </defs>
              {connectors.map(({ from, to, label }) => {
                const a = bubbleByKey.get(from);
                const b = bubbleByKey.get(to);
                if (!a || !b) return null;
                const mid = {
                  x: (edgePoint(a, b.cx, b.cy).x + edgePoint(b, a.cx, a.cy).x) / 2,
                  y: (edgePoint(a, b.cx, b.cy).y + edgePoint(b, a.cx, a.cy).y) / 2,
                };
                return (
                  <g key={`${from}-${to}`}>
                    <path
                      d={connectorPath(a, b)}
                      fill="none"
                      stroke="#64748b"
                      strokeWidth={3}
                      strokeDasharray="8 5"
                      strokeLinecap="round"
                      markerEnd="url(#em-arrow)"
                      className="em-flow"
                    />
                    {label ? (
                      <text
                        x={mid.x + 12}
                        y={mid.y + 6}
                        className="fill-slate-500 text-[18px] font-medium"
                      >
                        {label}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </svg>

            {bubbles.map((bubble) => {
              const isChild = Boolean(bubble.parent);
              const visible = !isChild || childrenInteractive;
              const opacity = isChild ? childReveal : 1;
              const circle = {
                left: bubble.cx - bubble.r,
                top: bubble.cy - bubble.r,
                width: bubble.r * 2,
                height: bubble.r * 2,
              };
              return (
                <div key={bubble.key}>
                  <button
                    type="button"
                    tabIndex={visible ? 0 : -1}
                    aria-hidden={visible ? undefined : true}
                    aria-label={`Zoom into ${BUBBLE_NAMES[bubble.key]}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      if (!map.wasDragged()) zoomInto(bubble);
                    }}
                    className="em-bubble absolute cursor-zoom-in rounded-full"
                    style={{
                      ...circle,
                      background: bubble.background,
                      border: bubble.border,
                      boxShadow: bubble.shadow,
                      opacity,
                      // Children settle into place as they fade in.
                      transform: isChild ? `scale(${0.9 + 0.1 * childReveal})` : undefined,
                      pointerEvents: visible ? "auto" : "none",
                    }}
                  />
                  {bubble.titlePlacement !== "none" ? (
                    <div
                      className={`pointer-events-none absolute -translate-x-1/2 whitespace-nowrap text-[26px] font-semibold leading-none tracking-tight ${
                        bubble.titleTone === "light"
                          ? "text-white [text-shadow:0_1px_12px_rgb(30_27_75/0.6)]"
                          : "text-slate-800"
                      } ${bubble.titlePlacement === "above" ? "-translate-y-full" : ""}`}
                      style={{
                        left: bubble.cx,
                        top:
                          bubble.titlePlacement === "above"
                            ? bubble.cy - bubble.r - (isChild ? 12 : 18)
                            : bubble.cy + bubble.r + 18,
                        opacity,
                        transition: fade,
                      }}
                    >
                      {bubble.title}
                    </div>
                  ) : null}
                </div>
              );
            })}

            {caldovaBubble ? (
              <>
                <div
                  className="pointer-events-none absolute flex w-[420px] flex-col items-center text-center text-white"
                  style={{
                    left: caldovaBubble.cx,
                    top: caldovaBubble.cy,
                    opacity: 1 - childReveal,
                    transform: `translate(-50%, -50%) scale(${1 + 0.06 * childReveal})`,
                    transition: fade,
                  }}
                  aria-hidden={childrenInteractive ? true : undefined}
                >
                  <span className="text-[34px] font-semibold leading-tight tracking-tight">
                    Caldova IQ
                  </span>
                  <span className="mt-1 text-[104px] font-semibold leading-none tracking-[-0.035em] tabular-nums [text-shadow:0_4px_18px_rgb(30_27_75/0.35)]">
                    {allCitations}
                  </span>
                  <span className="mt-2 text-[21px] text-violet-100">
                    {allCitations === 1 ? "citation" : "citations"}
                    {typeof confidence === "number"
                      ? ` · ${Math.round(confidence * 100)}% confidence`
                      : ""}
                  </span>
                  <span className="mt-7 flex items-center gap-2.5 text-[17px] font-medium">
                    <PackChip dot="#60a5fa" label="Microsoft IQ" value={iqCitations} />
                    <PackChip
                      dot="#67e8f9"
                      label="Integrations"
                      value={allCitations - iqCitations}
                    />
                  </span>
                  <span className="mt-4 inline-flex items-center gap-1 text-[16px] font-medium text-violet-100">
                    Click to explore
                    <HiChevronRight className="h-4 w-4" aria-hidden="true" />
                  </span>
                </div>
                <div
                  className="pointer-events-none absolute -translate-x-1/2 whitespace-nowrap text-[22px] font-semibold tracking-tight text-white"
                  style={{
                    left: caldovaBubble.cx,
                    top: caldovaBubble.cy - caldovaBubble.r + 30,
                    opacity: childReveal,
                    transition: fade,
                  }}
                  aria-hidden="true"
                >
                  Caldova IQ
                </div>
              </>
            ) : null}

            {microsoftBubble ? (
              <div
                className="pointer-events-none absolute flex w-[190px] flex-col items-center text-center"
                style={{
                  left: microsoftBubble.cx,
                  top: microsoftBubble.cy,
                  opacity: childReveal,
                  transform: `translate(-50%, -50%) scale(${0.9 + 0.1 * childReveal})`,
                  transition: fade,
                }}
                aria-hidden={childrenInteractive ? undefined : true}
              >
                <span className="text-[16px] font-semibold tracking-tight text-slate-900">
                  Microsoft IQ
                </span>
                <span className="mt-0.5 text-[38px] font-semibold leading-none tracking-[-0.03em] tabular-nums text-slate-900">
                  {iqCitations}
                </span>
                <span className="mt-1 text-[12px] text-slate-600">
                  {iqCitations === 1 ? "citation" : "citations"} · {activeIq} of {iqNodes.length}{" "}
                  sources
                </span>
              </div>
            ) : null}

            {bubbles.flatMap((bubble) => {
              const isChild = Boolean(bubble.parent);
              const visible = !isChild || childrenInteractive;
              const level = isChild ? innerLevel : outerLevel;
              return bubble.nodes.map((node) => {
                const delay = 120 + tileIndex++ * 60;
                const selected = node.key === selectedKey;
                return (
                  <div
                    key={node.key}
                    className="absolute h-0 w-0"
                    style={{
                      left: node.x,
                      top: node.y,
                      zIndex: selected ? 10 : undefined,
                      opacity: isChild ? childReveal : 1,
                      pointerEvents: visible ? undefined : "none",
                      transition: fade,
                    }}
                    inert={!visible}
                    onClick={(event) => event.stopPropagation()}
                  >
                    {/* Anchor on the icon's centre so labels and detail hang below it. */}
                    <div
                      className="absolute left-0 top-0"
                      style={{
                        transform: `scale(${counterScale}) translate(-50%, ${
                          level === "compact" ? -14 : -21
                        }px)`,
                        transformOrigin: "0 0",
                        transition,
                      }}
                    >
                      <div className="em-pop" style={{ animationDelay: `${delay}ms` }}>
                        <MapTile
                          node={node}
                          level={selected && level !== "compact" ? "detail" : level}
                          selected={selected}
                          onSelect={() => {
                            if (map.wasDragged()) return;
                            setSelectedKey(node.key);
                            setFocusKey(bubble.key);
                            map.focusOn(node.x, node.y, 110);
                          }}
                        />
                      </div>
                    </div>
                  </div>
                );
              });
            })}
          </div>
        </div>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-slate-500">
        Caldova IQ holds every evidence source the orchestrator can call: Microsoft IQ (FabricIQ,
        FoundryIQ, WebIQ, WorkIQ) and third-party integrations. Click it to zoom in. Tiles in
        colour cited evidence in this run; faded tiles weren't used. Waypoint Recorder remains the
        sole writer of the governed run, case, and recommendation.
      </p>
    </div>
  );
}

function evidenceFanoutCitations(fanout: FanoutLane[]): number {
  return fanout.reduce((acc, lane) => acc + laneClaimCount(lane), 0);
}

function PackChip({ dot, label, value }: { dot: string; label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-white/[0.12] py-1.5 pl-3 pr-3.5 ring-1 ring-inset ring-white/25">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: dot }} aria-hidden="true" />
      {label}
      <span className="tabular-nums text-violet-100">{value}</span>
    </span>
  );
}

function MapControl({
  label,
  onClick,
  bordered,
  children,
}: {
  label: string;
  onClick: () => void;
  bordered?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`flex h-8 w-8 items-center justify-center text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-600 ${
        bordered ? "border-t border-slate-200" : ""
      }`}
    >
      {children}
    </button>
  );
}


function MapTile({
  node,
  level,
  selected,
  onSelect,
}: {
  node: MapNode;
  level: MapLevel;
  selected: boolean;
  onSelect: () => void;
}) {
  const Icon = node.icon;
  const tileSize =
    level === "compact" ? "h-5 w-5 rounded-[5px] p-0.5" : "h-[34px] w-[34px] rounded-lg p-1";

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={`${node.label} (${node.title}): ${node.stats}`}
      aria-pressed={selected}
      className="group flex flex-col items-center gap-1.5 rounded-xl p-1 text-center focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
    >
      <span
        className={`relative inline-flex ${tileSize} items-center justify-center bg-white transition-[transform,box-shadow] duration-200 ease-out group-hover:-translate-y-0.5 ${
          node.active ? "" : node.ghost ? "opacity-80" : "opacity-50 grayscale"
        }`}
        style={{
          border: node.active
            ? `1.5px solid ${node.hex}`
            : `1.5px dashed ${node.ghost ? node.hex : "rgb(148 163 184)"}`,
          boxShadow: selected
            ? `0 0 0 4px ${node.hex}33, 0 6px 16px -6px rgb(15 23 42 / 0.35)`
            : "0 1px 2px rgb(15 23 42 / 0.08), 0 4px 10px -4px rgb(15 23 42 / 0.18)",
        }}
      >
        {node.img ? (
          <img src={node.img} alt="" loading="lazy" className="h-full w-full object-contain" />
        ) : (
          <Icon className={`h-full w-full ${node.iconClass}`} />
        )}
      </span>

      {level !== "compact" ? (
        <span
          className={`line-clamp-2 max-w-[120px] text-[12px] font-semibold leading-tight ${
            node.active ? "text-slate-800" : "text-slate-500"
          }`}
        >
          {node.label}
        </span>
      ) : null}

      {level !== "compact" && node.badge ? (
        <span
          className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase ring-1 ${node.badge.className}`}
        >
          {node.badge.text}
        </span>
      ) : null}

      {level === "detail" ? (
        <span className="w-[220px] rounded-lg border border-slate-200 bg-white px-3 py-2 text-left shadow-[0_1px_2px_rgba(15,23,42,0.06),0_8px_20px_-12px_rgba(15,23,42,0.35)]">
          <span className="block text-xs font-semibold text-slate-800">{node.title}</span>
          <span className={`block text-[11px] ${node.active ? node.iconClass : "text-slate-500"}`}>
            {node.stats}
          </span>
          {node.lines.length > 0 ? (
            <span className="mt-1.5 block space-y-1 border-t border-slate-100 pt-1.5">
              {node.lines.slice(0, 3).map((line) => (
                <span key={line} className="block truncate text-[11px] text-slate-600" title={line}>
                  {line}
                </span>
              ))}
              {node.lines.length > 3 ? (
                <span className="block text-[11px] text-slate-500">
                  +{node.lines.length - 3} more
                </span>
              ) : null}
            </span>
          ) : null}
        </span>
      ) : null}
    </button>
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
