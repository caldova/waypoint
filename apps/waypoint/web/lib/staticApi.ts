/**
 * In-browser stand-in for the Waypoint API, used only by the static build.
 *
 * Reads a scrubbed snapshot of the live API (`public/static-data/snapshot.json`,
 * written by `scripts/snapshot-static-data.mjs`) and answers the same `/api/*`
 * requests the pages make. Timestamps are moved forward so the activity always
 * looks recent, and "Run assurance" plays back a simulated run that finishes
 * with the invoice's existing result.
 */

import { withBase } from "./staticMode";

interface StaticSnapshot {
  schema_version: number;
  captured_at: string;
  /** API responses keyed by normalized request path, e.g. `/api/invoices/INV-1`. */
  responses: Record<string, unknown>;
  /** Invoice ids with a PDF under `static-data/pdfs/`. */
  pdfs: string[];
}

type JsonObject = Record<string, unknown>;

interface AgentRun extends JsonObject {
  id: string;
  case_id: string | null;
  name: string;
  status: string;
  created_at: string;
  updated_at: string;
  metadata: JsonObject;
}

interface InvoiceDecision extends JsonObject {
  invoice_id: string;
  invoice_number: string;
  has_agent_decision?: boolean;
}

interface SimulatedRun {
  id: string;
  invoiceId: string;
  invoiceNumber: string;
  startedAt: number;
}

const STATIC_USER = { email: "analyst@caldova.com", name: "Caldova Analyst", source: "static" };
const EMPTY_CONFIG = { foundry_endpoint: "", foundry_project_url: "", app_insights_resource_id: "" };

const SIM_STORAGE_KEY = "waypoint.static.simulated-runs.v1";
const SIM_RUN_MS = 30_000;
const SIM_LANES_START_MS = 2_000;
const SIM_FINALIZE_MS = 4_000;
const MAX_BATCH_INVOICES = 25;
const DAY_MS = 86_400_000;

const TERMINAL_STATUSES = new Set([
  "completed",
  "complete",
  "succeeded",
  "success",
  "partial",
  "failed",
  "error",
  "cancelled",
  "canceled",
]);
const SUCCESS_STATUSES = new Set(["completed", "complete", "succeeded", "success", "partial"]);
const LANE_IDENTITY_KEYS = ["agent", "plane", "expert", "agent_name", "name", "label", "iq", "tool"];
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

let snapshotPromise: Promise<StaticSnapshot> | null = null;

export async function staticFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const request = input instanceof Request ? input : null;
  const url = new URL(request ? request.url : String(input), window.location.origin);
  const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
  const path = decodePath(stripBase(url.pathname));

  if (!path.startsWith("/api/")) {
    return fetch(input, init);
  }

  const snapshot = await loadSnapshot();
  await delay(60 + Math.random() * 140);

  if (method === "GET") {
    return handleGet(snapshot, path, url.searchParams);
  }
  if (method === "POST") {
    if (path === "/api/invoices/assurance-runs/batch") {
      return triggerBatch(snapshot, await readJson(init?.body ?? (request ? await request.text() : null)));
    }
    const single = /^\/api\/invoices\/([^/]+)\/assurance-runs$/.exec(path);
    if (single) {
      return triggerSingle(snapshot, single[1]);
    }
  }
  return json({ detail: "Not Found" }, 404, "Not Found");
}

async function handleGet(snapshot: StaticSnapshot, path: string, params: URLSearchParams) {
  if (path === "/api/user/me") {
    return json(STATIC_USER);
  }
  if (path === "/api/config") {
    return json(EMPTY_CONFIG);
  }
  if (path === "/api/runs") {
    const caseId = params.get("case_id");
    const runs = allRuns(snapshot).filter((run) => !caseId || run.case_id === caseId);
    return json(runs);
  }
  if (path === "/api/invoice-decisions") {
    return json(invoiceDecisions(snapshot));
  }
  const pdf = /^\/api\/invoices\/([^/]+)\/pdf$/.exec(path);
  if (pdf) {
    const invoiceId = pdf[1];
    if (!snapshot.pdfs.includes(invoiceId)) {
      return json({ detail: `Invoice '${invoiceId}' has no PDF document` }, 404, "Not Found");
    }
    return fetch(withBase(`/static-data/pdfs/${encodeURIComponent(invoiceId)}.pdf`));
  }

  const body = snapshot.responses[responseKey(path, params)];
  if (body === undefined) {
    return json({ detail: "Not Found" }, 404, "Not Found");
  }
  return json(body);
}

