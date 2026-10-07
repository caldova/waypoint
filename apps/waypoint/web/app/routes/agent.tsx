import type { MetaFunction } from "react-router";
import type { ComponentType, ReactNode } from "react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
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
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { INTEGRATIONS, integrationForLane } from "../../lib/integrations";
import { authFetch } from "../../lib/msalAuth";
import { AppHeader } from "../components/AppHeader";
import { useAuth } from "../components/AuthProvider";
import { RequireAuth } from "../components/RequireAuth";
import { useModalDialog } from "../hooks/useModalDialog";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useFormat, type Formatters } from "../i18n/format";
import { normalizeDecision, useLabels, type Labels } from "../i18n/labels";
import { pageMeta } from "../i18n/meta";

export const meta: MetaFunction = ({ location }) => pageMeta(location, "agent");

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

function formatMoney(fmt: Formatters, value: number | undefined): string {
  return fmt.currency(value, "USD", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Strip the internal knowledge-base chunk anchor from an evidence source_ref,
// keeping the human-citable document title. Handles both the bracketed
// ("[ref_id:2]") and the unbracketed, separator-prefixed ("; ref_id:0") forms.
function cleanSourceRef(ref: string): string {
  const cleaned = ref.replace(/\s*;?\s*\[?ref_id:\s*\d+\]?/gi, "").trim();
  return cleaned.length > 0 ? cleaned : ref;
}

// Same fields as the previous `toLocaleString()` default: numeric date with seconds.
const TIMESTAMP_FORMAT: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
};

function formatTimestamp(fmt: Formatters, value: string): string {
  return fmt.dateTime(value, TIMESTAMP_FORMAT) ?? value;
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

const DECISION_VALUES = new Set(["approve", "review", "recover", "escalate"]);

/** Runs without a decision show their status instead; label whichever it is. */
function outcomeLabel(labels: Labels, value: string | undefined): string {
  return DECISION_VALUES.has(normalizeDecision(value))
    ? labels.decision(value)
    : labels.runStatus(value);
}

// ---------------------------------------------------------------------------
// IQ planes ("the IQ logos")
// ---------------------------------------------------------------------------

type IqKey = "workiq" | "webiq" | "foundryiq" | "fabriciq" | "other";

interface IqMeta {
  key: IqKey;
  /** Set for third-party integrations (key "other"), e.g. "oracle-erp". */
  integrationKey?: string;
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

// Chip/ring colours per integration, written out so Tailwind can see them.
const INTEGRATION_STYLES: Record<string, Pick<IqMeta, "ring" | "badge" | "text" | "dot">> = {
  "oracle-erp": {
    ring: "ring-[#f2c4bc]",
    badge: "bg-[#fdf3f1] text-[#9f3527]",
    text: "text-[#9f3527]",
    dot: "bg-[#c74634]",
  },
};

const INTEGRATION_META: Record<string, IqMeta> = Object.fromEntries(
  INTEGRATIONS.map((integration) => [
    integration.key,
    {
      ...IQ_META.other,
      ...INTEGRATION_STYLES[integration.key],
      integrationKey: integration.key,
      label: integration.label,
      agent: integration.agent,
      tool: integration.product,
      icon: HiPuzzle,
      img: integration.img,
      hex: integration.hex,
    },
  ]),
);

// IQ planes keep their own meta; known integrations get their name and logo;
// anything else falls back to a generic "Expert".
function metaForLane(lane: FanoutLane): IqMeta {
  const key = iqKeyForLane(lane);
  if (key !== "other") return IQ_META[key];
  const integration = integrationForLane(lane);
  return integration ? INTEGRATION_META[integration.key] : IQ_META.other;
}

function metaKey(meta: IqMeta): string {
  return meta.integrationKey ?? meta.key;
}

// The generic fallback has no brand name, so its "Expert" label is translated.
function isGenericMeta(meta: IqMeta): boolean {
  return meta.key === "other" && !meta.integrationKey;
}

// Distinct sources for a run's evidence: IQ planes first, then integrations.
function sourceMetasFor(fanout: FanoutLane[]): IqMeta[] {
  const metas = new Map<string, IqMeta>();
  for (const lane of fanout) {
    const meta = metaForLane(lane);
    metas.set(metaKey(meta), meta);
  }
  const rank = (meta: IqMeta) => {
    const index = IQ_ORDER.indexOf(meta.key);
    return index === -1 ? IQ_ORDER.length : index;
  };
  return [...metas.values()].sort((a, b) => rank(a) - rank(b));
}

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
  sources: IqMeta[];
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
      findingCount: typeof latestMeta.finding_count === "number" ? latestMeta.finding_count : 0,
      confidence: groupConfidence(latestMeta, fanout),
      confidenceCalibrated: latestMeta.confidence_calibrated === true,
      iqKeys,
      sources: sourceMetasFor(fanout),
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

  const iqStats = IQ_ORDER.map((key) => ({
    meta: IQ_META[key],
    runCount: runCount[key],
    claimCount: claimCount[key],
    moneyAtRisk: moneyAtRisk[key],
    avgConfidence: confidenceCount[key] > 0 ? confidenceSum[key] / confidenceCount[key] : null,
  }));

  const integrationStats = new Map<string, IqStat & { confidenceSum: number; confidenceN: number }>();
  for (const run of runs) {
    const seen = new Set<string>();
    for (const lane of evidenceFanout(run.metadata ?? {})) {
      const meta = metaForLane(lane);
      if (!meta.integrationKey) continue;
      const stat = integrationStats.get(meta.integrationKey) ?? {
        meta,
        runCount: 0,
        claimCount: 0,
        moneyAtRisk: 0,
        avgConfidence: null,
        confidenceSum: 0,
        confidenceN: 0,
      };
      stat.claimCount += laneClaimCount(lane);
      const confidence = laneAvgConfidence(lane);
      if (typeof confidence === "number") {
        stat.confidenceSum += confidence;
        stat.confidenceN += 1;
      }
      if (!seen.has(meta.integrationKey)) {
        seen.add(meta.integrationKey);
        stat.runCount += 1;
      }
      integrationStats.set(meta.integrationKey, stat);
    }
  }
  for (const group of groups) {
    for (const meta of group.sources) {
      const stat = meta.integrationKey ? integrationStats.get(meta.integrationKey) : undefined;
      if (stat) stat.moneyAtRisk += group.moneyAtRisk;
    }
  }

  return [
    ...iqStats,
    ...[...integrationStats.values()].map(({ confidenceSum, confidenceN, ...stat }) => ({
      ...stat,
      avgConfidence: confidenceN > 0 ? confidenceSum / confidenceN : null,
    })),
  ].filter((stat) => stat.runCount > 0);
}

// ---------------------------------------------------------------------------
// Filtering / sorting
// ---------------------------------------------------------------------------

type TimeRangeKey = "7d" | "30d" | "90d" | "all";

const TIME_RANGES = [
  { key: "7d", labelKey: "filters.range.days7", days: 7 },
  { key: "30d", labelKey: "filters.range.days30", days: 30 },
  { key: "90d", labelKey: "filters.range.days90", days: 90 },
  { key: "all", labelKey: "filters.range.all", days: null },
] as const satisfies readonly { key: TimeRangeKey; labelKey: string; days: number | null }[];

type SortKey = "recent" | "money" | "confidence";

const SORT_OPTIONS = [
  { key: "recent", labelKey: "filters.sort.recent" },
  { key: "money", labelKey: "filters.sort.money" },
  { key: "confidence", labelKey: "filters.sort.confidence" },
] as const satisfies readonly { key: SortKey; labelKey: string }[];

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

function monthLabelOf(fmt: Formatters, key: string): string {
  const [year, month] = key.split("-").map(Number);
  if (!year || !month) {
    return key;
  }
  return fmt.date(new Date(year, month - 1, 1), { month: "short", year: "numeric" }) ?? key;
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
  const { t } = useTranslation("agent");
  const fmt = useFormat();
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
  // Read through a ref so switching language doesn't refetch the runs.
  const tRef = useRef(t);
  tRef.current = t;

  const fetchRuns = useCallback(async () => {
    if (auth.status !== "authenticated") {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await tracedFetch("fetchAgentRuns", "/api/runs");
      if (!response.ok) {
        throw new Error(tRef.current("errors.fetchFailedStatus", { status: response.statusText }));
      }
      const data: AgentRun[] = await response.json();
      data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setRuns(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : tRef.current("errors.fetchFailed"));
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
      // Fold aliases (e.g. "recovery") so each translated label appears once.
      set.add(normalizeDecision(group.decision));
    }
    return Array.from(set).sort();
  }, [allGroups]);

  // 2) Narrow by decision + search, then 3) sort.
  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = allGroups.filter((group) => {
      if (decisionFilter !== "all" && normalizeDecision(group.decision) !== decisionFilter) {
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
      {/* Below xl the run list and sidebar stack, so the page scrolls as a document; at xl
          they sit side by side and each pane scrolls on its own. */}
      <div className="flex min-h-screen bg-slate-50 text-slate-950 xl:h-screen xl:overflow-hidden">
        <div className="flex min-h-0 w-full flex-col">
          <AppHeader />

          <main
            id="main-content"
            className="relative mx-auto grid min-h-0 w-full max-w-[1500px] flex-1 grid-cols-1 gap-2 px-3 py-3 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:px-4"
          >
            <section
              className="flex flex-col rounded-lg border border-slate-200 bg-white p-3 shadow-sm xl:min-h-0"
              aria-labelledby="agent-heading"
            >
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 pb-3">
                <div>
                  <h1 id="agent-heading" className="text-2xl font-semibold tracking-tight">
                    {t("page.heading")}
                  </h1>
                  <p className="mt-1 max-w-[65ch] text-sm leading-6 text-slate-600">
                    {t("page.intro")}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void fetchRuns()}
                    className="inline-flex min-h-9 items-center gap-2 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 max-md:min-h-11"
                  >
                    <HiRefresh className="h-4 w-4" aria-hidden="true" />
                    {t("page.refresh")}
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

              <div className="mt-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-1">
                {loading ? (
                  <p className="px-1 py-6 text-sm text-slate-500">{t("page.loading")}</p>
                ) : runs.length === 0 ? (
                  <EmptyState />
                ) : groups.length === 0 ? (
                  <NoMatches onReset={resetFilters} />
                ) : (
                  <>
                  <h2 className="sr-only">{t("page.invoices")}</h2>
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
                  </>
                )}
              </div>
            </section>

            <aside className="flex flex-col gap-2 xl:min-h-0 xl:overflow-auto">
              <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                <h2 className="type-section">{t("usage.heading")}</h2>
                <p className="mt-1 type-meta leading-5">
                  {t("usage.description")}
                </p>
                {iqStats.length > 0 ? (
                  <ul className="mt-2.5 space-y-2">
                    {iqStats.map((stat) => (
                      <IqUsageTile key={metaKey(stat.meta)} stat={stat} />
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2.5 rounded-md border border-dashed border-slate-200 bg-slate-50/60 p-2.5 text-xs leading-5 text-slate-500">
                    {t("usage.empty")}
                  </p>
                )}
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                <h2 className="type-section">{t("totals.heading")}</h2>
                <dl className="mt-2 grid grid-cols-3 gap-2">
                  <Stat label={t("page.invoices")} value={String(totals.invoices)} />
                  <Stat label={t("totals.runs")} value={String(totals.runs)} />
                  <Stat
                    label={t("shared.atRisk")}
                    value={formatMoney(fmt, totals.moneyAtRisk)}
                    tone="text-emerald-700"
                    onClick={() => setCashKey((key) => key + 1)}
                    hint={t("totals.makeItRain")}
                  />
                </dl>
                {moneyTrend.length > 1 ? (
                  <div className="mt-3 border-t border-slate-100 pt-2.5">
                    <div className="flex items-center justify-between type-meta">
                      <span className="font-medium text-slate-600">{t("totals.trendHeading")}</span>
                      <span>{t("totals.days", { count: moneyTrend.length })}</span>
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
  size = "sm",
}: {
  label: string;
  value: string;
  tone?: string;
  onClick?: () => void;
  hint?: string;
  size?: "sm" | "lg";
}) {
  const valueClass = `mt-0.5 block font-semibold tabular-nums ${
    size === "lg" ? "text-lg" : "text-sm"
  } ${tone ?? ""}`;
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={hint}
        className="group -m-1.5 rounded-md p-1.5 text-left transition-colors hover:bg-emerald-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300"
      >
        <span className="block type-meta">{label}</span>
        <span className={valueClass}>{value}</span>
      </button>
    );
  }
  return (
    <div>
      <dt className="type-meta">{label}</dt>
      <dd className={valueClass}>{value}</dd>
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
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  const labels = useLabels();
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-slate-100 pb-3">
      <div className="flex items-center gap-1.5">
        <span className="type-label">{t("filters.when")}</span>
        <div className="inline-flex rounded-md border border-slate-200 p-0.5">
          {TIME_RANGES.map((range) => {
            const active = monthFilter === "all" && timeRange === range.key;
            return (
              <button
                key={range.key}
                type="button"
                onClick={() => onTimeRange(range.key)}
                aria-pressed={active}
                className={`rounded px-2 py-1 text-xs font-semibold transition-colors max-md:min-h-11 max-md:min-w-11 ${
                  active ? "bg-blue-700 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {t(range.labelKey)}
              </button>
            );
          })}
        </div>
        {months.length > 0 ? (
          <select
            value={monthFilter}
            onChange={(event) => onMonthFilter(event.target.value)}
            className="min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus:border-blue-300 focus:outline-none max-md:min-h-11 max-md:text-base"
            aria-label={t("filters.monthAriaLabel")}
          >
            <option value="all">{t("filters.anyMonth")}</option>
            {months.map((month) => (
              <option key={month} value={month}>
                {monthLabelOf(fmt, month)}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {decisions.length > 1 ? (
        <div className="flex items-center gap-1.5">
          <span className="type-label">{t("filters.decision")}</span>
          <div className="flex flex-wrap items-center gap-1">
            <DecisionChip
              label={t("filters.allDecisions")}
              active={decisionFilter === "all"}
              onClick={() => onDecisionFilter("all")}
            />
            {decisions.map((decision) => (
              <DecisionChip
                key={decision}
                label={outcomeLabel(labels, decision)}
                active={decisionFilter === decision}
                onClick={() => onDecisionFilter(decision)}
              />
            ))}
          </div>
        </div>
      ) : null}

      <div className="ml-auto flex items-center gap-2 max-md:ml-0 max-md:w-full">
        <div className="relative max-md:min-w-0 max-md:flex-1">
          <HiSearch
            className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder={t("filters.searchPlaceholder")}
            className="min-h-8 w-44 max-md:w-full rounded-md border border-slate-200 bg-white pl-7 pr-2 py-1 text-xs text-slate-700 placeholder:text-slate-500 focus:border-blue-300 focus:outline-none max-md:min-h-11 max-md:text-base"
            aria-label={t("filters.searchAriaLabel")}
          />
        </div>
        <select
          value={sort}
          onChange={(event) => onSort(event.target.value as SortKey)}
          className="min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus:border-blue-300 focus:outline-none max-md:min-h-11 max-md:text-base"
          aria-label={t("filters.sortAriaLabel")}
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {t(option.labelKey)}
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
      aria-pressed={active}
      className={`rounded-full px-2.5 py-1 text-xs font-semibold ring-1 transition-colors max-md:min-h-11 max-md:px-3.5 ${
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
  const { t } = useTranslation("agent");
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
      aria-label={t("totals.trendAriaLabel")}
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
  const { t } = useTranslation("agent");
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-1 py-12 text-center">
      <p className="text-sm font-medium text-slate-600">{t("filters.noMatches")}</p>
      <button
        type="button"
        onClick={onReset}
        className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50"
      >
        <HiX className="h-3.5 w-3.5" aria-hidden="true" />
        {t("filters.clear")}
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
  const { t } = useTranslation("agent");
  const fmt = useFormat();
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
              {isGenericMeta(meta) ? t("shared.expert") : meta.agent}
            </span>
            {meta.stub ? (
              <span className="shrink-0 rounded-full bg-amber-50 px-1.5 py-0.5 text-xs font-semibold text-amber-800 ring-1 ring-amber-200">
                {t("usage.stub")}
              </span>
            ) : null}
          </span>
          <span className={`shrink-0 text-xs font-semibold ${meta.text}`}>
            {idle ? "—" : t("shared.ranCount", { n: stat.runCount })}
          </span>
        </div>
        {meta.tool ? (
          <p className="mt-0.5 truncate type-meta">
            {t("usage.connectedTo", { tool: meta.tool })}
          </p>
        ) : null}
        <div className="mt-0.5 text-xs text-slate-500">
          {t("usage.citationsContributed", { count: stat.claimCount })}
        </div>
        {!idle && stat.avgConfidence != null ? (
          <div className="mt-1.5 flex items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full ${meta.dot}`}
                style={{ width: `${Math.round(Math.min(Math.max(stat.avgConfidence, 0), 1) * 100)}%` }}
              />
            </div>
            <span className="type-meta tabular-nums">
              {fmt.percent(stat.avgConfidence, 0)}
            </span>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function IqChip({ meta }: { meta: IqMeta }) {
  const { t } = useTranslation("agent");
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${meta.ring} ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden="true" />
      {isGenericMeta(meta) ? t("shared.expert") : meta.label}
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
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  const labels = useLabels();
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
              className={`rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${decisionStyle(
                group.decision,
              )}`}
            >
              {outcomeLabel(labels, group.decision)}
            </span>
            <h3 className="text-base font-semibold leading-6">{group.label}</h3>
            {group.moneyAtRisk > 0 ? (
              <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-100">
                {t("shared.amountAtRisk", { amount: formatMoney(fmt, group.moneyAtRisk) })}
              </span>
            ) : null}
            <span className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-600">
              <HiRefresh className="h-3.5 w-3.5" aria-hidden="true" />
              {t("shared.ranCount", { n: group.runCount })}
            </span>
            {group.confidence != null ? (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-600"
                title={
                  group.confidenceCalibrated
                    ? t("invoice.calibratedHint")
                    : t("invoice.uncalibratedHint")
                }
              >
                {labels.score(group.confidence, group.confidenceCalibrated)}
              </span>
            ) : null}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {group.sources.length > 0 ? (
              group.sources.map((meta) => <IqChip key={metaKey(meta)} meta={meta} />)
            ) : (
              <span className="type-meta">{t("invoice.noEvidence")}</span>
            )}
          </div>
          <p className="mt-1.5 flex items-center gap-1 type-meta">
            <HiClock className="h-3.5 w-3.5" aria-hidden="true" />
            {t("invoice.lastRun", { time: formatTimestamp(fmt, group.lastRunAt) })}
            {group.findingCount > 0 ? (
              <span>
                {" "}
                · {t("invoice.findings", { count: group.findingCount })}
              </span>
            ) : null}
          </p>
        </div>
        <span className="mt-1 shrink-0 text-slate-500">
          {expanded ? (
            <HiChevronDown className="h-5 w-5" aria-hidden="true" />
          ) : (
            <HiChevronRight className="h-5 w-5" aria-hidden="true" />
          )}
        </span>
      </button>

      {expanded ? (
        <div className="border-t border-slate-100 px-3 py-2.5">
          <h4 className="mb-1.5 type-label">{t("invoice.runHistory")}</h4>
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
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  const labels = useLabels();
  const meta = run.metadata ?? {};
  const fanout = evidenceFanout(meta);
  const sources = sourceMetasFor(fanout);
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
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span
              className={`rounded px-1.5 py-0.5 text-xs font-semibold ring-1 ${decisionStyle(
                meta.decision || run.status,
              )}`}
            >
              {outcomeLabel(labels, meta.decision || run.status)}
            </span>
            {latest ? (
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-semibold text-blue-700 ring-1 ring-blue-100">
                {t("run.latest")}
              </span>
            ) : null}
            <span className="max-w-full truncate type-meta">{formatTimestamp(fmt, run.created_at)}</span>
          </div>
          <p className="mt-0.5 line-clamp-1 text-sm text-slate-600">
            {run.summary || t("run.noSummary")}
          </p>
          {sources.length > 0 ? (
            <div className="mt-1 flex items-center gap-1">
              {sources.map((source) => (
                <IqLogo key={metaKey(source)} meta={source} size="h-5 w-5" />
              ))}
            </div>
          ) : null}
        </div>
        <span className="shrink-0 text-xs font-semibold text-blue-700">{t("run.view")}</span>
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Run lightbox
// ---------------------------------------------------------------------------

function RunLightbox({ run, onClose }: { run: AgentRun; onClose: () => void }) {
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  const labels = useLabels();
  const meta = run.metadata ?? {};
  const fanout = evidenceFanout(meta);
  const analystLanes = useMemo(
    () => (Array.isArray(meta.fanout) ? meta.fanout.filter(isAnalystLane) : []),
    [meta.fanout],
  );
  const invoiceLabel = meta.invoice_number || meta.invoice_id || run.name;

  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useModalDialog(dialogRef, { onClose, initialFocusRef: headingRef });

  // Below xl the page scrolls as a document; stop it scrolling behind the dialog.
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = previous;
    };
  }, []);

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4 max-md:p-2 xl:absolute xl:z-30"
      role="dialog"
      aria-modal="true"
      aria-label={t("lightbox.ariaLabel", { invoice: invoiceLabel })}
      onClick={onClose}
    >
      <section
        className="flex max-h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 p-4">
          <div className="min-w-0">
            <h2
              ref={headingRef}
              tabIndex={-1}
              className="flex flex-wrap items-center gap-2 rounded-sm text-xl font-semibold"
            >
              {invoiceLabel}
              <span
                className={`rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${decisionStyle(
                  meta.decision || run.status,
                )}`}
              >
                {outcomeLabel(labels, meta.decision || run.status)}
              </span>
            </h2>
            <p className="mt-0.5 text-sm text-slate-600">
              {t("lightbox.ranOn", {
                time: formatTimestamp(fmt, run.created_at),
                author: run.created_by,
              })}
            </p>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-500 hover:bg-slate-50 max-md:flex max-md:h-11 max-md:w-11 max-md:items-center max-md:justify-center"
            onClick={onClose}
          >
            <HiX className="h-5 w-5" aria-hidden="true" />
            <span className="sr-only">{t("lightbox.close")}</span>
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:flex sm:flex-wrap sm:gap-x-10">
            <Stat
              label={t("shared.atRisk")}
              value={formatMoney(fmt, meta.money_at_risk)}
              tone="text-emerald-700"
              size="lg"
            />
            <Stat
              label={
                meta.confidence_calibrated === true
                  ? t("lightbox.confidence")
                  : t("lightbox.evidenceScore")
              }
              value={typeof meta.confidence === "number" ? fmt.percent(meta.confidence, 0) : "—"}
              size="lg"
            />
            <Stat label={t("lightbox.experts")} value={String(fanout.length)} size="lg" />
            <Stat
              label={t("lightbox.findings")}
              size="lg"
              value={typeof meta.finding_count === "number" ? String(meta.finding_count) : "—"}
            />
          </dl>

          {run.summary ? (
            <p className="max-w-[75ch] text-sm leading-6 text-slate-700">
              {run.summary}
            </p>
          ) : null}

          <EvidenceMap
            fanout={fanout}
            analystLanes={analystLanes}
            decision={meta.decision || run.status}
            moneyAtRisk={meta.money_at_risk}
            confidence={meta.confidence}
            confidenceCalibrated={meta.confidence_calibrated === true}
          />

          <div>
            <h3 className="text-sm font-semibold text-slate-800">{t("lightbox.perExpertHeading")}</h3>
            {fanout.length > 0 ? (
              <ol className="mt-1 divide-y divide-slate-100">
                {fanout.map((lane, index) => (
                  <ExpertLane key={`${lane.agent ?? lane.plane ?? "lane"}-${index}`} lane={lane} />
                ))}
              </ol>
            ) : (
              <p className="mt-1 text-sm text-slate-500">
                {t("lightbox.noPerExpert")}
              </p>
            )}
          </div>

          {run.foundry_agent_name ||
          run.foundry_conversation_id ||
          run.app_insights_operation_id ? (
            <div className="border-t border-slate-100 pt-4">
              <h3 className="type-label">{t("lightbox.telemetry.heading")}</h3>
              <dl className="mt-1.5 space-y-1 text-xs text-slate-600">
                {run.foundry_agent_name ? (
                  <TelemetryRow label={t("lightbox.telemetry.foundryAgent")} value={run.foundry_agent_name} />
                ) : null}
                {run.foundry_conversation_id ? (
                  <TelemetryRow label={t("lightbox.telemetry.conversation")} value={run.foundry_conversation_id} />
                ) : null}
                {run.app_insights_operation_id ? (
                  <TelemetryRow label={t("lightbox.telemetry.operation")} value={run.app_insights_operation_id} />
                ) : null}
                <TelemetryRow label={t("lightbox.telemetry.runId")} value={run.id} />
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
      <dt className="text-slate-500">{label}</dt>
      <dd>
        <code className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
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
  /** Evidence sources only: cited claims and their mean confidence (0-1). */
  citations?: number;
  avgConfidence?: number | null;
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
    const meta = metaForLane(lane);
    const key =
      meta.key !== "other"
        ? meta.key
        : `other:${meta.integrationKey ?? lane.agent ?? lane.plane ?? index}`;
    const group = groups.get(key) ?? { meta, lane, evidence: [] };
    group.evidence.push(...citedEvidence(lane));
    groups.set(key, group);
  });
  return groups;
}

// Third-party (non-IQ) evidence lanes. Empty today; the Integrations bubble
// shows a placeholder until a connector contributes cited evidence.
function buildIntegrationNodes(
  fanout: FanoutLane[],
  t: TFunction<"agent">,
  fmt: Formatters,
): MapNode[] {
  const groups = groupEvidenceLanes(fanout);
  const keys = [...groups.keys()].filter((key) => key.startsWith("other:")).sort();
  const positions = layoutAgents(Math.max(keys.length, 1), INTEGRATIONS_BUBBLE);
  if (keys.length === 0) {
    return [
      {
        key: "integrations-placeholder",
        ghost: true,
        label: t("map.node.integrationsPlaceholder.label"),
        title: t("map.node.integrationsPlaceholder.title"),
        stats: t("map.node.integrationsPlaceholder.stats"),
        lines: [],
        active: false,
        hex: "#0891b2",
        icon: HiPuzzle,
        iconClass: "text-cyan-700",
        ...positions[0],
      },
    ];
  }
  return keys.map((key, index) => {
    const node = evidenceNodeFor(key, groups.get(key), positions[index], t, fmt);
    // Known integrations keep their own logo and colour.
    return groups.get(key)?.meta.integrationKey
      ? node
      : { ...node, hex: "#0891b2", icon: HiPuzzle, iconClass: "text-cyan-700" };
  });
}

function buildEvidenceNodes(fanout: FanoutLane[], t: TFunction<"agent">, fmt: Formatters): MapNode[] {
  const groups = groupEvidenceLanes(fanout);
  // Keep every IQ plane on the map so positions stay stable run to run.
  const positions = layoutEvidence(IQ_ORDER.length, MICROSOFT_BUBBLE);
  return IQ_ORDER.map((key, index) =>
    evidenceNodeFor(key, groups.get(key), positions[index], t, fmt),
  );
}

function evidenceNodeFor(
  key: string,
  group: LaneGroup | undefined,
  position: { x: number; y: number },
  t: TFunction<"agent">,
  fmt: Formatters,
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
  const generic = isGenericMeta(meta);
  const agentId = lane.agent || lane.plane;
  return {
    key,
    label: generic
      ? lane.plane
        ? humanizeIdentifier(lane.plane)
        : t("map.node.evidenceSourceFallback")
      : meta.label,
    title: generic
      ? agentId
        ? humanizeIdentifier(agentId)
        : t("map.node.integrationFallback")
      : meta.agent,
    stats: active
      ? avg !== null
        ? t("map.node.citationsWithScore", {
            count: evidence.length,
            percent: fmt.percent(avg, 0),
          })
        : t("shared.citations", { count: evidence.length })
      : t("map.node.notUsed"),
    lines: [
      ...new Set(evidence.map((item) => cleanSourceRef(item.source_ref ?? "")).filter(Boolean)),
    ],
    active,
    citations: evidence.length,
    avgConfidence: avg,
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
  confidenceCalibrated,
  t,
  fmt,
  labels,
}: {
  evidenceFanout: FanoutLane[];
  analystLanes: FanoutLane[];
  decision: string;
  moneyAtRisk: number | undefined;
  confidence: number | undefined;
  confidenceCalibrated: boolean;
  t: TFunction<"agent">;
  fmt: Formatters;
  labels: Labels;
}): MapBubble[] {
  const evidenceNodes = buildEvidenceNodes(evidenceFanout, t, fmt);
  const integrationNodes = buildIntegrationNodes(evidenceFanout, t, fmt);
  const activeIq = evidenceNodes.filter((node) => node.active).length;
  const connectedIntegrations = integrationNodes.filter((node) => node.active).length;
  const activeSources = activeIq + connectedIntegrations;
  const totalSources =
    evidenceNodes.length +
    integrationNodes.filter((node) => node.key !== "integrations-placeholder").length;

  const orchestrationPositions = layoutAgents(2, ORCHESTRATION_BUBBLE);
  const orchestratorLines = [
    typeof moneyAtRisk === "number" && moneyAtRisk > 0
      ? t("shared.amountAtRisk", { amount: formatMoney(fmt, moneyAtRisk) })
      : "",
    typeof confidence === "number" ? labels.score(confidence, confidenceCalibrated) : "",
  ].filter(Boolean);
  const orchestration: MapBubble = {
    key: "orchestration",
    title: t("map.bubbleName.orchestration"),
    ...ORCHESTRATION_BUBBLE,
    ...glassBubble("#4f46e5", "#eef2ff", "#dfe4ff"),
    titlePlacement: "below",
    nodes: [
      {
        key: "invoice-intake",
        label: t("map.node.intake.label"),
        title: "Content Understanding",
        stats: t("map.node.intake.stats"),
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
        title: t("map.node.orchestrator.title"),
        stats: t("map.node.orchestrator.fannedOut", { count: activeSources }),
        lines: orchestratorLines,
        badge: { text: outcomeLabel(labels, decision), className: decisionStyle(decision) },
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
    title: t("map.bubbleTitle.caldova", { active: activeSources, total: totalSources }),
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
    title: t("map.bubbleName.microsoft"),
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
    title: t("map.bubbleTitle.integrations", { n: connectedIntegrations }),
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
    title: t("map.bubbleName.record"),
    ...recordBubbleShape,
    ...glassBubble("#059669", "#ecfdf5", "#d1fae5"),
    // Keep the title clear of the connector down to the analysts bubble.
    titlePlacement: hasAnalysts ? "above" : "below",
    nodes: [
      {
        key: "waypoint-recorder",
        label: "Caldova Recorder",
        title: t("map.node.recorder.title"),
        stats: t("map.node.recorder.stats"),
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
      title: t("map.bubbleTitle.analysts", { n: analystLanes.length }),
      ...analystShape,
      ...glassBubble("#7c3aed", "#f5f3ff", "#ede9fe"),
      titlePlacement: "below",
      nodes: analystLanes.map((lane, index) => ({
        key: `analyst-${lane.agent || lane.plane || index}`,
        label:
          lane.agent || lane.plane
            ? humanizeIdentifier(lane.agent || lane.plane || "")
            : t("map.node.analyst.fallback"),
        title: t("map.node.analyst.title"),
        stats: t("map.node.analyst.stats"),
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

  // Pan (without zooming) so a keyboard-focused bubble or tile that sits
  // partly outside the viewport comes fully into view.
  const revealElement = useCallback(
    (target: HTMLElement) => {
      const el = viewportRef.current;
      if (!el) return;
      const box = el.getBoundingClientRect();
      const rect = target.getBoundingClientRect();
      const margin = 16;
      const shift = (start: number, size: number, min: number, max: number) => {
        if (size > max - min - 2 * margin) return (min + max) / 2 - (start + size / 2);
        if (start < min + margin) return min + margin - start;
        if (start + size > max - margin) return max - margin - (start + size);
        return 0;
      };
      const dx = shift(rect.left, rect.width, box.left, box.right);
      const dy = shift(rect.top, rect.height, box.top, box.bottom);
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
      startAnimation();
      setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }));
    },
    [startAnimation],
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
    canZoomIn: view.scale < fitScale * MAX_ZOOM - 1e-6,
    canZoomOut: view.scale > fitScale * MIN_ZOOM + 1e-6,
    zoomIn: () => zoomByButton(1.25),
    zoomOut: () => zoomByButton(1 / 1.25),
    resetView: () => applyFit(true),
    focusOn,
    revealElement,
    zoomToCircle,
    wasDragged: () => draggedRef.current,
    onPointerDown,
    onPointerMove,
    endDrag,
  };
}

const BUBBLE_NAME_KEYS = {
  orchestration: "map.bubbleName.orchestration",
  caldova: "map.bubbleName.caldova",
  microsoft: "map.bubbleName.microsoft",
  integrations: "map.bubbleName.integrations",
  record: "map.bubbleName.record",
  analysts: "map.bubbleName.analysts",
} as const satisfies Record<BubbleKey, string>;

const PACKED_KEYS: BubbleKey[] = ["caldova", "microsoft", "integrations"];

function EvidenceMap({
  fanout,
  analystLanes,
  decision,
  moneyAtRisk,
  confidence,
  confidenceCalibrated,
}: {
  fanout: FanoutLane[];
  analystLanes: FanoutLane[];
  decision: string;
  moneyAtRisk: number | undefined;
  confidence: number | undefined;
  confidenceCalibrated: boolean;
}) {
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  const labels = useLabels();
  const bubbles = useMemo(
    () =>
      buildMapBubbles({
        evidenceFanout: fanout,
        analystLanes,
        decision,
        moneyAtRisk,
        confidence,
        confidenceCalibrated,
        t,
        fmt,
        labels,
      }),
    [fanout, analystLanes, decision, moneyAtRisk, confidence, confidenceCalibrated, t, fmt, labels],
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
    connectors.push({ from: "record", to: "analysts", label: t("map.connector.reads") });
  }

  const map = useMapView();
  const reducedMotion = usePrefersReducedMotion();
  const [mode, setMode] = useAgentMapMode();
  const hintId = useId();
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
  const fade = reducedMotion ? undefined : `opacity 450ms ${MAP_EASE}, transform 450ms ${MAP_EASE}`;
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

  // Keyboard focus on an off-screen bubble or tile pans it into view.
  const revealOnKeyboardFocus = (event: React.FocusEvent<HTMLElement>) => {
    const target = event.target as HTMLElement;
    if (target.matches(":focus-visible")) map.revealElement(target);
  };

  let tileIndex = 0;

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
        <h3 className="text-sm font-semibold text-slate-800">{t("map.heading")}</h3>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-xs text-slate-600">
            {t("map.summary", {
              count: agentCount,
              active: activeSources,
              total: sourceNodes.length,
            })}
          </p>
          <div
            role="group"
            aria-label={t("map.viewAriaLabel")}
            className="flex rounded-md border border-slate-200 bg-white p-0.5 text-xs font-medium"
          >
            {(["map", "list"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={mode === option}
                onClick={() => setMode(option)}
                className={`rounded px-2.5 py-1 transition-colors max-md:min-h-11 max-md:px-3.5 ${
                  mode === option
                    ? "bg-slate-900 text-white"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                }`}
              >
                {option === "map" ? t("map.mode.map") : t("map.mode.list")}
              </button>
            ))}
          </div>
        </div>
      </div>

      {mode === "list" ? (
        <AgentMapList
          bubbles={bubbles}
          allCitations={allCitations}
          iqCitations={iqCitations}
          activeSources={activeSources}
          totalSources={sourceNodes.length}
          confidence={confidence}
          confidenceCalibrated={confidenceCalibrated}
        />
      ) : null}
      {/* Kept mounted while hidden so the map's resize and wheel listeners stay bound. */}
      <div hidden={mode !== "map"}>
        <div className="relative mt-2 overflow-clip rounded-xl bg-slate-50">
          <nav
            aria-label={t("map.zoomLevelAriaLabel")}
            className="absolute left-2 top-2 z-20 flex items-center gap-0.5 rounded-md border border-slate-200 bg-white/90 px-1 py-0.5 text-xs shadow-[0_1px_2px_rgba(15,23,42,0.06),0_4px_12px_-6px_rgba(15,23,42,0.18)] backdrop-blur"
          >
            <button
              type="button"
              onClick={resetView}
              aria-current={trail.length === 0 ? "location" : undefined}
              className={`rounded px-1.5 py-1 font-medium transition-colors hover:bg-slate-100 ${
                trail.length === 0 ? "text-slate-900" : "text-slate-600"
              }`}
            >
              {t("map.allAgents")}
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
                    className={`rounded px-1.5 py-1 font-medium transition-colors hover:bg-slate-100 ${
                      last ? "text-violet-700" : "text-slate-600"
                    }`}
                  >
                    {t(BUBBLE_NAME_KEYS[key])}
                  </button>
                </span>
              );
            })}
          </nav>
          <div className="absolute right-2 top-2 z-20 flex flex-col overflow-hidden rounded-md border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.06),0_4px_12px_-6px_rgba(15,23,42,0.18)]">
            <MapControl label={t("map.zoomIn")} onClick={map.zoomIn} disabled={!map.canZoomIn}>
              <HiPlus className="h-4 w-4" aria-hidden="true" />
            </MapControl>
            <MapControl label={t("map.zoomOut")} onClick={map.zoomOut} disabled={!map.canZoomOut} bordered>
              <HiMinus className="h-4 w-4" aria-hidden="true" />
            </MapControl>
            <MapControl label={t("map.fit")} onClick={resetView} bordered>
              <HiArrowsExpand className="h-3.5 w-3.5" aria-hidden="true" />
            </MapControl>
          </div>
          <span className="pointer-events-none absolute bottom-2 left-3 z-20 text-xs text-slate-600">
            {t("map.hint")}
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
            aria-label={t("map.ariaLabel")}
            aria-describedby={hintId}
          >
            <p id={hintId} className="sr-only">
              {t("map.srHint")}
            </p>
            <style>{`
              @keyframes em-pop {
                from { opacity: 0; transform: scale(.6); filter: blur(4px); }
                to { opacity: 1; transform: scale(1); filter: blur(0); }
              }
              @keyframes em-dash { to { stroke-dashoffset: -26; } }
              .em-bubble { transition: filter 200ms ease-out, opacity 450ms ${MAP_EASE}, transform 450ms ${MAP_EASE}; }
              .em-bubble:hover { filter: brightness(1.04) saturate(1.08); }
              .em-bubble:focus-visible { outline: 4px solid #7c3aed; outline-offset: 6px; }
              @media (prefers-reduced-motion: reduce) {
                .em-bubble { transition: none; }
              }
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
                          className="fill-slate-600 text-[20px] font-medium"
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
                      inert={!visible}
                      aria-label={t("map.zoomInto", { name: t(BUBBLE_NAME_KEYS[bubble.key]) })}
                      aria-current={focusKey === bubble.key ? "location" : undefined}
                      onFocus={revealOnKeyboardFocus}
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
                      {t("map.bubbleName.caldova")}
                    </span>
                    <span className="mt-1 text-[104px] font-semibold leading-none tracking-[-0.035em] tabular-nums [text-shadow:0_4px_18px_rgb(30_27_75/0.35)]">
                      {allCitations}
                    </span>
                    <span className="mt-2 text-[21px] text-violet-100">
                      {t("map.citationUnit", { count: allCitations })}
                      {typeof confidence === "number"
                        ? ` · ${labels.score(confidence, confidenceCalibrated)}`
                        : ""}
                    </span>
                    <span className="mt-7 flex items-center gap-2.5 text-[20px] font-medium">
                      <PackChip dot="#60a5fa" label={t("map.bubbleName.microsoft")} value={iqCitations} />
                      <PackChip
                        dot="#67e8f9"
                        label={t("map.bubbleName.integrations")}
                        value={allCitations - iqCitations}
                      />
                    </span>
                    <span className="mt-4 inline-flex items-center gap-1 text-[20px] font-medium text-violet-100">
                      {t("map.clickToExplore")}
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
                    {t("map.bubbleName.caldova")}
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
                    {t("map.bubbleName.microsoft")}
                  </span>
                  <span className="mt-0.5 text-[38px] font-semibold leading-none tracking-[-0.03em] tabular-nums text-slate-900">
                    {iqCitations}
                  </span>
                  <span className="mt-1 text-[16px] leading-snug text-slate-600">
                    {t("map.citationUnit", { count: iqCitations })}
                    <span className="block">
                      {t("map.sourcesOf", { active: activeIq, total: iqNodes.length })}
                    </span>
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
                      onFocus={revealOnKeyboardFocus}
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
        <p className="mt-1.5 max-w-[100ch] text-xs leading-5 text-slate-600">
          {t("map.footnote")}
        </p>
      </div>
    </div>
  );
}

type AgentMapMode = "map" | "list";
const AGENT_MAP_MODE_KEY = "waypoint.agentMap.view";

// Remember Map vs List across runs so a screen-reader or keyboard user who
// prefers the list doesn't have to switch on every run.
function useAgentMapMode(): [AgentMapMode, (mode: AgentMapMode) => void] {
  const [mode, setMode] = useState<AgentMapMode>(() => {
    try {
      return window.localStorage.getItem(AGENT_MAP_MODE_KEY) === "list" ? "list" : "map";
    } catch {
      return "map";
    }
  });
  const update = useCallback((next: AgentMapMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(AGENT_MAP_MODE_KEY, next);
    } catch {
      // Storage can be unavailable (private mode); the choice just won't persist.
    }
  }, []);
  return [mode, update];
}

function nodeEvidenceSummary(node: MapNode, t: TFunction<"agent">, fmt: Formatters): string {
  if (node.citations === undefined) return node.stats;
  if (!node.active) return t("map.node.notUsed");
  const parts = [t("map.list.used", { count: node.citations })];
  if (typeof node.avgConfidence === "number") {
    parts.push(t("map.list.avgConfidence", { percent: fmt.percent(node.avgConfidence, 0) }));
  }
  return parts.join(" · ");
}

function AgentMapListNodes({ nodes }: { nodes: MapNode[] }) {
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  return (
    <ul className="mt-1 divide-y divide-slate-200/70">
      {nodes.map((node) => {
        const isSource = node.citations !== undefined;
        return (
          <li key={node.key} className="py-2.5">
            <p className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm">
              <span className={`font-semibold ${node.active ? "text-slate-900" : "text-slate-600"}`}>
                {node.label}
              </span>
              <span className="text-xs text-slate-600">{node.title}</span>
              {node.badge ? (
                <span
                  className={`rounded px-1.5 py-px text-xs font-semibold ring-1 ${node.badge.className}`}
                >
                  {node.badge.text}
                </span>
              ) : null}
            </p>
            <p
              className={`mt-0.5 text-xs ${
                isSource && node.active ? "font-medium text-slate-800" : "text-slate-600"
              }`}
            >
              {nodeEvidenceSummary(node, t, fmt)}
            </p>
            {node.lines.length > 0 ? (
              isSource ? (
                <div className="mt-1.5">
                  <p className="text-xs text-slate-600">{t("map.list.sources")}</p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {node.lines.map((line) => (
                      <li key={line}>
                        <code className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-700 ring-1 ring-slate-200">
                          {line}
                        </code>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <ul className="mt-1 space-y-0.5 text-xs text-slate-600">
                  {node.lines.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              )
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

// Text equivalent of the circle pack: the same bubbles and agents, in flow
// order, with each evidence source's use, citations, confidence and refs.
function AgentMapList({
  bubbles,
  allCitations,
  iqCitations,
  activeSources,
  totalSources,
  confidence,
  confidenceCalibrated,
}: {
  bubbles: MapBubble[];
  allCitations: number;
  iqCitations: number;
  activeSources: number;
  totalSources: number;
  confidence: number | undefined;
  confidenceCalibrated: boolean;
}) {
  const { t } = useTranslation("agent");
  const labels = useLabels();
  const byKey = new Map(bubbles.map((bubble) => [bubble.key, bubble]));
  const children = (key: BubbleKey) => bubbles.filter((bubble) => bubble.parent === key);
  const topLevel = bubbles.filter((bubble) => !bubble.parent);
  const microsoft = byKey.get("microsoft");
  const integrations = byKey.get("integrations");
  const connectedIntegrations = integrations?.nodes.filter((node) => node.active).length ?? 0;
  const iqUsed = microsoft?.nodes.filter((node) => node.active).length ?? 0;

  const summaryFor = (bubble: MapBubble): string => {
    switch (bubble.key) {
      case "caldova":
        return [
          t("shared.citations", { count: allCitations }),
          typeof confidence === "number" ? labels.score(confidence, confidenceCalibrated) : "",
          t("map.list.sourcesUsed", { active: activeSources, total: totalSources }),
        ]
          .filter(Boolean)
          .join(" · ");
      case "microsoft":
        return [
          t("shared.citations", { count: iqCitations }),
          t("map.list.iqSourcesUsed", { active: iqUsed, total: microsoft?.nodes.length ?? 0 }),
        ].join(" · ");
      case "integrations":
        return connectedIntegrations > 0
          ? t("map.list.integrationsConnected", { count: connectedIntegrations })
          : t("map.list.noIntegrations");
      case "orchestration":
        return t("map.list.orchestration");
      case "record":
        return t("map.list.record");
      case "analysts":
        return t("map.list.analysts");
      default:
        return "";
    }
  };

  const renderBubble = (bubble: MapBubble, level: number) => {
    const nested = children(bubble.key);
    const nodes = bubble.nodes.filter((node) => node.key !== "integrations-placeholder");
    const Heading = level === 0 ? "h4" : "h5";
    return (
      <>
        <Heading className="text-sm font-semibold text-slate-900">{t(BUBBLE_NAME_KEYS[bubble.key])}</Heading>
        <p className="mt-0.5 text-xs text-slate-600">{summaryFor(bubble)}</p>
        {nodes.length > 0 ? <AgentMapListNodes nodes={nodes} /> : null}
        {nested.length > 0 ? (
          <ul className="mt-3 space-y-4 border-l border-violet-200 pl-3">
            {nested.map((child) => (
              <li key={child.key}>{renderBubble(child, level + 1)}</li>
            ))}
          </ul>
        ) : null}
      </>
    );
  };

  return (
    <div className="mt-2 rounded-xl bg-slate-50 p-4">
      <p className="text-xs leading-5 text-slate-600">
        {byKey.has("analysts") ? t("map.list.flowWithAnalysts") : t("map.list.flow")}
      </p>
      <ol className="mt-3 space-y-4">
        {topLevel.map((bubble) => (
          <li key={bubble.key}>{renderBubble(bubble, 0)}</li>
        ))}
      </ol>
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
  disabled = false,
  children,
}: {
  label: string;
  onClick: () => void;
  bordered?: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  // aria-disabled (not disabled) so a focused control at its zoom limit keeps focus.
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      aria-label={label}
      aria-disabled={disabled || undefined}
      title={label}
      className={`flex h-8 w-8 items-center justify-center transition-colors max-md:h-11 max-md:w-11 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-600 ${
        disabled
          ? "cursor-not-allowed text-slate-300"
          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
      } ${bordered ? "border-t border-slate-200" : ""}`}
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
  const { t } = useTranslation("agent");
  const Icon = node.icon;
  const tileSize =
    level === "compact" ? "h-5 w-5 rounded-[5px] p-0.5" : "h-[34px] w-[34px] rounded-lg p-1";

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={t("map.tile.ariaLabel", { label: node.label, title: node.title, stats: node.stats })}
      aria-pressed={selected}
      className="group flex flex-col items-center gap-1.5 rounded-xl p-1 text-center focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
    >
      <span
        className={`relative inline-flex ${tileSize} items-center justify-center bg-white transition-[transform,box-shadow] duration-200 ease-out group-hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:group-hover:translate-y-0 ${
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
          className={`rounded px-1.5 py-px text-xs font-semibold ring-1 ${node.badge.className}`}
        >
          {node.badge.text}
        </span>
      ) : null}

      {level === "detail" ? (
        <span className="w-[220px] rounded-lg border border-slate-200 bg-white px-3 py-2 text-left shadow-[0_1px_2px_rgba(15,23,42,0.06),0_8px_20px_-12px_rgba(15,23,42,0.35)]">
          <span className="block text-xs font-semibold text-slate-800">{node.title}</span>
          <span className={`block text-xs ${node.active ? node.iconClass : "text-slate-500"}`}>
            {node.stats}
          </span>
          {node.lines.length > 0 ? (
            <span className="mt-1.5 block space-y-1 border-t border-slate-100 pt-1.5">
              {node.lines.slice(0, 3).map((line) => (
                <span key={line} className="block truncate text-xs text-slate-600" title={line}>
                  {line}
                </span>
              ))}
              {node.lines.length > 3 ? (
                <span className="block text-xs text-slate-500">
                  {t("map.tile.more", { n: node.lines.length - 3 })}
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
  const { t } = useTranslation("agent");
  const fmt = useFormat();
  const evidence = citedEvidence(lane);
  const meta = metaForLane(lane);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
        <IqLogo meta={meta} size="h-7 w-7" />
        <span className="font-semibold">
          {isGenericMeta(meta) ? lane.agent || lane.plane || t("shared.expert") : meta.label}
        </span>
        <span className="type-meta">
          {t("shared.citations", { count: evidence.length })}
        </span>
      </div>
      {lane.summary ? <p className="mt-1 pl-9 text-sm text-slate-600">{lane.summary}</p> : null}
      {evidence.length > 0 ? (
        <ul className="mt-2 space-y-2 pl-9">
          {evidence.map((item, index) => (
            <li key={index} className="text-sm text-slate-600">
              <span className="block">{item.claim || t("lane.noCitationText")}</span>
              <span className="mt-0.5 flex flex-wrap items-center gap-2 type-meta">
                {item.source_ref ? (
                  <code className="rounded bg-slate-50 px-1.5 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                    {cleanSourceRef(item.source_ref)}
                  </code>
                ) : null}
                {item.supports ? <span>· {t("lane.supports", { value: item.supports })}</span> : null}
                {item.classification ? <span>· {item.classification}</span> : null}
                {typeof item.confidence === "number" ? (
                  <span>· {fmt.percent(item.confidence, 0)}</span>
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
  const { t } = useTranslation("agent");
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50/60 p-6 text-center">
      <h3 className="text-base font-semibold text-slate-700">{t("empty.heading")}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
        {t("empty.body")}
      </p>
    </div>
  );
}