/** Same normalization the snapshot script uses for its keys. */
export function responseKey(path: string, params: URLSearchParams): string {
  const entries = [...params.entries()]
    .filter(([key]) => key !== "include_content")
    .sort(([a], [b]) => a.localeCompare(b));
  const query = new URLSearchParams(entries).toString();
  return query ? `${path}?${query}` : path;
}

// ---------------------------------------------------------------------------
// Snapshot loading and time shifting
// ---------------------------------------------------------------------------

function loadSnapshot(): Promise<StaticSnapshot> {
  if (!snapshotPromise) {
    snapshotPromise = fetch(withBase("/static-data/snapshot.json"))
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Static data is missing (${response.status}).`);
        }
        return response.json() as Promise<StaticSnapshot>;
      })
      .then(rebaseSnapshot)
      .catch((error: unknown) => {
        snapshotPromise = null;
        throw error;
      });
  }
  return snapshotPromise;
}

/**
 * Move every timestamp forward by whole days so the newest activity lands on
 * "today" (or yesterday, if it happened later in the day than now).
 */
function rebaseSnapshot(snapshot: StaticSnapshot): StaticSnapshot {
  const runs = (snapshot.responses["/api/runs"] as AgentRun[] | undefined) ?? [];
  const latest = runs.reduce(
    (max, run) => Math.max(max, Date.parse(run.updated_at) || 0, Date.parse(run.created_at) || 0),
    0,
  );
  const anchor = latest || Date.parse(snapshot.captured_at) || Date.now();
  const shiftMs = Math.max(0, Math.floor((Date.now() - anchor) / DAY_MS)) * DAY_MS;
  if (shiftMs === 0) {
    return snapshot;
  }
  return { ...snapshot, responses: shiftTimestamps(snapshot.responses, shiftMs) as JsonObject };
}

function shiftTimestamps(value: unknown, shiftMs: number): unknown {
  if (typeof value === "string") {
    if (!ISO_DATETIME.test(value)) {
      return value;
    }
    const time = Date.parse(value);
    return Number.isFinite(time) ? new Date(time + shiftMs).toISOString() : value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => shiftTimestamps(item, shiftMs));
  }
  if (value && typeof value === "object") {
    const result: JsonObject = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = shiftTimestamps(item, shiftMs);
    }
    return result;
  }
  return value;
}

// ---------------------------------------------------------------------------
// Runs and decisions, including simulated runs
// ---------------------------------------------------------------------------

function snapshotRuns(snapshot: StaticSnapshot): AgentRun[] {
  return (snapshot.responses["/api/runs"] as AgentRun[] | undefined) ?? [];
}

function snapshotDecisions(snapshot: StaticSnapshot): InvoiceDecision[] {
  return (snapshot.responses["/api/invoice-decisions"] as InvoiceDecision[] | undefined) ?? [];
}

function allRuns(snapshot: StaticSnapshot): AgentRun[] {
  const now = Date.now();
  const simulated = readSimulatedRuns().map((sim) => materialize(snapshot, sim, now));
  return [...simulated, ...snapshotRuns(snapshot)].sort(
    (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
  );
}

function invoiceDecisions(snapshot: StaticSnapshot): InvoiceDecision[] {
  const now = Date.now();
  const sims = readSimulatedRuns();
  return snapshotDecisions(snapshot).map((decision) => {
    const mine = sims.filter((sim) => sim.invoiceId === decision.invoice_id);
    if (mine.length === 0) {
      return decision;
    }
    const active = mine.some((sim) => now - sim.startedAt < SIM_RUN_MS);
    const finishedAt = Math.max(
      ...mine.map((sim) => sim.startedAt + SIM_RUN_MS).filter((time) => time <= now),
      0,
    );
    const next: InvoiceDecision = { ...decision, has_active_run: active };
    if (finishedAt && decision.has_agent_decision) {
      next.agent_run_at = new Date(finishedAt).toISOString();
    }
    if (active && !decision.has_agent_decision) {
      next.decision = "Pending";
      next.status = "pending";
      next.reasoning = "Assurance review is in progress.";
    }
    return next;
  });
}

/** The invoice's newest finished real run; its result is what a simulated run ends with. */
function templateRun(snapshot: StaticSnapshot, invoiceId: string): AgentRun | null {
  const forInvoice = snapshotRuns(snapshot)
    .filter((run) => run.metadata?.invoice_id === invoiceId || run.name === `assurance:${invoiceId}`)
    .filter((run) => TERMINAL_STATUSES.has(run.status?.toLowerCase()))
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  return (
    forInvoice.find((run) => SUCCESS_STATUSES.has(run.status.toLowerCase())) ?? forInvoice[0] ?? null
  );
}

function materialize(snapshot: StaticSnapshot, sim: SimulatedRun, now: number): AgentRun {
  const template = templateRun(snapshot, sim.invoiceId);
  const elapsed = Math.max(0, now - sim.startedAt);
  const startedIso = new Date(sim.startedAt).toISOString();
  const baseMetadata: JsonObject = {
    invoice_id: sim.invoiceId,
    invoice_number: sim.invoiceNumber,
    trigger: "waypoint-user",
  };

  if (elapsed >= SIM_RUN_MS) {
    const finishedIso = new Date(sim.startedAt + SIM_RUN_MS).toISOString();
    if (template) {
      return {
        ...template,
        id: sim.id,
        created_by: STATIC_USER.email,
        created_at: startedIso,
        updated_at: finishedIso,
        idempotency_key: null,
        metadata: { ...template.metadata, trigger: "waypoint-user" },
      };
    }
    return {
      ...emptyRun(sim, startedIso, finishedIso),
      status: "completed",
      summary: `Invoice assurance completed for ${sim.invoiceNumber}.`,
      metadata: baseMetadata,
    };
  }

  const lanes = Array.isArray(template?.metadata?.fanout)
    ? (template.metadata.fanout as JsonObject[])
    : [];
  const laneWindow = SIM_RUN_MS - SIM_LANES_START_MS - SIM_FINALIZE_MS;
  const laneDoneAt = (index: number) =>
    SIM_LANES_START_MS + ((index + 1) * laneWindow) / Math.max(lanes.length, 1);
  const lastStep = lanes.reduce(
    (latest, _lane, index) => (elapsed >= laneDoneAt(index) ? laneDoneAt(index) : latest),
    0,
  );
  const fanout = lanes.map((lane, index) => (elapsed >= laneDoneAt(index) ? lane : pendingLane(lane)));

  return {
    ...emptyRun(sim, startedIso, new Date(sim.startedAt + lastStep).toISOString()),
    status: "running",
    foundry_agent_name: (template?.foundry_agent_name as string | null | undefined) ?? null,
    summary: "Invoice assurance is in_progress.",
    metadata: {
      ...baseMetadata,
      foundry_start_status: "in_progress",
      ...(template?.metadata?.experts_consulted !== undefined
        ? { experts_consulted: template.metadata.experts_consulted }
        : {}),
      ...(lanes.length ? { fanout } : {}),
    },
  };
}

function emptyRun(sim: SimulatedRun, createdAt: string, updatedAt: string): AgentRun {
  return {
    id: sim.id,
    case_id: null,
    name: `assurance:${sim.invoiceId}`,
    status: "running",
    foundry_agent_name: null,
    foundry_conversation_id: null,
    foundry_response_id: null,
    app_insights_operation_id: null,
    summary: "",
    created_by: STATIC_USER.email,
    created_at: createdAt,
    updated_at: updatedAt,
    metadata: {},
    idempotency_key: null,
  };
}

/** A lane that hasn't reported yet: same identity, empty findings. */
function pendingLane(lane: JsonObject): JsonObject {
  const pending: JsonObject = {};
  for (const [key, value] of Object.entries(lane)) {
    if (LANE_IDENTITY_KEYS.includes(key)) {
      pending[key] = value;
    } else if (Array.isArray(value)) {
      pending[key] = [];
    } else if (typeof value === "string") {
      pending[key] = "";
    }
  }
  return { ...pending, summary: "", evidence: [] };
}

function startOrReuse(snapshot: StaticSnapshot, decision: InvoiceDecision) {
  const now = Date.now();
  const sims = readSimulatedRuns();
  const active = sims.find(
    (sim) => sim.invoiceId === decision.invoice_id && now - sim.startedAt < SIM_RUN_MS,
  );
  if (active) {
    return { run: materialize(snapshot, active, now), reused: true };
  }
  const sim: SimulatedRun = {
    id: newRunId(),
    invoiceId: decision.invoice_id,
    invoiceNumber: decision.invoice_number,
    startedAt: now,
  };
  writeSimulatedRuns([...sims, sim]);
  return { run: materialize(snapshot, sim, now), reused: false };
}

function triggerSingle(snapshot: StaticSnapshot, invoiceId: string) {
  const decision = snapshotDecisions(snapshot).find((item) => item.invoice_id === invoiceId);
  if (!decision) {
    return json({ detail: `Invoice '${invoiceId}' not found.` }, 404, "Not Found");
  }
  const { run, reused } = startOrReuse(snapshot, decision);
  return json({ run, reused, foundry_response_id: null }, 202, "Accepted");
}

function triggerBatch(snapshot: StaticSnapshot, body: unknown) {
  const raw = (body as { invoice_ids?: unknown } | null)?.invoice_ids;
  const ids = Array.isArray(raw)
    ? [...new Set(raw.map((id) => String(id).trim()).filter(Boolean))]
    : [];
  if (ids.length === 0 || ids.length > MAX_BATCH_INVOICES) {
    return json({ detail: "Invalid batch request." }, 422, "Unprocessable Entity");
  }

  const decisions = snapshotDecisions(snapshot);
  const items = ids.map((invoiceId) => {
    const decision = decisions.find((item) => item.invoice_id === invoiceId);
    if (!decision) {
      return { invoice_id: invoiceId, invoice_number: null, outcome: "not_found", run_id: null, run_status: null };
    }
    const { run, reused } = startOrReuse(snapshot, decision);
    return {
      invoice_id: invoiceId,
      invoice_number: decision.invoice_number,
      outcome: reused ? "reused" : "accepted",
      run_id: run.id,
      run_status: run.status,
      foundry_response_id: null,
    };
  });
  const count = (outcome: string) => items.filter((item) => item.outcome === outcome).length;
  return json(
    {
      items,
      total: items.length,
      accepted: count("accepted"),
      reused: count("reused"),
      not_found: count("not_found"),
      start_failed: 0,
    },
    202,
    "Accepted",
  );
}

function readSimulatedRuns(): SimulatedRun[] {
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(SIM_STORAGE_KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as SimulatedRun[]) : [];
  } catch {
    return [];
  }
}

function writeSimulatedRuns(runs: SimulatedRun[]) {
  try {
    window.sessionStorage.setItem(SIM_STORAGE_KEY, JSON.stringify(runs));
  } catch {
    // Storage full or blocked: the run just won't survive a reload.
  }
}

function newRunId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function stripBase(pathname: string): string {
  const base = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");
  return base && pathname.startsWith(`${base}/`) ? pathname.slice(base.length) : pathname;
}

function decodePath(pathname: string): string {
  return pathname
    .split("/")
    .map((segment) => {
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    })
    .join("/");
}

async function readJson(body: BodyInit | null | undefined): Promise<unknown> {
  if (typeof body !== "string") {
    return null;
  }
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
}

function json(body: unknown, status = 200, statusText = "OK"): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
    headers: { "content-type": "application/json" },
  });
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
