import type { MetaFunction } from "react-router";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import {
  HiCheckCircle,
  HiChevronRight,
  HiDocumentText,
  HiDownload,
  HiExternalLink,
  HiRefresh,
  HiSearch,
  HiSparkles,
  HiX,
} from "react-icons/hi";
import { authFetch } from "../../lib/msalAuth";
import { AppHeader } from "../components/AppHeader";
import { useAuth } from "../components/AuthProvider";
import { RequireAuth } from "../components/RequireAuth";

export const meta: MetaFunction = () => [
  { title: "Invoices - Waypoint" },
  {
    name: "description",
    content: "Waypoint invoice decisions and agent context",
  },
];

interface InvoiceDecision {
  invoice_id: string;
  invoice_number: string;
  supplier_id: string;
  supplier_name: string;
  scenario_id: string | null;
  scenario_name: string | null;
  decision: string;
  category: string;
  reasoning: string;
  severity: string;
  status: string;
  currency: string;
  overpayment_amount: string;
  overpayment_display: string;
  source: string;
  evidence_count: number;
  contract_document_ids: string[];
  policy_ids: string[];
  basis_summary: string | null;
  basis_types: Array<"contract" | "policy">;
  html_uri: string | null;
  pdf_uri: string | null;
  has_agent_decision: boolean;
  has_active_run: boolean;
  agent_decision: string | null;
  agent_run_count: number;
  agent_run_index: number | null;
  agent_run_at: string | null;
  agent_case_id: string | null;
  confidence: string | null;
  confidence_calibrated: boolean;
  agent_title: string | null;
  agent_source_count: number;
  agent_plane_count: number;
  metadata: {
    invoice_status?: string;
    line_count?: number;
  };
}

interface InvoiceDetail extends InvoiceDecisionBase {
  supplier: { id: string; name: string } | null;
  scenario: { id: string; name: string } | null;
  lines: InvoiceLine[];
  findings: Finding[];
  evidence: EvidenceReference[];
}

interface InvoiceDecisionBase {
  id: string;
  supplier_id: string;
  scenario_id: string | null;
  invoice_number: string;
  status: string;
  currency: string;
  total_amount: string;
  html_uri: string | null;
  pdf_uri: string | null;
}

interface InvoiceLine {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
  sku: string | null;
  purchase_order: string | null;
}

interface Finding {
  id: string;
  category: string;
  severity: string;
  status: string;
  summary: string;
  overpayment_amount: string;
  contract_document_ids: string[];
  policy_ids: string[];
  basis_summary: string | null;
  evidence_ids: string[];
}

interface EvidenceReference {
  id: string;
  title: string;
  evidence_type: string;
  uri: string | null;
  excerpt: string | null;
}

interface FanoutEvidenceItem {
  claim?: string;
  source_ref?: string;
  classification?: string;
  confidence?: number;
}

interface FanoutLane {
  agent?: string;
  plane?: string;
  summary?: string;
  evidence?: FanoutEvidenceItem[];
}

interface AssuranceCase {
  id: string;
  invoice_id: string;
  title: string;
  summary: string;
  status: string;
  created_at: string;
}

interface CaseRecommendation {
  id: string;
  case_id: string;
  decision: string;
  reasoning: string;
  confidence: string;
  money_at_risk: string;
  evidence_ids: string[];
  proposed_next_actions: string[];
  created_by: string;
  created_at: string;
  metadata: {
    expert_evidence?: FanoutLane[];
    waypoint_run_id?: string;
    confidence_calibrated?: boolean;
  };
}

interface CaseDraft {
  id: string;
  case_id: string;
  draft_type: string;
  title: string;
  body: string;
  source_recommendation_id: string | null;
  created_by: string;
  created_at: string;
}

interface AgentRunRef {
  id: string;
  case_id: string | null;
  status: string;
  summary: string;
  created_at: string;
  metadata: { decision?: string; fanout?: FanoutLane[] };
}

interface AssuranceRunTriggerResult {
  reused: boolean;
  run: {
    id: string;
    status: string;
  };
  foundry_response_id: string | null;
}

type BatchAssuranceOutcome = "accepted" | "reused" | "not_found" | "start_failed";

interface BatchAssuranceItemResult {
  invoice_id: string;
  invoice_number: string | null;
  outcome: BatchAssuranceOutcome;
  run_id: string | null;
  run_status: string | null;
  foundry_response_id: string | null;
}

interface BatchAssuranceResult {
  items: BatchAssuranceItemResult[];
  total: number;
  accepted: number;
  reused: number;
  not_found: number;
  start_failed: number;
}

const MAX_BATCH_ASSURANCE_INVOICES = 25;
const BATCH_ASSURANCE_CONCURRENCY = 4;

interface AgentCaseEntry {
  case: AssuranceCase;
  recommendation: CaseRecommendation | null;
  drafts: CaseDraft[];
  fanout: FanoutLane[];
  run: AgentRunRef | null;
}

interface AgentContext {
  entries: AgentCaseEntry[];
}

interface AssuranceCaseView {
  case: AssuranceCase;
  latest_recommendation: CaseRecommendation | null;
  recommendations: CaseRecommendation[];
  drafts: CaseDraft[];
  evidence: EvidenceReference[];
  sources: FanoutEvidenceItem[];
}

interface InvoiceAssurance {
  invoice_id: string;
  has_agent_decision: boolean;
  cases: AssuranceCaseView[];
}


interface ContractDocument {
  id: string;
  supplier_id: string;
  title: string;
  document_type: string;
  effective_date: string | null;
  uri: string | null;
  metadata: Record<string, unknown>;
  text?: string | null;
  content_source?: "onelake" | "uri-only";
}

interface PolicyDocument {
  id: string;
  name: string;
  description: string;
  severity: string;
  metadata: Record<string, unknown>;
  text?: string | null;
  content_source?: "onelake" | "uri-only";
}

type DocumentPreview =
  | { kind: "invoice-pdf"; title: string; uri: string; invoiceId: string }
  | { kind: "contract"; document: ContractDocument }
  | { kind: "policy"; policy: PolicyDocument };

async function tracedFetch(
  name: string,
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const { traced } = await import("../../lib/telemetry");
  return traced(name, () => authFetch(input, init, { requireToken: true }));
}

type SortKey = "recent" | "overpayment" | "confidence" | "supplier";

const SORT_OPTIONS: Array<{ key: SortKey; label: string }> = [
  { key: "recent", label: "Most recent" },
  { key: "overpayment", label: "Highest overpayment" },
  { key: "confidence", label: "Lowest confidence" },
  { key: "supplier", label: "Supplier A–Z" },
];

function overpaymentAmount(row: InvoiceDecision): number {
  const amount = Number(row.overpayment_amount);
  return Number.isFinite(amount) ? amount : 0;
}

// Unknown confidence sorts last when ranking lowest-first.
function confidenceValue(row: InvoiceDecision): number {
  const score = Number(row.confidence);
  return Number.isFinite(score) ? score : Number.POSITIVE_INFINITY;
}

function decisionColor(decision: string): string {
  // Stoplight ramp for adjudicated outcomes; Review is intentionally off the
  // ramp (neutral blue) because it is a workflow state, not a severity level.
  switch (decision) {
    case "Escalate":
      return "#dc2626"; // red — stop
    case "Recover":
      return "#ea580c"; // orange — caution
    case "Approve":
      return "#16a34a"; // green — go
    case "Review":
      return "#2563eb"; // blue — pending human adjudication
    case "Closed":
    case "Not run":
      return "#64748b"; // slate
    default:
      return "#d97706"; // amber — in-flight/pending
  }
}

function severityColor(severity: string): string {
  const value = severity.toLowerCase();
  if (value.includes("critical") || value.includes("high")) {
    return "#e11d48";
  }
  if (value.includes("medium") || value.includes("moderate")) {
    return "#d97706";
  }
  if (value.includes("low")) {
    return "#059669";
  }
  return "#64748b";
}

// Canonical labels for the known proposed-action ids (mirrors the backend
// ActionType.name values). Falls back to humanizing the raw id so any future
// action still renders as prose instead of a snake_case token.
const ACTION_LABELS: Record<string, string> = {
  recommend_recover: "Recommend recovery",
  draft_supplier_dispute: "Draft supplier dispute",
  request_legal_escalation: "Request legal escalation",
  request_quality_review: "Request quality review",
};

function formatActionLabel(action: string): string {
  return (
    ACTION_LABELS[action] ??
    action.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}

// Evidence source_ref values arrive with a trailing knowledge-base chunk anchor
// in either a bracketed ("Invoice Reconciliation Policy [ref_id:2]") or an
// unbracketed, separator-prefixed form ("capacity-agreement §6 Invoice
// evidence; ref_id:0"). The anchor is an internal retrieval ordinal, not a
// citable reference, so strip both forms and keep the document title. Falls
// back to the raw value if stripping leaves nothing.
function cleanSourceRef(ref: string): string {
  const cleaned = ref.replace(/\s*;?\s*\[?ref_id:\s*\d+\]?/gi, "").trim();
  return cleaned.length > 0 ? cleaned : ref;
}

export default function Invoices() {
  const auth = useAuth();
  const [decisions, setDecisions] = useState<InvoiceDecision[]>([]);
  const [selectedDecision, setSelectedDecision] = useState<InvoiceDecision | null>(null);
  const [invoiceDetail, setInvoiceDetail] = useState<InvoiceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [agentContext, setAgentContext] = useState<AgentContext | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);
  const [triggeringInvoiceId, setTriggeringInvoiceId] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [selectedInvoiceIds, setSelectedInvoiceIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [batchConfirmOpen, setBatchConfirmOpen] = useState(false);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [batchResult, setBatchResult] = useState<BatchAssuranceResult | null>(null);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const deepLinkAppliedRef = useRef(false);

  const [decisionFilter, setDecisionFilter] = useState<string>("all");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [supplierFilter, setSupplierFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");

  const fetchDecisions = useCallback(async () => {
    if (auth.status !== "authenticated") {
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await tracedFetch("fetchInvoiceDecisions", "/api/invoice-decisions");
      if (!response.ok) {
        throw new Error(`Failed to fetch invoice decisions: ${response.statusText}`);
      }
      setDecisions(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch invoice decisions");
    } finally {
      setLoading(false);
    }
  }, [auth.status]);

  useEffect(() => {
    if (auth.status === "authenticated") {
      void fetchDecisions();
    }
  }, [auth.status, fetchDecisions]);

  // Deep-link support: honor ?invoice=<invoice_id|invoice_number> (or
  // ?case=<case_id>) by preselecting the matching decision once decisions have
  // loaded. This lets the assurance-analyst Adaptive Card link a Finance
  // approver straight to one invoice's context. Applied once per mount so the
  // user can freely close the panel afterwards.
  useEffect(() => {
    if (deepLinkAppliedRef.current || loading || decisions.length === 0) {
      return;
    }
    const invoiceParam = searchParams.get("invoice");
    const caseParam = searchParams.get("case");
    if (!invoiceParam && !caseParam) {
      return;
    }

    if (invoiceParam) {
      const match = decisions.find(
        (decision) =>
          decision.invoice_id === invoiceParam || decision.invoice_number === invoiceParam,
      );
      if (match) {
        deepLinkAppliedRef.current = true;
        setSelectedDecision(match);
      }
      return;
    }

    // ?case=<case_id> -> resolve the case's invoice, then preselect it.
    let cancelled = false;
    void (async () => {
      try {
        const response = await tracedFetch(
          "resolveCaseDeepLink",
          `/api/cases/${encodeURIComponent(caseParam as string)}`,
        );
        if (!response.ok || cancelled) {
          return;
        }
        const assuranceCase = (await response.json()) as { invoice_id?: string };
        const match = decisions.find(
          (decision) => decision.invoice_id === assuranceCase.invoice_id,
        );
        if (match && !cancelled) {
          deepLinkAppliedRef.current = true;
          setSelectedDecision(match);
        }
      } catch {
        // Deep-link is best-effort; fall back to the full list silently.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [auth.status, loading, decisions, searchParams]);

  useEffect(() => {
    if (!selectedDecision) {
      setInvoiceDetail(null);
      return;
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectedDecision(null);
      }
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [selectedDecision]);

  const openDocumentPreview = useCallback(
    async (type: "contract" | "policy", id: string) => {
      if (auth.status !== "authenticated") {
        return;
      }

      setPreviewLoading(true);
      try {
        const endpoint =
          type === "contract"
            ? `/api/contract-documents/${id}?include_content=true`
            : `/api/policies/${id}?include_content=true`;
        const response = await tracedFetch("fetchDocumentPreview", endpoint);
        if (!response.ok) {
          throw new Error(`Failed to fetch ${type} preview: ${response.statusText}`);
        }
        if (type === "contract") {
          setPreview({ kind: "contract", document: await response.json() });
        } else {
          setPreview({ kind: "policy", policy: await response.json() });
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to fetch ${type} preview`);
      } finally {
        setPreviewLoading(false);
      }
    },
    [auth.status],
  );

  useEffect(() => {
    if (auth.status !== "authenticated" || !selectedDecision) {
      return;
    }

    let cancelled = false;
    setDetailLoading(true);
    tracedFetch("fetchInvoiceDetail", `/api/invoices/${selectedDecision.invoice_id}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to fetch invoice detail: ${response.statusText}`);
        }
        return response.json();
      })
      .then((detail: InvoiceDetail) => {
        if (!cancelled) {
          setInvoiceDetail(detail);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch invoice detail");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setDetailLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [auth.status, selectedDecision]);

  const triggerAssurance = useCallback(
    async (decision: InvoiceDecision) => {
      setTriggeringInvoiceId(decision.invoice_id);
      setTriggerError(null);
      try {
        const response = await tracedFetch(
          "triggerInvoiceAssurance",
          `/api/invoices/${encodeURIComponent(decision.invoice_id)}/assurance-runs`,
          { method: "POST" },
        );
        if (!response.ok) {
          const body = (await response.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(body?.detail || `Unable to start assurance (${response.status}).`);
        }
        const result = (await response.json()) as AssuranceRunTriggerResult;
        await fetchDecisions();
        const params = new URLSearchParams({
          invoice: decision.invoice_number || decision.invoice_id,
          run: result.run.id,
        });
        if (result.reused) {
          params.set("reused", "true");
        }
        navigate(`/activity?${params.toString()}`);
      } catch (err) {
        setTriggerError(err instanceof Error ? err.message : "Unable to start assurance.");
      } finally {
        setTriggeringInvoiceId(null);
      }
    },
    [fetchDecisions, navigate],
  );

  useEffect(() => {
    if (auth.status !== "authenticated" || !selectedDecision) {
      setAgentContext(null);
      return;
    }

    let cancelled = false;
    const invoiceId = selectedDecision.invoice_id;
    setAgentLoading(true);
    setAgentContext(null);

    (async () => {
      const fetchLatestRun = async (caseId: string): Promise<AgentRunRef | null> => {
        const runsResp = await tracedFetch(
          "fetchCaseRuns",
          `/api/runs?case_id=${encodeURIComponent(caseId)}`,
        );
        if (!runsResp.ok) {
          return null;
        }
        const runs: AgentRunRef[] = await runsResp.json();
        runs.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        return runs[0] ?? null;
      };

      const byCreatedAtDesc = (a: { created_at: string }, b: { created_at: string }) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime();

      const entryFanout = (
        recommendation: CaseRecommendation | null,
        run: AgentRunRef | null,
      ): FanoutLane[] =>
        (recommendation?.metadata?.expert_evidence ?? run?.metadata?.fanout ?? []) as FanoutLane[];

      // Legacy path: used until the consolidated /assurance endpoint is deployed.
      // Loads every case (not just the newest) so the drawer switcher still works here.
      const loadFromCasesAndRuns = async (): Promise<AgentContext> => {
        const casesResp = await tracedFetch(
          "fetchInvoiceCases",
          `/api/cases?invoice_id=${encodeURIComponent(invoiceId)}`,
        );
        if (!casesResp.ok) {
          throw new Error(`Failed to fetch cases: ${casesResp.statusText}`);
        }
        const cases: AssuranceCase[] = await casesResp.json();
        cases.sort(byCreatedAtDesc);

        const entries = await Promise.all(
          cases.map(async (agentCase): Promise<AgentCaseEntry> => {
            const [recsResp, draftsResp, run] = await Promise.all([
              tracedFetch(
                "fetchCaseRecommendations",
                `/api/cases/${encodeURIComponent(agentCase.id)}/recommendations`,
              ),
              tracedFetch(
                "fetchCaseDrafts",
                `/api/cases/${encodeURIComponent(agentCase.id)}/drafts`,
              ),
              fetchLatestRun(agentCase.id),
            ]);
            let recommendation: CaseRecommendation | null = null;
            if (recsResp.ok) {
              const recs: CaseRecommendation[] = await recsResp.json();
              recs.sort(byCreatedAtDesc);
              recommendation = recs[0] ?? null;
            }
            const drafts: CaseDraft[] = draftsResp.ok ? await draftsResp.json() : [];
            return { case: agentCase, recommendation, drafts, run, fanout: entryFanout(recommendation, run) };
          }),
        );
        return { entries };
      };

      try {
        const assuranceResp = await tracedFetch(
          "fetchInvoiceAssurance",
          `/api/invoices/${encodeURIComponent(invoiceId)}/assurance`,
        );

        let context: AgentContext;
        if (assuranceResp.ok) {
          const assurance: InvoiceAssurance = await assuranceResp.json();
          const caseViews = [...assurance.cases].sort((a, b) =>
            byCreatedAtDesc(a.case, b.case),
          );
          const runs = await Promise.all(
            caseViews.map((view) => fetchLatestRun(view.case.id)),
          );
          const entries = caseViews.map((view, index): AgentCaseEntry => {
            const recommendation = view.latest_recommendation ?? null;
            const run = runs[index];
            return {
              case: view.case,
              recommendation,
              drafts: view.drafts ?? [],
              run,
              fanout: entryFanout(recommendation, run),
            };
          });
          context = { entries };
        } else {
          // The /assurance endpoint isn't available yet (e.g. api not redeployed):
          // fall back to the existing cases + runs path so the card never blanks.
          context = await loadFromCasesAndRuns();
        }

        if (!cancelled) {
          setAgentContext(context);
        }
      } catch {
        if (!cancelled) {
          setAgentContext(null);
        }
      } finally {
        if (!cancelled) {
          setAgentLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [auth.status, selectedDecision]);

  const decisionOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of decisions) {
      if (row.decision) {
        set.add(row.decision);
      }
    }
    return Array.from(set).sort();
  }, [decisions]);

  const severityOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of decisions) {
      if (row.severity) {
        set.add(row.severity);
      }
    }
    return Array.from(set).sort();
  }, [decisions]);

  const supplierOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of decisions) {
      if (row.supplier_name) {
        set.add(row.supplier_name);
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [decisions]);

  const categoryOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of decisions) {
      if (row.category) {
        set.add(row.category);
      }
    }
    return Array.from(set).sort((a, b) =>
      formatCategory(a).localeCompare(formatCategory(b)),
    );
  }, [decisions]);

  // Narrow by the active filters, then sort. "recent" preserves the API order
  // (already newest-first) so rows without an agent run never get scrambled.
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = decisions.filter((row) => {
      if (decisionFilter !== "all" && row.decision !== decisionFilter) {
        return false;
      }
      if (severityFilter !== "all" && row.severity !== severityFilter) {
        return false;
      }
      if (supplierFilter !== "all" && row.supplier_name !== supplierFilter) {
        return false;
      }
      if (categoryFilter !== "all" && row.category !== categoryFilter) {
        return false;
      }
      if (needle) {
        const haystack =
          `${row.invoice_number} ${row.supplier_name} ${row.agent_title ?? ""} ${row.reasoning}`.toLowerCase();
        if (!haystack.includes(needle)) {
          return false;
        }
      }
      return true;
    });
    const sorted = [...filtered];
    if (sort === "overpayment") {
      sorted.sort((a, b) => overpaymentAmount(b) - overpaymentAmount(a));
    } else if (sort === "confidence") {
      sorted.sort((a, b) => confidenceValue(a) - confidenceValue(b));
    } else if (sort === "supplier") {
      sorted.sort((a, b) => a.supplier_name.localeCompare(b.supplier_name));
    }
    return sorted;
  }, [decisions, decisionFilter, severityFilter, supplierFilter, categoryFilter, query, sort]);

  const totalOverpayment = useMemo(
    () => visible.reduce((sum, row) => sum + overpaymentAmount(row), 0),
    [visible],
  );
  const escalationCount = useMemo(
    () => visible.filter((row) => row.decision === "Escalate").length,
    [visible],
  );
  // Keep in-flight and unreviewed invoices out of decision metrics while retaining them in the
  // complete selectable work queue.
  const pendingCount = useMemo(
    () => visible.filter((row) => row.has_active_run && !row.has_agent_decision).length,
    [visible],
  );
  const reviewedCount = useMemo(
    () => visible.filter((row) => row.has_agent_decision).length,
    [visible],
  );
  const unreviewedCount = visible.length - reviewedCount - pendingCount;
  const selectedRows = useMemo(
    () => decisions.filter((row) => selectedInvoiceIds.has(row.invoice_id)),
    [decisions, selectedInvoiceIds],
  );
  const allVisibleSelected =
    visible.length > 0 && visible.every((row) => selectedInvoiceIds.has(row.invoice_id));
  const someVisibleSelected = visible.some((row) => selectedInvoiceIds.has(row.invoice_id));
  const batchSelectionTooLarge = selectedRows.length > MAX_BATCH_ASSURANCE_INVOICES;

  const filtersActive =
    decisionFilter !== "all" ||
    severityFilter !== "all" ||
    supplierFilter !== "all" ||
    categoryFilter !== "all" ||
    query.trim() !== "";

  const resetFilters = useCallback(() => {
    setDecisionFilter("all");
    setSeverityFilter("all");
    setSupplierFilter("all");
    setCategoryFilter("all");
    setQuery("");
  }, []);

  // Pending (in-flight) rows jump to the live Activity feed for that invoice; decided rows open
  // the decision drawer in place.
  const openRow = useCallback(
    (row: InvoiceDecision) => {
      if (row.has_active_run && !row.has_agent_decision) {
        navigate(`/activity?invoice=${encodeURIComponent(row.invoice_number)}`);
        return;
      }
      setSelectedDecision(row);
    },
    [navigate],
  );

  const toggleInvoiceSelection = useCallback((invoiceId: string) => {
    setSelectedInvoiceIds((current) => {
      const next = new Set(current);
      if (next.has(invoiceId)) {
        next.delete(invoiceId);
      } else {
        next.add(invoiceId);
      }
      return next;
    });
    setBatchError(null);
  }, []);

  const toggleVisibleSelection = useCallback(() => {
    setSelectedInvoiceIds((current) => {
      const next = new Set(current);
      if (visible.every((row) => next.has(row.invoice_id))) {
        for (const row of visible) {
          next.delete(row.invoice_id);
        }
      } else {
        for (const row of visible) {
          next.add(row.invoice_id);
        }
      }
      return next;
    });
    setBatchError(null);
  }, [visible]);

  const triggerBatchAssurance = useCallback(async () => {
    const invoiceIds = selectedRows.map((row) => row.invoice_id);
    if (
      invoiceIds.length === 0 ||
      invoiceIds.length > MAX_BATCH_ASSURANCE_INVOICES
    ) {
      return;
    }

    setBatchLoading(true);
    setBatchError(null);
    try {
      const response = await tracedFetch(
        "triggerBatchInvoiceAssurance",
        "/api/invoices/assurance-runs/batch",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ invoice_ids: invoiceIds }),
        },
      );
      if (!response.ok) {
        throw new Error(`Unable to start batch assurance (${response.status}).`);
      }
      const result = (await response.json()) as BatchAssuranceResult;
      setBatchResult(result);
      setBatchConfirmOpen(false);
      setSelectedInvoiceIds(new Set());
      await fetchDecisions();
    } catch (err) {
      setBatchError(
        err instanceof Error ? err.message : "Unable to start batch assurance.",
      );
    } finally {
      setBatchLoading(false);
    }
  }, [fetchDecisions, selectedRows]);

  const openBatchActivity = useCallback(() => {
    const item = batchResult?.items.find(
      (candidate) =>
        (candidate.outcome === "accepted" || candidate.outcome === "reused") &&
        candidate.run_id,
    );
    if (!item) {
      navigate("/activity");
      return;
    }
    const params = new URLSearchParams({
      invoice: item.invoice_number || item.invoice_id,
      run: item.run_id as string,
    });
    navigate(`/activity?${params.toString()}`);
  }, [batchResult, navigate]);

  return (
    <RequireAuth>
      <div className="flex h-screen overflow-hidden bg-slate-50 text-slate-950">
        <div className="flex min-h-0 w-full flex-col">
          <AppHeader />

          <div className="relative flex min-h-0 w-full flex-1 flex-col">
          <main
            id="main-content"
            className="mx-auto grid min-h-0 w-full max-w-[1500px] flex-1 grid-cols-1 gap-2 px-3 py-3 xl:grid-cols-[minmax(0,1fr)_340px] 2xl:px-4"
          >
            <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
              <div className="border-b border-slate-100 px-3 py-2.5">
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">
                      Supplier invoice register
                    </p>
                    <h1 className="mt-1 text-xl font-semibold tracking-tight">
                      Supplier invoices
                    </h1>
                    <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-500">
                      The complete invoice work queue. Select any unreviewed invoices to run
                      assurance, then inspect recorded decisions, evidence, and recovery.
                    </p>
                  </div>
                  <div
                    className={`grid ${pendingCount > 0 ? "grid-cols-4" : "grid-cols-3"} gap-2 text-right text-sm`}
                  >
                    <InfoTile
                      label={filtersActive ? "Shown" : "Invoices"}
                      value={loading ? "..." : String(visible.length)}
                    />
                    {pendingCount > 0 ? (
                      <InfoTile
                        label="Pending"
                        value={loading ? "..." : String(pendingCount)}
                        reviewing
                        onClick={() => navigate("/activity")}
                        title="View live progress in Activity"
                      />
                    ) : null}
                    <InfoTile
                      label="Escalations"
                      value={loading ? "..." : String(escalationCount)}
                      escalation={escalationCount > 0}
                      onClick={
                        escalationCount > 0
                          ? () =>
                              setDecisionFilter((prev) =>
                                prev === "Escalate" ? "all" : "Escalate",
                              )
                          : undefined
                      }
                      title={escalationCount > 0 ? "Filter to escalations" : undefined}
                    />
                    <InfoTile
                      label="Recoverable"
                      value={loading ? "..." : formatMoney(totalOverpayment)}
                      emphasized
                    />
                  </div>
                </div>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
                  <HiSparkles className="h-3.5 w-3.5 text-blue-600" aria-hidden="true" />
                  {loading
                    ? "Loading supplier invoice decisions from the Waypoint API…"
                    : `${formatMoney(totalOverpayment)} recoverable across ${reviewedCount} reviewed invoice${
                        reviewedCount === 1 ? "" : "s"
                      } · ${escalationCount} escalation${
                        escalationCount === 1 ? "" : "s"
                      }${
                        pendingCount > 0
                          ? ` · ${pendingCount} pending`
                          : ""
                      }${
                        unreviewedCount > 0
                          ? ` · ${unreviewedCount} ready to run`
                          : ""
                      }. Human approvals and citations stay attached to every recommendation.`}
                </p>
              </div>

              {error ? (
                <div className="m-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
                  {error}
                </div>
              ) : null}

              {!loading && decisions.length > 0 ? (
                <FilterBar
                  decisions={decisionOptions}
                  decisionFilter={decisionFilter}
                  onDecisionFilter={setDecisionFilter}
                  severities={severityOptions}
                  severityFilter={severityFilter}
                  onSeverityFilter={setSeverityFilter}
                  suppliers={supplierOptions}
                  supplierFilter={supplierFilter}
                  onSupplierFilter={setSupplierFilter}
                  categories={categoryOptions}
                  categoryFilter={categoryFilter}
                  onCategoryFilter={setCategoryFilter}
                  query={query}
                  onQuery={setQuery}
                  sort={sort}
                  onSort={setSort}
                />
              ) : null}

              <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-3 py-2 text-sm text-slate-600">
                <span>
                  {loading
                    ? "Loading…"
                    : filtersActive
                      ? `Showing ${visible.length} of ${decisions.length}`
                      : `${decisions.length} invoice${decisions.length === 1 ? "" : "s"}`}
                </span>
                <div className="flex items-center gap-2">
                  {!loading && visible.length > 0 ? (
                    <button
                      type="button"
                      className="min-h-9 rounded-md border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                      onClick={toggleVisibleSelection}
                    >
                      {allVisibleSelected ? "Clear visible" : "Select visible"}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={fetchDecisions}
                    disabled={loading || auth.status !== "authenticated"}
                  >
                    <HiRefresh className={loading ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
                    Refresh
                  </button>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-auto">
                {loading ? (
                  <p className="px-3 py-6 text-sm text-slate-500">Loading invoices…</p>
                ) : decisions.length === 0 ? (
                  <p className="px-3 py-6 text-sm text-slate-500">
                    No invoices are available.
                  </p>
                ) : visible.length === 0 ? (
                  <NoMatches onReset={resetFilters} />
                ) : (
                  <table className="w-full table-fixed text-left text-[13px]">
                    <colgroup>
                      <col className="w-[44px]" />
                      <col className="w-[170px]" />
                      <col />
                      <col className="w-[100px]" />
                      <col className="w-[140px]" />
                      <col className="w-[110px]" />
                      <col className="w-[110px]" />
                      <col className="w-[120px]" />
                      <col className="w-[120px]" />
                    </colgroup>
                    <thead className="sticky top-0 z-10 bg-slate-50 text-[11px] uppercase tracking-[0.16em] text-slate-500 shadow-[0_1px_0_rgba(0,0,0,0.06)]">
                      <tr>
                        <th className="p-0" scope="col">
                          <label
                            className="inline-flex h-11 w-11 cursor-pointer items-center justify-center"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <SelectionCheckbox
                              checked={allVisibleSelected}
                              mixed={someVisibleSelected && !allVisibleSelected}
                              label={
                                allVisibleSelected
                                  ? "Clear all visible invoices"
                                  : "Select all visible invoices"
                              }
                              onChange={toggleVisibleSelection}
                            />
                          </label>
                        </th>
                        <th className="px-3 py-2" scope="col">Invoice</th>
                        <th className="px-3 py-2" scope="col">Reasoning</th>
                        <th className="px-3 py-2" scope="col">Decision</th>
                        <th className="px-3 py-2" scope="col">Category</th>
                        <th className="px-3 py-2" scope="col">Basis</th>
                        <th className="px-3 py-2" scope="col">Confidence</th>
                        <th className="px-3 py-2" scope="col">
                          <span title="How many independent experts corroborated the decision, and how many evidence sources they cited.">
                            Evidence
                          </span>
                        </th>
                        <th className="px-3 py-2" scope="col">Overpayment</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {visible.map((row) => (
                        <tr
                          key={row.invoice_id}
                          className={[
                            "cursor-pointer hover:bg-slate-50",
                            selectedInvoiceIds.has(row.invoice_id) ? "bg-indigo-50/60" : "",
                            selectedDecision?.invoice_id === row.invoice_id ? "bg-blue-50/70" : "",
                          ].join(" ")}
                          onClick={() => openRow(row)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              openRow(row);
                            }
                          }}
                          tabIndex={0}
                          aria-selected={selectedDecision?.invoice_id === row.invoice_id}
                        >
                          <td className="p-0">
                            <label
                              className="inline-flex h-11 w-11 cursor-pointer items-center justify-center"
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => event.stopPropagation()}
                            >
                              <SelectionCheckbox
                                checked={selectedInvoiceIds.has(row.invoice_id)}
                                label={`Select invoice ${row.invoice_number}`}
                                onChange={() => toggleInvoiceSelection(row.invoice_id)}
                              />
                            </label>
                          </td>
                          <td className="px-3 py-2.5">
                            <span className="block truncate font-semibold">{row.invoice_number}</span>
                            {row.supplier_name ? (
                              <span className="mt-0.5 block truncate text-[11px] text-slate-500">
                                {row.supplier_name}
                              </span>
                            ) : null}
                            {row.has_agent_decision && row.agent_run_count > 0 ? (
                              <span className="mt-0.5 flex flex-col text-[11px] font-normal text-slate-400">
                                {row.agent_run_at ? (
                                  <span className="whitespace-nowrap">
                                    {formatRunDateTime(row.agent_run_at)}
                                  </span>
                                ) : null}
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                  <HiSparkles className="h-3 w-3 shrink-0 text-blue-500" aria-hidden="true" />
                                  Run {row.agent_run_index ?? row.agent_run_count} of{" "}
                                  {row.agent_run_count}
                                </span>
                              </span>
                            ) : null}
                            {row.has_active_run && !row.has_agent_decision ? (
                              <span className="mt-0.5 flex items-center gap-1 whitespace-nowrap text-[11px] font-normal text-indigo-500">
                                <HiSparkles className="h-3 w-3 shrink-0 animate-pulse" aria-hidden="true" />
                                Agents working…
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2.5 text-slate-700">
                            <p className="line-clamp-2 leading-5">
                              {row.agent_title ?? row.reasoning}
                            </p>
                          </td>
                          <td className="px-3 py-2.5 pr-6">
                            <div className="flex items-center gap-1.5">
                              {row.has_active_run && !row.has_agent_decision ? (
                                <button
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    openRow(row);
                                  }}
                                  title="View live progress in Activity"
                                  className="inline-flex items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700 ring-1 ring-inset ring-indigo-200 transition hover:bg-indigo-100 hover:ring-indigo-300"
                                >
                                  <span
                                    className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-indigo-300 border-t-indigo-600"
                                    aria-hidden="true"
                                  />
                                  Pending
                                  <HiExternalLink className="h-3 w-3 text-indigo-400" aria-hidden="true" />
                                </button>
                              ) : (
                                <DecisionPill decision={row.decision} />
                              )}
                            </div>
                          </td>
                          <td className="truncate px-3 py-2.5 text-slate-600">
                            {formatCategory(row.category)}
                          </td>
                          <td className="px-3 py-2.5">
                            <BasisPills basisTypes={row.basis_types} />
                          </td>
                          <td className="px-3 py-2.5">
                            <ConfidenceBadge
                              confidence={row.confidence}
                              calibrated={row.confidence_calibrated}
                              hasDecision={row.has_agent_decision}
                            />
                          </td>
                          <td className="px-3 py-2.5 text-slate-600">
                            <SourceCount
                              sources={row.agent_source_count}
                              planes={row.agent_plane_count}
                            />
                          </td>
                          <td className="px-3 py-2.5 font-semibold text-emerald-700">
                            {!row.has_agent_decision
                              ? <span className="text-slate-400">—</span>
                              : row.overpayment_display}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              {selectedRows.length > 0 || batchResult || batchError ? (
                <BatchAssuranceBar
                  selectedCount={selectedRows.length}
                  selectionTooLarge={batchSelectionTooLarge}
                  result={batchResult}
                  error={batchError}
                  onReview={() => setBatchConfirmOpen(true)}
                  onClear={() => setSelectedInvoiceIds(new Set())}
                  onViewActivity={openBatchActivity}
                />
              ) : null}
            </section>

            <aside className="flex min-h-0 flex-col gap-2 overflow-auto">
              {loading ? (
                <section className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-500 shadow-sm">
                  Loading insights…
                </section>
              ) : decisions.length > 0 ? (
                <InsightsSidebar rows={visible} onSelect={setSelectedDecision} />
              ) : null}
            </aside>
          </main>

            {selectedDecision ? (
              <DecisionDrawer
                decision={selectedDecision}
                detail={invoiceDetail}
                loading={detailLoading}
                agentContext={agentContext}
                agentLoading={agentLoading}
                triggering={triggeringInvoiceId === selectedDecision.invoice_id}
                triggerError={triggerError}
                onRunAssurance={() => void triggerAssurance(selectedDecision)}
                onViewActivity={() =>
                  navigate(
                    `/activity?invoice=${encodeURIComponent(
                      selectedDecision.invoice_number || selectedDecision.invoice_id,
                    )}`,
                  )
                }
                onOpenDocument={openDocumentPreview}
                onOpenPdf={(uri) =>
                  setPreview({
                    kind: "invoice-pdf",
                    title: `${selectedDecision.invoice_number} PDF`,
                    uri,
                    invoiceId: selectedDecision.invoice_id,
                  })
                }
                onClose={() => setSelectedDecision(null)}
              />
            ) : null}

            {batchConfirmOpen ? (
              <BatchAssuranceConfirmation
                rows={selectedRows}
                loading={batchLoading}
                error={batchError}
                onConfirm={() => void triggerBatchAssurance()}
                onClose={() => {
                  if (!batchLoading) {
                    setBatchConfirmOpen(false);
                    setBatchError(null);
                  }
                }}
              />
            ) : null}

            {preview ? (
              <DocumentPreviewModal preview={preview} onClose={() => setPreview(null)} />
            ) : previewLoading ? (
              <DocumentPreviewLoading onClose={() => setPreviewLoading(false)} />
            ) : null}
          </div>
        </div>
      </div>
    </RequireAuth>
  );
}

// ---------------------------------------------------------------------------
// Batch assurance
// ---------------------------------------------------------------------------

function SelectionCheckbox({
  checked,
  mixed = false,
  label,
  onChange,
}: {
  checked: boolean;
  mixed?: boolean;
  label: string;
  onChange: () => void;
}) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = mixed;
    }
  }, [mixed]);

  return (
    <input
      ref={checkboxRef}
      type="checkbox"
      checked={checked}
      aria-label={label}
      onChange={onChange}
      className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
    />
  );
}

function BatchAssuranceBar({
  selectedCount,
  selectionTooLarge,
  result,
  error,
  onReview,
  onClear,
  onViewActivity,
}: {
  selectedCount: number;
  selectionTooLarge: boolean;
  result: BatchAssuranceResult | null;
  error: string | null;
  onReview: () => void;
  onClear: () => void;
  onViewActivity: () => void;
}) {
  const hasActivityRuns = Boolean(
    result?.items.some(
      (item) =>
        (item.outcome === "accepted" || item.outcome === "reused") && item.run_id,
    ),
  );

  return (
    <div
      className="sticky bottom-0 z-20 border-t border-slate-200 bg-white/95 px-3 py-2.5 shadow-[0_-4px_14px_rgba(15,23,42,0.08)] backdrop-blur"
      aria-live="polite"
    >
      {selectedCount > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-900">
              {selectedCount} invoice{selectedCount === 1 ? "" : "s"} selected
            </p>
            <p
              className={`text-xs ${
                selectionTooLarge ? "font-medium text-rose-700" : "text-slate-500"
              }`}
            >
              {selectionTooLarge
                ? `Reduce the selection to ${MAX_BATCH_ASSURANCE_INVOICES} invoices or fewer.`
                : `Batch limit ${MAX_BATCH_ASSURANCE_INVOICES} · up to ${BATCH_ASSURANCE_CONCURRENCY} starts at once`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md px-3 py-1.5 text-sm font-semibold text-slate-600 hover:bg-slate-100"
              onClick={onClear}
            >
              Clear
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={onReview}
              disabled={selectionTooLarge}
            >
              <HiSparkles className="h-4 w-4" aria-hidden="true" />
              Review batch
            </button>
          </div>
        </div>
      ) : result ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <HiCheckCircle className="h-4 w-4 text-emerald-600" aria-hidden="true" />
              Batch request processed
            </p>
            <p className="mt-0.5 text-xs text-slate-600">
              {result.accepted} started · {result.reused} reused · {result.not_found} not found ·{" "}
              {result.start_failed} failed to start
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-sm font-semibold text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={onViewActivity}
            disabled={!hasActivityRuns}
          >
            View Activity
            <HiExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      ) : error ? (
        <p className="text-sm text-rose-700" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function BatchAssuranceConfirmation({
  rows,
  loading,
  error,
  onConfirm,
  onClose,
}: {
  rows: InvoiceDecision[];
  loading: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const totalAtRisk = rows.reduce(
    (sum, row) => sum + overpaymentAmount(row),
    0,
  );

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !loading) {
        onClose();
      }
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [loading, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="batch-assurance-title"
      aria-describedby="batch-assurance-guidance"
      onClick={loading ? undefined : onClose}
    >
      <section
        className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 p-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">
              Batch assurance
            </p>
            <h2 id="batch-assurance-title" className="mt-1 text-xl font-semibold">
              Start assurance for {rows.length} invoice{rows.length === 1 ? "" : "s"}?
            </h2>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-50 disabled:opacity-50"
            onClick={onClose}
            disabled={loading}
          >
            <HiX className="h-5 w-5" aria-hidden="true" />
            <span className="sr-only">Close batch confirmation</span>
          </button>
        </div>

        <div className="space-y-4 p-4">
          <div
            id="batch-assurance-guidance"
            className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm leading-5 text-blue-950"
          >
            Each newly accepted invoice starts a hosted agent orchestration and may incur usage
            cost. Active runs are reused automatically. Waypoint starts at most{" "}
            {BATCH_ASSURANCE_CONCURRENCY} invoices concurrently and accepts up to{" "}
            {MAX_BATCH_ASSURANCE_INVOICES} per batch.
          </div>

          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-500">Current recoverable amount</span>
            <span className="font-semibold text-emerald-700">{formatMoney(totalAtRisk)}</span>
          </div>

          <ul className="max-h-40 divide-y divide-slate-100 overflow-auto rounded-lg border border-slate-200">
            {rows.map((row) => (
              <li
                key={row.invoice_id}
                className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
              >
                <span className="truncate font-medium text-slate-800">{row.invoice_number}</span>
                <span className="truncate text-slate-500">{row.supplier_name}</span>
              </li>
            ))}
          </ul>

          {error ? (
            <p className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
              {error}
            </p>
          ) : null}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50 px-4 py-3">
          <button
            type="button"
            className="rounded-md px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-200 disabled:opacity-50"
            onClick={onClose}
            disabled={loading}
          >
            Cancel
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60"
            onClick={onConfirm}
            disabled={loading}
            autoFocus
          >
            {loading ? (
              <HiRefresh className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <HiSparkles className="h-4 w-4" aria-hidden="true" />
            )}
            {loading ? "Starting batch…" : "Start batch assurance"}
          </button>
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

function FilterBar({
  decisions,
  decisionFilter,
  onDecisionFilter,
  severities,
  severityFilter,
  onSeverityFilter,
  suppliers,
  supplierFilter,
  onSupplierFilter,
  categories,
  categoryFilter,
  onCategoryFilter,
  query,
  onQuery,
  sort,
  onSort,
}: {
  decisions: string[];
  decisionFilter: string;
  onDecisionFilter: (key: string) => void;
  severities: string[];
  severityFilter: string;
  onSeverityFilter: (key: string) => void;
  suppliers: string[];
  supplierFilter: string;
  onSupplierFilter: (key: string) => void;
  categories: string[];
  categoryFilter: string;
  onCategoryFilter: (key: string) => void;
  query: string;
  onQuery: (value: string) => void;
  sort: SortKey;
  onSort: (key: SortKey) => void;
}) {
  const selectClass =
    "min-h-8 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium text-slate-700 focus:border-blue-300 focus:outline-none";
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-slate-100 px-3 py-2.5">
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

      {categories.length > 1 ? (
        <select
          value={categoryFilter}
          onChange={(event) => onCategoryFilter(event.target.value)}
          className={`max-w-44 ${selectClass}`}
          aria-label="Filter by category"
        >
          <option value="all">All categories</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {formatCategory(category)}
            </option>
          ))}
        </select>
      ) : null}

      {severities.length > 1 ? (
        <select
          value={severityFilter}
          onChange={(event) => onSeverityFilter(event.target.value)}
          className={`capitalize ${selectClass}`}
          aria-label="Filter by severity"
        >
          <option value="all">Any severity</option>
          {severities.map((severity) => (
            <option key={severity} value={severity}>
              {severity}
            </option>
          ))}
        </select>
      ) : null}

      {suppliers.length > 1 ? (
        <select
          value={supplierFilter}
          onChange={(event) => onSupplierFilter(event.target.value)}
          className={`max-w-44 ${selectClass}`}
          aria-label="Filter by supplier"
        >
          <option value="all">All suppliers</option>
          {suppliers.map((supplier) => (
            <option key={supplier} value={supplier}>
              {supplier}
            </option>
          ))}
        </select>
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
            placeholder="Search invoice or supplier…"
            className="min-h-8 w-48 rounded-md border border-slate-200 bg-white py-1 pl-7 pr-2 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-300 focus:outline-none"
            aria-label="Search invoices"
          />
        </div>
        <select
          value={sort}
          onChange={(event) => onSort(event.target.value as SortKey)}
          className={selectClass}
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

function NoMatches({ onReset }: { onReset: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-3 py-10 text-center">
      <p className="text-sm font-semibold text-slate-700">No invoices match these filters</p>
      <p className="max-w-sm text-xs text-slate-500">
        Try widening the decision, severity, or supplier filters — or clear them to see the full
        register.
      </p>
      <button
        type="button"
        onClick={onReset}
        className="mt-1 inline-flex items-center rounded-md border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
      >
        Clear filters
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Insights sidebar (Recovery & risk) — business view, distinct from /agent
// ---------------------------------------------------------------------------

interface TrendPoint {
  label: string;
  value: number;
}

function buildRecoveryTrend(rows: InvoiceDecision[]): TrendPoint[] {
  const byDay = new Map<string, number>();
  for (const row of rows) {
    if (!row.agent_run_at) {
      continue;
    }
    const date = new Date(row.agent_run_at);
    if (Number.isNaN(date.getTime())) {
      continue;
    }
    const key = date.toISOString().slice(0, 10);
    byDay.set(key, (byDay.get(key) ?? 0) + overpaymentAmount(row));
  }
  return Array.from(byDay.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([label, value]) => ({ label, value }));
}

function InsightsSidebar({
  rows,
  onSelect,
}: {
  rows: InvoiceDecision[];
  onSelect: (row: InvoiceDecision) => void;
}) {
  const decisionMix = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) {
      if (row.decision === "Pending" || row.decision === "Not run") {
        continue;
      }
      counts.set(row.decision, (counts.get(row.decision) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([decision, count]) => ({ decision, count }))
      .sort((a, b) => b.count - a.count);
  }, [rows]);

  const recoveryBySupplier = useMemo(() => {
    const totals = new Map<string, number>();
    for (const row of rows) {
      const amount = overpaymentAmount(row);
      if (amount <= 0 || !row.supplier_name) {
        continue;
      }
      totals.set(row.supplier_name, (totals.get(row.supplier_name) ?? 0) + amount);
    }
    return Array.from(totals.entries())
      .map(([supplier, amount]) => ({ supplier, amount }))
      .sort((a, b) => b.amount - a.amount)
      .slice(0, 5);
  }, [rows]);

  const severityBreakdown = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) {
      if (!row.severity) {
        continue;
      }
      counts.set(row.severity, (counts.get(row.severity) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([severity, count]) => ({ severity, count }))
      .sort((a, b) => b.count - a.count);
  }, [rows]);

  const topOverpayments = useMemo(
    () =>
      [...rows]
        .filter((row) => overpaymentAmount(row) > 0)
        .sort((a, b) => overpaymentAmount(b) - overpaymentAmount(a))
        .slice(0, 5),
    [rows],
  );

  const trend = useMemo(() => buildRecoveryTrend(rows), [rows]);

  const total = decisionMix.reduce((sum, item) => sum + item.count, 0);
  const recoverySupplierMax = recoveryBySupplier[0]?.amount ?? 0;

  return (
    <>
      <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          Decision mix
        </p>
        {decisionMix.length > 0 ? (
          <>
            <div className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-slate-100">
              {decisionMix.map((item) => (
                <span
                  key={item.decision}
                  style={{
                    width: `${(item.count / total) * 100}%`,
                    backgroundColor: decisionColor(item.decision),
                  }}
                  title={`${item.decision}: ${item.count}`}
                />
              ))}
            </div>
            <ul className="mt-2.5 space-y-1.5">
              {decisionMix.map((item) => (
                <li
                  key={item.decision}
                  className="flex items-center justify-between gap-2 text-xs text-slate-600"
                >
                  <span className="flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: decisionColor(item.decision) }}
                    />
                    {item.decision}
                  </span>
                  <span className="tabular-nums text-slate-500">
                    {item.count} · {Math.round((item.count / total) * 100)}%
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="mt-2 text-xs text-slate-400">No decisions in view.</p>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
          Recovery by supplier
        </p>
        {recoveryBySupplier.length > 0 ? (
          <ul className="mt-2.5 space-y-2">
            {recoveryBySupplier.map((item) => (
              <li key={item.supplier}>
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate font-medium text-slate-700">{item.supplier}</span>
                  <span className="shrink-0 tabular-nums font-semibold text-emerald-700">
                    {formatMoney(item.amount)}
                  </span>
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                  <span
                    className="block h-full rounded-full bg-emerald-500"
                    style={{
                      width: `${recoverySupplierMax > 0 ? (item.amount / recoverySupplierMax) * 100 : 0}%`,
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs text-slate-400">No recoverable overpayment in view.</p>
        )}
      </section>

      {severityBreakdown.length > 0 ? (
        <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Severity
          </p>
          <ul className="mt-2.5 space-y-1.5">
            {severityBreakdown.map((item) => (
              <li
                key={item.severity}
                className="flex items-center justify-between gap-2 text-xs text-slate-600"
              >
                <span className="flex items-center gap-1.5">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: severityColor(item.severity) }}
                  />
                  {item.severity}
                </span>
                <span className="tabular-nums text-slate-500">{item.count}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {topOverpayments.length > 0 ? (
        <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Top overpayments
          </p>
          <ul className="mt-2 space-y-1">
            {topOverpayments.map((row) => (
              <li key={row.invoice_id}>
                <button
                  type="button"
                  onClick={() => onSelect(row)}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left text-xs hover:bg-slate-50"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-700">
                      {row.invoice_number}
                    </span>
                    {row.supplier_name ? (
                      <span className="block truncate text-[11px] text-slate-400">
                        {row.supplier_name}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 tabular-nums font-semibold text-emerald-700">
                    {row.overpayment_display}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {trend.length > 1 ? (
        <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <div className="flex items-center justify-between text-[11px] text-slate-400">
            <span className="font-semibold uppercase tracking-[0.2em] text-slate-500">
              Recovery trend
            </span>
            <span>{trend.length} days</span>
          </div>
          <Sparkline points={trend} className="mt-2" />
        </section>
      ) : null}
    </>
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
      aria-label="Recovery over time"
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

type TabKey = "decision" | "evidence" | "trail" | "documents";

function DecisionDrawer({
  decision,
  detail,
  loading,
  agentContext,
  agentLoading,
  triggering,
  triggerError,
  onRunAssurance,
  onViewActivity,
  onOpenDocument,
  onOpenPdf,
  onClose,
}: {
  decision: InvoiceDecision;
  detail: InvoiceDetail | null;
  loading: boolean;
  agentContext: AgentContext | null;
  agentLoading: boolean;
  triggering: boolean;
  triggerError: string | null;
  onRunAssurance: () => void;
  onViewActivity: () => void;
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
  onOpenPdf: (uri: string) => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<TabKey>("decision");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  useEffect(() => {
    setTab("decision");
    setSelectedCaseId(null);
  }, [decision.invoice_id]);

  const finding = decision.has_agent_decision ? detail?.findings[0] : undefined;
  const entries = agentContext?.entries ?? [];
  const selectedEntry =
    entries.find((entry) => entry.case.id === selectedCaseId) ?? entries[0] ?? null;
  const fanout = selectedEntry?.fanout ?? [];

  // The drawer header reflects the NEWEST agent run (the canonical/current decision) so it
  // always agrees with the lead of the Agent-decision card and the list row. The switcher
  // inside the card lets the reviewer inspect older runs without moving the header.
  const newestEntry = entries[0] ?? null;
  const newestRecommendation = newestEntry?.recommendation ?? null;
  const moneyAtRisk = newestRecommendation
    ? formatAgentMoney(newestRecommendation.money_at_risk)
    : decision.overpayment_display;
  const confidencePct = newestRecommendation?.metadata.confidence_calibrated === true
    ? Math.round(Number(newestRecommendation.confidence) * 100)
    : null;
  const headerDecision = newestRecommendation
    ? agentDecisionToLabel(newestRecommendation.decision)
    : decision.decision;

  return (
    <div className="absolute inset-0 z-30 flex justify-end">
      <button
        type="button"
        className="absolute inset-0 cursor-default bg-slate-950/20"
        aria-label="Close decision context"
        onClick={onClose}
      />
      <aside
        className="relative z-10 flex h-full w-full max-w-[440px] flex-col overflow-hidden border-l border-slate-200 bg-white shadow-2xl"
        aria-label={`Decision context for ${decision.invoice_number}`}
      >
        <div className="border-b border-slate-100 bg-white p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold">{decision.invoice_number}</h2>
              <p className="mt-0.5 truncate text-sm text-slate-500">{decision.supplier_name}</p>
            </div>
            <button
              className="-mr-1 shrink-0 rounded-md p-1 text-slate-400 hover:bg-slate-50"
              type="button"
              onClick={onClose}
            >
              <HiX className="h-5 w-5" />
              <span className="sr-only">Close decision context</span>
            </button>
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <DecisionPill decision={headerDecision} />
            {decision.has_agent_decision ? (
              <>
                <SummaryChip tone="emerald">{moneyAtRisk} at risk</SummaryChip>
                {confidencePct !== null ? (
                  <SummaryChip tone="slate">{confidencePct}% confidence</SummaryChip>
                ) : (
                  <SummaryChip tone="slate">Confidence not calibrated</SummaryChip>
                )}
                <SummaryChip tone="slate">{decision.category}</SummaryChip>
                <SummaryChip tone="slate">{decision.evidence_count} evidence</SummaryChip>
              </>
            ) : null}
          </div>
          <div className="mt-3">
            <button
              type="button"
              onClick={decision.has_active_run ? onViewActivity : onRunAssurance}
              disabled={triggering}
              className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-wait disabled:opacity-60"
            >
              <HiSparkles className={triggering ? "h-4 w-4 animate-pulse" : "h-4 w-4"} />
              {triggering
                ? "Starting assurance…"
                : decision.has_active_run
                  ? "View active run"
                  : "Run assurance"}
            </button>
            {triggerError ? (
              <p className="mt-2 text-sm text-rose-700" role="alert">
                {triggerError}
              </p>
            ) : null}
          </div>
        </div>

        <SegmentedTabs tab={tab} onChange={setTab} evidenceCount={fanout.length} />

        <div className="min-h-0 flex-1 overflow-auto">
          {tab === "decision" ? (
            <div className="space-y-5 p-4">
              {decision.has_agent_decision ? (
                <>
                  <AgentDecisionSummary
                    entries={entries}
                    selectedEntry={selectedEntry}
                    onSelectCase={setSelectedCaseId}
                    loading={agentLoading}
                  />

                  <section>
                    <h3 className="font-semibold">Finding</h3>
                    <p className="mt-2 text-sm leading-6 text-slate-700">
                      {finding?.summary ?? decision.reasoning}
                    </p>
                  </section>

                  <BasisGlance
                    decision={decision}
                    finding={finding}
                    onViewDocuments={() => setTab("documents")}
                  />
                </>
              ) : (
                <section className="rounded-md border border-blue-100 bg-blue-50/60 p-4">
                  <h3 className="font-semibold text-slate-900">Ready for assurance</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-600">
                    Run assurance to generate a governed decision, grounded evidence, and any
                    recoverable amount for this invoice.
                  </p>
                </section>
              )}
            </div>
          ) : null}

          {tab === "evidence" ? (
            <div className="space-y-5 p-4">
              <section>
                <h3 className="font-semibold">Per-expert evidence</h3>
                {fanout.length > 0 ? (
                  <ol className="mt-2 space-y-2">
                    {(() => {
                      const topLane = topConfidenceLaneIndex(fanout);
                      return fanout.map((lane, index) => (
                        <ExpertLane
                          key={`${lane.agent ?? lane.plane ?? "lane"}-${index}`}
                          lane={lane}
                          defaultOpen={index === topLane}
                        />
                      ));
                    })()}
                  </ol>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">
                    No per-expert evidence has been recorded for this invoice yet.
                  </p>
                )}
              </section>

              {loading ? (
                <p className="text-sm text-slate-500">Loading invoice detail…</p>
              ) : (
                <>
                  <section>
                    <h3 className="font-semibold">Evidence references</h3>
                    <ol className="mt-2 space-y-2">
                      {(decision.has_agent_decision ? detail?.evidence ?? [] : []).map((item) => (
                        <li
                          key={item.id}
                          className="rounded-md border border-slate-100 p-2 text-sm"
                        >
                          <div className="flex items-start gap-2">
                            <HiDocumentText className="mt-0.5 h-4 w-4 text-blue-700" />
                            <div>
                              <p className="font-medium">{item.title}</p>
                              <p className="text-xs uppercase tracking-[0.14em] text-slate-500">
                                {item.evidence_type}
                              </p>
                              {item.excerpt ? (
                                <p className="mt-1 text-sm leading-5 text-slate-600">
                                  {item.excerpt}
                                </p>
                              ) : null}
                              <DocumentLink label="Open evidence" uri={item.uri} compact />
                            </div>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </section>

                  <section>
                    <h3 className="font-semibold">Invoice lines</h3>
                    <div className="mt-2 divide-y divide-slate-100 rounded-md border border-slate-100">
                      {(detail?.lines ?? []).map((line) => (
                        <div key={line.id} className="p-2 text-sm">
                          <div className="flex items-start justify-between gap-3">
                            <p className="font-medium">{line.description}</p>
                            <p className="font-semibold">
                              {formatCurrency(line.amount, detail?.currency)}
                            </p>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">
                            {line.sku ? `SKU ${line.sku}` : "No SKU"}
                            {line.purchase_order ? ` · ${line.purchase_order}` : ""}
                          </p>
                        </div>
                      ))}
                    </div>
                  </section>
                </>
              )}
            </div>
          ) : null}

          {tab === "trail" ? (
            <div className="p-4">
              <section>
                <h3 className="font-semibold">Decision trail</h3>
                <ol className="mt-2 space-y-0">
                  {decisionTrail(decision, detail).map((item) => (
                    <li key={item.title} className="grid grid-cols-[20px_minmax(0,1fr)] gap-3">
                      <div className="relative flex justify-center">
                        <span className="relative z-10 mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-50 text-blue-700 ring-4 ring-white">
                          <HiCheckCircle className="h-4 w-4" />
                        </span>
                        <span className="absolute bottom-0 top-7 w-px bg-slate-200" />
                      </div>
                      <div className="pb-5">
                        <p className="font-semibold">{item.title}</p>
                        <p className="mt-1 text-sm leading-6 text-slate-600">{item.detail}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            </div>
          ) : null}

          {tab === "documents" ? (
            <div className="space-y-4 p-4">
              <div className="flex items-center gap-2 rounded-md border border-slate-100 bg-slate-50/80 px-3 py-2">
                <OneLakeIcon className="h-4 w-4 shrink-0" />
                <p className="text-xs font-medium text-slate-600">
                  Documents sourced from Microsoft OneLake
                </p>
              </div>
              <BasisSummary
                decision={decision}
                finding={finding}
                onOpenDocument={onOpenDocument}
              />
              <div className="flex flex-wrap gap-2">
                <PreviewDocumentButton
                  label="Invoice PDF"
                  uri={decision.pdf_uri}
                  onOpen={onOpenPdf}
                />
              </div>
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function SummaryChip({
  tone,
  children,
}: {
  tone: "emerald" | "slate";
  children: ReactNode;
}) {
  const cls =
    tone === "emerald"
      ? "bg-emerald-50 text-emerald-800 ring-emerald-100"
      : "bg-slate-50 text-slate-600 ring-slate-200";
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      {children}
    </span>
  );
}

function SegmentedTabs({
  tab,
  onChange,
  evidenceCount,
}: {
  tab: TabKey;
  onChange: (tab: TabKey) => void;
  evidenceCount: number;
}) {
  const tabs: Array<{ key: TabKey; label: string; count?: number }> = [
    { key: "decision", label: "Decision" },
    { key: "evidence", label: "Evidence", count: evidenceCount },
    { key: "trail", label: "Trail" },
    { key: "documents", label: "Documents" },
  ];
  return (
    <div className="border-b border-slate-100 px-3">
      <div className="flex gap-1" role="tablist" aria-label="Invoice detail sections">
        {tabs.map((entry) => {
          const active = entry.key === tab;
          return (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(entry.key)}
              className={[
                "relative flex items-center gap-1 px-2.5 py-2 text-xs font-semibold transition-colors",
                active ? "text-blue-700" : "text-slate-500 hover:text-slate-700",
              ].join(" ")}
            >
              {entry.label}
              {entry.count ? (
                <span className="rounded bg-slate-100 px-1 text-[10px] font-medium text-slate-500">
                  {entry.count}
                </span>
              ) : null}
              {active ? (
                <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-blue-600" />
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const PLANE_LABELS: Record<string, string> = {
  workiq: "WorkIQ",
  webiq: "WebIQ",
  foundryiq: "FoundryIQ",
  fabriciq: "FabricIQ",
};

function planeLabel(lane: FanoutLane): string {
  const key = (lane.plane ?? lane.agent ?? "").toLowerCase().replace(/-expert$/, "");
  return PLANE_LABELS[key] ?? formatCategory(lane.agent || lane.plane || "Expert");
}

function laneAvgConfidence(lane: FanoutLane): number | null {
  const items = (lane.evidence ?? []).filter(
    (item) => typeof item.confidence === "number",
  );
  if (items.length === 0) {
    return null;
  }
  const sum = items.reduce((acc, item) => acc + (item.confidence ?? 0), 0);
  return sum / items.length;
}

function topConfidenceLaneIndex(lanes: FanoutLane[]): number {
  let best = 0;
  let bestScore = -Infinity;
  lanes.forEach((lane, index) => {
    const score = laneAvgConfidence(lane) ?? -1;
    if (score > bestScore) {
      bestScore = score;
      best = index;
    }
  });
  return best;
}

function confidenceTone(score: number): string {
  if (score >= 0.7) {
    return "bg-emerald-50 text-emerald-800 ring-emerald-100";
  }
  if (score >= 0.4) {
    return "bg-amber-50 text-amber-800 ring-amber-100";
  }
  return "bg-rose-50 text-rose-800 ring-rose-100";
}

function ExpertLane({
  lane,
  defaultOpen = false,
}: {
  lane: FanoutLane;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const evidence = lane.evidence ?? [];
  const avg = laneAvgConfidence(lane);
  return (
    <li className="overflow-hidden rounded-md border border-slate-200 bg-white text-sm">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 p-2 text-left hover:bg-slate-50"
      >
        <HiChevronRight
          className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}
        />
        <span className="font-semibold capitalize">{planeLabel(lane)}</span>
        <span className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[11px] font-medium text-slate-500">
          {evidence.length} {evidence.length === 1 ? "citation" : "citations"}
        </span>
        {avg !== null ? (
          <span
            className={`ml-auto rounded-md px-1.5 py-0.5 text-[11px] font-semibold ring-1 ${confidenceTone(avg)}`}
          >
            {Math.round(avg * 100)}%
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="border-t border-slate-100 p-2">
          {lane.summary ? <p className="text-sm text-slate-600">{lane.summary}</p> : null}
          {evidence.length > 0 ? (
            <ul className="mt-1.5 space-y-1.5 border-l border-slate-200 pl-3">
              {evidence.map((item, itemIndex) => (
                <li key={itemIndex} className="text-sm text-slate-600">
                  <div className="flex items-start justify-between gap-2">
                    <span className="block">{item.claim || "(no citation text)"}</span>
                    {typeof item.confidence === "number" ? (
                      <span className="shrink-0 text-[11px] font-medium text-slate-400">
                        {Math.round(item.confidence * 100)}%
                      </span>
                    ) : null}
                  </div>
                  {item.source_ref ? (
                    <code className="mt-0.5 inline-block rounded bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-slate-200">
                      {cleanSourceRef(item.source_ref)}
                    </code>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function BasisGlance({
  decision,
  finding,
  onViewDocuments,
}: {
  decision: InvoiceDecision;
  finding: Finding | undefined;
  onViewDocuments: () => void;
}) {
  const summary = finding?.basis_summary ?? decision.basis_summary;
  return (
    <section className="rounded-md border border-indigo-100 bg-indigo-50/60 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-indigo-800">
          Contract / policy basis
        </p>
        <BasisPills basisTypes={decision.basis_types} />
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        {summary ?? "No contract or policy basis is attached to this finding."}
      </p>
      <button
        type="button"
        onClick={onViewDocuments}
        className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-indigo-700 hover:text-indigo-900"
      >
        View documents
        <HiChevronRight className="h-3.5 w-3.5" />
      </button>
    </section>
  );
}

function formatAgentMoney(value: string | undefined): string {
  const amount = Number(value ?? 0);
  return `$${(Number.isFinite(amount) ? amount : 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

const AGENT_DECISION_STYLES: Record<string, string> = {
  recover: "bg-emerald-50 text-emerald-800 ring-emerald-100",
  recovery: "bg-emerald-50 text-emerald-800 ring-emerald-100",
  escalate: "bg-red-50 text-red-800 ring-red-100",
  review: "bg-amber-50 text-amber-800 ring-amber-100",
  approve: "bg-slate-100 text-slate-700 ring-slate-200",
};

function agentDecisionToLabel(decision: string): string {
  const normalized = decision.toLowerCase();
  if (normalized === "recover" || normalized === "recovery") return "Recover";
  if (normalized === "escalate") return "Escalate";
  if (normalized === "approve") return "Approve";
  if (normalized === "review") return "Review";
  return decision ? decision.charAt(0).toUpperCase() + decision.slice(1) : decision;
}

function formatRunDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function CaseSwitcher({
  entries,
  selectedCaseId,
  onSelectCase,
}: {
  entries: AgentCaseEntry[];
  selectedCaseId: string | null;
  onSelectCase: (caseId: string) => void;
}) {
  const count = entries.length;
  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-white p-2">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Agent runs ({count})
        </p>
        <p className="text-[11px] text-slate-400">Newest first · runs disagree</p>
      </div>
      <div
        className="mt-1.5 flex flex-wrap gap-1.5"
        role="radiogroup"
        aria-label="Select agent run"
      >
        {entries.map((entry, index) => {
          const runNumber = count - index;
          const active = entry.case.id === selectedCaseId;
          const decision = (entry.recommendation?.decision ?? entry.run?.metadata?.decision ?? "")
            .toLowerCase();
          const dot = AGENT_DECISION_STYLES[decision] ?? "bg-slate-100 text-slate-700 ring-slate-200";
          return (
            <button
              key={entry.case.id}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onSelectCase(entry.case.id)}
              className={[
                "flex items-center gap-1.5 rounded-md border px-2 py-1 text-left text-[11px] transition-colors",
                active
                  ? "border-blue-300 bg-blue-50 text-blue-900 ring-1 ring-blue-200"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
              ].join(" ")}
            >
              <span className={`h-2 w-2 shrink-0 rounded-full ring-1 ${dot}`} aria-hidden="true" />
              <span className="font-semibold">Run {runNumber}</span>
              {decision ? <span className="capitalize">· {agentDecisionToLabel(decision)}</span> : null}
              {index === 0 ? (
                <span className="rounded bg-blue-100 px-1 text-[10px] font-semibold text-blue-700">
                  newest
                </span>
              ) : null}
              <span className="whitespace-nowrap text-slate-400">{formatRunDateTime(entry.case.created_at)}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function AgentDecisionSummary({
  entries,
  selectedEntry,
  onSelectCase,
  loading,
}: {
  entries: AgentCaseEntry[];
  selectedEntry: AgentCaseEntry | null;
  onSelectCase: (caseId: string) => void;
  loading: boolean;
}) {
  if (loading) {
    return (
      <section className="rounded-md border border-blue-100 bg-blue-50/40 p-3">
        <p className="text-sm text-slate-500">Loading agent decision…</p>
      </section>
    );
  }

  const recommendation = selectedEntry?.recommendation ?? null;
  const fanout = selectedEntry?.fanout ?? [];
  const caseCount = entries.length;

  if (!recommendation && fanout.length === 0) {
    return (
      <section className="rounded-md border border-dashed border-slate-300 bg-slate-50/60 p-3">
        <div className="flex items-center gap-2">
          <HiSparkles className="h-4 w-4 text-blue-700" aria-hidden="true" />
          <h3 className="font-semibold">Agent decision</h3>
        </div>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          No agent run has been recorded for this invoice yet. Trigger a pacioli fan-out
          and the aggregator will write the grounded decision and evidence trail here.
        </p>
      </section>
    );
  }

  const decision = (recommendation?.decision ?? selectedEntry?.run?.metadata?.decision ?? "").toLowerCase();
  const style = AGENT_DECISION_STYLES[decision] ?? "bg-slate-100 text-slate-700 ring-slate-200";
  const drafts = selectedEntry?.drafts ?? [];
  const reviewerDraft =
    drafts.find((draft) => draft.draft_type === "approval_summary") ?? drafts[0] ?? null;

  return (
    <section className="rounded-md border border-blue-100 bg-blue-50/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <HiSparkles className="h-4 w-4 text-blue-700" aria-hidden="true" />
        <h3 className="font-semibold">Agent decision</h3>
        {decision ? (
          <span className={`rounded-md px-2 py-0.5 text-xs font-semibold uppercase capitalize ring-1 ${style}`}>
            {decision}
          </span>
        ) : null}
        {recommendation ? (
          <>
            <span className="rounded-md bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-100">
              {formatAgentMoney(recommendation.money_at_risk)} at risk
            </span>
            {recommendation.metadata.confidence_calibrated === true ? (
              <span className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-600">
                {Math.round(Number(recommendation.confidence) * 100)}% confidence
              </span>
            ) : (
              <span
                className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-xs font-medium text-slate-600"
                title="The current score measures fallback evidence retrieval, not calibrated decision accuracy."
              >
                Confidence not calibrated
              </span>
            )}
          </>
        ) : null}
      </div>

      {caseCount > 1 && selectedEntry ? (
        <CaseSwitcher
          entries={entries}
          selectedCaseId={selectedEntry.case.id}
          onSelectCase={onSelectCase}
        />
      ) : null}

      {recommendation?.reasoning ? (
        <p className="mt-2 text-sm leading-6 text-slate-700">{recommendation.reasoning}</p>
      ) : null}

      {recommendation && recommendation.proposed_next_actions.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-600">
          {recommendation.proposed_next_actions.map((action, index) => (
            <li key={index}>{formatActionLabel(action)}</li>
          ))}
        </ul>
      ) : null}

      {reviewerDraft ? (
        <div className="mt-3 rounded-md border border-slate-200 bg-white p-2.5">
          <div className="flex items-center gap-1.5">
            <HiDocumentText className="h-4 w-4 text-blue-700" aria-hidden="true" />
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              Reviewer draft · {reviewerDraft.draft_type.replace(/_/g, " ")}
            </p>
          </div>
          <p className="mt-1.5 text-sm font-medium text-slate-800">{reviewerDraft.title}</p>
          <p className="mt-1 text-sm leading-6 text-slate-600">{reviewerDraft.body}</p>
        </div>
      ) : null}

      {recommendation ? (
        <p className="mt-2 text-xs text-slate-400">
          {recommendation.created_by} ·{" "}
          <code className="rounded bg-slate-50 px-1 py-0.5 text-[11px] text-slate-600">
            {recommendation.metadata?.waypoint_run_id ?? selectedEntry?.run?.id ?? recommendation.id}
          </code>
        </p>
      ) : null}
    </section>
  );
}

function InfoTile({
  label,
  value,
  emphasized = false,
  reviewing = false,
  escalation = false,
  onClick,
  title,
}: {
  label: string;
  value: string;
  emphasized?: boolean;
  reviewing?: boolean;
  escalation?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  const labelClass = reviewing
    ? "text-indigo-600"
    : escalation
      ? "text-red-600"
      : "text-slate-500";
  const valueClass = reviewing
    ? "flex items-center justify-end gap-1.5 font-semibold text-indigo-700"
    : escalation
      ? "font-semibold text-red-700"
      : emphasized
        ? "font-semibold text-emerald-700"
        : "font-medium";

  const inner = (
    <>
      <p className={`text-xs ${labelClass}`}>{label}</p>
      <p className={valueClass}>
        {reviewing ? (
          <span
            className="h-2.5 w-2.5 animate-spin rounded-full border-[1.5px] border-indigo-300 border-t-indigo-600"
            aria-hidden="true"
          />
        ) : null}
        {value}
      </p>
    </>
  );

  if (onClick) {
    const buttonTone = reviewing
      ? "bg-indigo-50 ring-1 ring-inset ring-indigo-200 hover:bg-indigo-100 hover:ring-indigo-300"
      : escalation
        ? "bg-red-50 ring-1 ring-inset ring-red-200 hover:bg-red-100 hover:ring-red-300"
        : "bg-slate-50 hover:bg-slate-100";
    return (
      <button
        type="button"
        onClick={onClick}
        title={title}
        className={`w-full rounded-md p-2 text-right transition ${buttonTone}`}
      >
        {inner}
      </button>
    );
  }

  return (
    <div
      className={`rounded-md p-2 ${
        reviewing ? "bg-indigo-50" : escalation ? "bg-red-50" : "bg-slate-50"
      }`}
    >
      {inner}
    </div>
  );
}

function DocumentLink({
  label,
  uri,
  compact = false,
}: {
  label: string;
  uri: string | null;
  compact?: boolean;
}) {
  if (!uri) {
    return null;
  }
  const displayPath = cleanDocumentPath(uri);
  const isWebUri = uri.startsWith("http://") || uri.startsWith("https://");
  const className = compact
    ? "mt-1 inline-flex max-w-full flex-wrap items-center gap-1 break-all text-xs font-medium text-blue-700"
    : "inline-flex max-w-full flex-wrap items-center gap-1 break-all rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-800";
  if (!isWebUri) {
    return <span className={className}>{label}: {displayPath}</span>;
  }
  return (
    <a className={className} href={uri} target="_blank" rel="noreferrer">
      {label}: {displayPath}
      <HiExternalLink className="h-3.5 w-3.5" />
    </a>
  );
}

function OneLakeIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 48 49"
      className={className}
      role="img"
      aria-label="Microsoft OneLake"
    >
      <mask
        id="ol-a"
        width="40"
        height="41"
        x="4"
        y="4"
        maskUnits="userSpaceOnUse"
        style={{ maskType: "luminance" }}
      >
        <path fill="#fff" d="M43.481 4.5H4.52v39.985h38.96V4.5Z" />
      </mask>
      <g mask="url(#ol-a)">
        <path
          fill="url(#ol-b)"
          d="M22.21 33.041c5.486-3.168 7.293-10.312 4.033-15.957-3.26-5.646-10.35-7.654-15.836-4.486C4.92 15.766 3.114 22.91 6.373 28.556c3.26 5.645 10.35 7.653 15.836 4.485Z"
        />
        <path
          fill="url(#ol-c)"
          d="M29.371 17.215c2.849-2.85 2.78-7.536-.152-10.468C26.287 3.816 21.6 3.75 18.751 6.6s-2.78 7.537.152 10.468c2.933 2.932 7.62 2.998 10.468.148Z"
        />
        <path
          fill="url(#ol-d)"
          d="M26.299 43.72c9.487 0 17.178-7.691 17.178-17.179S35.787 9.362 26.3 9.362 9.12 17.053 9.12 26.541 16.811 43.72 26.3 43.72Z"
        />
        <path
          fill="url(#ol-e)"
          fillRule="evenodd"
          d="M19.569 5.887c-10.085 6.23-13.61 19.35-7.815 29.845.39.71.815 1.392 1.274 2.039l.45.069 9.966 3.327 9.468-6.343c-1.585.05-8.18-3.693-12.49-11.872-5.4-10.248-3.173-14.982-.843-17.065h-.01Z"
          clipRule="evenodd"
        />
        <path
          fill="url(#ol-f)"
          fillOpacity=".2"
          fillRule="evenodd"
          d="M19.569 5.887c-10.085 6.23-13.61 19.35-7.815 29.845.39.71.815 1.392 1.274 2.039l.45.069 9.966 3.327 9.468-6.343c-1.585.05-8.18-3.693-12.49-11.872-5.4-10.248-3.173-14.982-.843-17.065h-.01Z"
          clipRule="evenodd"
        />
        <path
          fill="url(#ol-g)"
          fillRule="evenodd"
          d="M39.364 37.697a17.24 17.24 0 0 0 3.638-7.109c-1.708-4.877-8.58-6.249-12.34-2.433-2.889 2.927-5.89 5.386-8.146 5.825C9.469 36.542 3.919 25.787 4.873 20.84a19.81 19.81 0 0 0 .05 7.73c2.196 10.76 12.696 17.7 23.457 15.505a19.814 19.814 0 0 0 8.727-4.181s.04-.03.054-.045a19.76 19.76 0 0 0 2.202-2.157v.005Z"
          clipRule="evenodd"
        />
      </g>
      <defs>
        <radialGradient
          id="ol-d"
          cx="0"
          cy="0"
          r="1"
          gradientTransform="rotate(134.83 18.113 8.294) scale(25.8925 33.4033)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".39" stopColor="#028FDC" />
          <stop offset=".59" stopColor="#0078D4" />
          <stop offset="1" stopColor="#1A508B" />
        </radialGradient>
        <radialGradient
          id="ol-e"
          cx="0"
          cy="0"
          r="1"
          gradientTransform="rotate(139.44 12.54 14.145) scale(23.3006 28.7495)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".46" stopColor="#40D9FA" />
          <stop offset=".9" stopColor="#0095E6" />
        </radialGradient>
        <radialGradient
          id="ol-f"
          cx="0"
          cy="0"
          r="1"
          gradientTransform="matrix(-2.65308 24.58184 -17.45831 -1.88425 18.408 11.764)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".77" stopOpacity="0" />
          <stop offset="1" />
        </radialGradient>
        <radialGradient
          id="ol-g"
          cx="0"
          cy="0"
          r="1"
          gradientTransform="rotate(85.97 -1.011 31.209) scale(38.4749 70.1578)"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".1" stopColor="#BDF5FF" />
          <stop offset=".47" stopColor="#40D9FA" />
        </radialGradient>
        <linearGradient
          id="ol-b"
          x1="39.51"
          x2="4.448"
          y1="17.473"
          y2="25.557"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".2" stopColor="#028FDC" />
          <stop offset=".51" stopColor="#0078D4" />
          <stop offset="1" stopColor="#0B315B" />
        </linearGradient>
        <linearGradient
          id="ol-c"
          x1="41.995"
          x2="18.831"
          y1="28.341"
          y2="7.112"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset=".04" stopColor="#028FDC" />
          <stop offset=".46" stopColor="#0078D4" />
          <stop offset="1" stopColor="#0B315B" />
        </linearGradient>
      </defs>
    </svg>
  );
}

function PreviewDocumentButton({
  label,
  uri,
  onOpen,
}: {
  label: string;
  uri: string | null;
  onOpen: (uri: string) => void;
}) {
  if (!uri) {
    return null;
  }
  return (
    <button
      type="button"
      className="inline-flex max-w-full flex-wrap items-center gap-1 break-all rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-left text-xs font-medium text-blue-800 hover:border-blue-200 hover:bg-blue-100"
      onClick={() => onOpen(uri)}
    >
      {label}: {cleanDocumentPath(uri)}
    </button>
  );
}

function cleanDocumentPath(uri: string) {
  const hiddenSegment = ["gen", "erated"].join("");
  return uri
    .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
    .split("/")
    .filter((part) => part && !part.toLowerCase().includes(hiddenSegment))
    .join("/");
}

function DecisionPill({ decision }: { decision: string }) {
  if (decision === "Pending") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-700">
        <span
          className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-indigo-300 border-t-indigo-600"
          aria-hidden="true"
        />
        Pending
        <HiExternalLink className="h-3 w-3 text-indigo-400" aria-hidden="true" />
      </span>
    );
  }
  if (decision === "Not run") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
        <span className="h-2 w-2 rounded-full bg-slate-400" aria-hidden="true" />
        Not run
      </span>
    );
  }
  const className =
    decision === "Escalate"
      ? "bg-rose-50 text-rose-800"
      : decision === "Recover"
        ? "bg-emerald-50 text-emerald-800"
        : decision === "Approve"
          ? "bg-blue-50 text-blue-800"
          : decision === "Closed"
            ? "bg-slate-100 text-slate-700"
            : "bg-amber-50 text-amber-800";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold ${className}`}
    >
      <span
        className="inline-block h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: decisionColor(decision) }}
        aria-hidden="true"
      />
      {decision}
    </span>
  );
}

function ConfidenceBadge({
  confidence,
  calibrated,
  hasDecision,
}: {
  confidence: string | null;
  calibrated: boolean;
  hasDecision: boolean;
}) {
  if (hasDecision && !calibrated) {
    return (
      <span
        className="inline-flex rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 ring-1 ring-slate-200"
        title="The current score measures fallback evidence retrieval, not calibrated decision accuracy."
      >
        Not calibrated
      </span>
    );
  }
  if (confidence === null || confidence === "") {
    return <span className="text-xs text-slate-400">—</span>;
  }
  const score = Number(confidence);
  if (!Number.isFinite(score)) {
    return <span className="text-xs text-slate-400">—</span>;
  }
  return (
    <span
      className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${confidenceTone(score)}`}
    >
      {Math.round(score * 100)}%
    </span>
  );
}

function SourceCount({ sources, planes }: { sources: number; planes: number }) {
  if (sources <= 0 && planes <= 0) {
    return (
      <span className="text-xs text-slate-400" title="No expert evidence recorded for this invoice yet.">
        No evidence
      </span>
    );
  }
  const expertWord = planes === 1 ? "expert" : "experts";
  const sourceWord = sources === 1 ? "source" : "sources";
  const tooltip =
    planes > 0
      ? `${sources} evidence ${sourceWord} corroborated across ${planes} independent ${expertWord} (e.g. WorkIQ, FabricIQ). Open the row to see each expert's citations.`
      : `${sources} evidence ${sourceWord} recorded. Open the row to see the details.`;
  if (planes <= 0) {
    return (
      <span className="text-xs text-slate-600" title={tooltip}>
        <span className="font-semibold text-slate-700">{sources}</span> {sourceWord}
      </span>
    );
  }
  return (
    <span className="flex flex-col leading-tight" title={tooltip}>
      <span className="text-xs text-slate-700">
        <span className="font-semibold">{planes}</span> {expertWord}
      </span>
      {sources > 0 ? (
        <span className="text-[11px] text-slate-400">
          {sources} {sourceWord} cited
        </span>
      ) : null}
    </span>
  );
}

function BasisPills({ basisTypes }: { basisTypes: Array<"contract" | "policy"> }) {
  if (basisTypes.length === 0) {
    return <span className="text-xs text-slate-400">Unmapped</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {basisTypes.map((basisType) => (
        <span
          key={basisType}
          className={
            basisType === "contract"
              ? "rounded-md bg-indigo-50 px-2 py-0.5 text-xs font-semibold text-indigo-800"
              : "rounded-md bg-cyan-50 px-2 py-0.5 text-xs font-semibold text-cyan-800"
          }
        >
          {basisType === "contract" ? "Contract" : "Policy"}
        </span>
      ))}
    </div>
  );
}

function BasisSummary({
  decision,
  finding,
  onOpenDocument,
}: {
  decision: InvoiceDecision;
  finding: Finding | undefined;
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
}) {
  const contractIds = finding?.contract_document_ids ?? decision.contract_document_ids;
  const policyIds = finding?.policy_ids ?? decision.policy_ids;
  const summary = finding?.basis_summary ?? decision.basis_summary;

  return (
    <div className="mt-3 rounded-md border border-indigo-100 bg-indigo-50/60 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-indigo-800">
          Contract / policy basis
        </p>
        <BasisPills basisTypes={decision.basis_types} />
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-700">
        {summary ?? "No contract or policy basis is attached to this finding."}
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {contractIds.map((id) => (
          <button
            key={id}
            type="button"
            className="rounded bg-white px-2 py-1 text-left text-xs font-medium text-indigo-800 ring-1 ring-indigo-100 hover:bg-indigo-100"
            onClick={() => onOpenDocument("contract", id)}
          >
            {id}
          </button>
        ))}
        {policyIds.map((id) => (
          <button
            key={id}
            type="button"
            className="rounded bg-white px-2 py-1 text-left text-xs font-medium text-cyan-800 ring-1 ring-cyan-100 hover:bg-cyan-100"
            onClick={() => onOpenDocument("policy", id)}
          >
            {id}
          </button>
        ))}
      </div>
    </div>
  );
}

function LightboxShell({
  title,
  subtitle,
  onClose,
  dense = false,
  children,
}: {
  title: string;
  subtitle: string;
  onClose: () => void;
  dense?: boolean;
  children: ReactNode;
}) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        // Capture phase + stop propagation so ESC closes the viewer first, without also
        // closing the decision drawer underneath it.
        event.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={`Preview ${title}`}
      onClick={onClose}
    >
      <section
        className={
          dense
            ? "flex h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
            : "flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        }
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 bg-white p-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-700">
              {subtitle}
            </p>
            <h2 className="mt-1 text-xl font-semibold">{title}</h2>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-50"
            onClick={onClose}
          >
            <HiX className="h-5 w-5" />
            <span className="sr-only">Close preview</span>
          </button>
        </div>
        <div
          className={
            dense
              ? "min-h-0 flex-1 overflow-hidden bg-slate-100"
              : "min-h-0 flex-1 space-y-4 overflow-auto p-4"
          }
        >
          {children}
        </div>
      </section>
    </div>
  );
}

function DocumentPreviewLoading({ onClose }: { onClose: () => void }) {
  return (
    <LightboxShell title="Loading document" subtitle="Document viewer" onClose={onClose}>
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
        <HiRefresh className="h-5 w-5 animate-spin" />
        Loading document…
      </div>
    </LightboxShell>
  );
}

function DocumentPreviewModal({
  preview,
  onClose,
}: {
  preview: DocumentPreview;
  onClose: () => void;
}) {
  const title =
    preview.kind === "contract"
      ? preview.document.title
      : preview.kind === "policy"
        ? preview.policy.name
        : preview.title;
  const subtitle =
    preview.kind === "contract"
      ? "Contract document"
      : preview.kind === "policy"
        ? "Policy document"
        : "Invoice PDF";

  return (
    <LightboxShell
      title={title}
      subtitle={subtitle}
      onClose={onClose}
      dense={preview.kind === "invoice-pdf"}
    >
      {preview.kind === "contract" ? (
        <ContractPreview document={preview.document} />
      ) : preview.kind === "policy" ? (
        <PolicyPreview policy={preview.policy} />
      ) : (
        <InvoicePdfPreview uri={preview.uri} invoiceId={preview.invoiceId} title={title} />
      )}
    </LightboxShell>
  );
}

function ContractPreview({ document }: { document: ContractDocument }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <InfoTile label="Document ID" value={document.id} />
        <InfoTile label="Supplier ID" value={document.supplier_id} />
        <InfoTile label="Type" value={formatCategory(document.document_type)} />
        <InfoTile label="Effective" value={document.effective_date ?? "Not specified"} />
      </div>
      {document.text && document.text.trim() ? (
        <FullTextBlock text={document.text} />
      ) : (
        <DocumentUnavailable uri={document.uri} />
      )}
      <MetadataPreview metadata={document.metadata} />
    </>
  );
}

function PolicyPreview({ policy }: { policy: PolicyDocument }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-2 text-sm">
        <InfoTile label="Policy ID" value={policy.id} />
        <InfoTile label="Severity" value={formatCategory(policy.severity)} />
      </div>
      <p className="rounded-md bg-slate-50 p-3 text-sm leading-6 text-slate-700">
        {policy.description || "No policy description is available for this policy."}
      </p>
      {policy.text && policy.text.trim() ? <FullTextBlock text={policy.text} /> : null}
      <MetadataPreview metadata={policy.metadata} />
    </>
  );
}

function FullTextBlock({ text }: { text: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-100 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">
        Document content
      </div>
      <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap break-words px-4 py-3 font-sans text-sm leading-6 text-slate-700">
        {text}
      </pre>
    </div>
  );
}

function DocumentUnavailable({ uri }: { uri: string | null }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4">
      <p className="text-sm font-semibold text-slate-800">Document content not available here</p>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        The full document lives in the Waypoint corpus lake, which isn&apos;t connected in this
        environment. The reference below stays attached to this finding.
      </p>
      {uri ? (
        <p className="mt-3 break-all rounded-md bg-white p-3 font-mono text-xs text-slate-700">
          {cleanDocumentPath(uri)}
        </p>
      ) : null}
    </div>
  );
}

function InvoicePdfPreview({
  uri,
  invoiceId,
  title,
}: {
  uri: string;
  invoiceId: string;
  title: string;
}) {
  const [state, setState] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setState("loading");
    setObjectUrl(null);

    (async () => {
      try {
        const response = await tracedFetch(
          "fetchInvoicePdf",
          `/api/invoices/${encodeURIComponent(invoiceId)}/pdf`,
        );
        if (response.status === 404 || response.status === 409) {
          if (!cancelled) setState("unavailable");
          return;
        }
        if (!response.ok) {
          throw new Error(`Failed to load PDF: ${response.statusText}`);
        }
        const blob = await response.blob();
        createdUrl = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(createdUrl);
          return;
        }
        setObjectUrl(createdUrl);
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();

    return () => {
      cancelled = true;
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl);
      }
    };
  }, [invoiceId]);

  if (state === "loading") {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
        <HiRefresh className="h-5 w-5 animate-spin" />
        Loading PDF…
      </div>
    );
  }

  if (state === "ready" && objectUrl) {
    return (
      <iframe src={objectUrl} title={title} className="h-full w-full border-0 bg-slate-100" />
    );
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="max-w-md rounded-lg border border-dashed border-slate-300 bg-white p-5 text-center">
        <p className="text-sm font-semibold text-slate-800">
          {state === "unavailable"
            ? "PDF not available here"
            : "Couldn’t load this PDF"}
        </p>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {state === "unavailable"
            ? "The source PDF lives in the Waypoint corpus lake, which isn’t connected in this environment. The reference below stays attached to this finding."
            : "Something went wrong while loading the document. You can try reopening it."}
        </p>
        <p className="mt-3 inline-flex items-center gap-1.5 break-all rounded-md bg-slate-50 p-3 font-mono text-xs text-slate-700">
          <HiDownload className="h-3.5 w-3.5 shrink-0" />
          {cleanDocumentPath(uri)}
        </p>
      </div>
    </div>
  );
}

function MetadataPreview({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, value]) => value !== null && value !== "");
  if (entries.length === 0) {
    return null;
  }
  return (
    <div className="rounded-md border border-slate-100 p-3">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Metadata</p>
      <dl className="mt-2 space-y-2 text-sm">
        {entries.slice(0, 6).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[130px_minmax(0,1fr)] gap-3">
            <dt className="font-medium text-slate-500">{formatCategory(key)}</dt>
            <dd className="break-words text-slate-700">{formatMetadataValue(value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function decisionTrail(decision: InvoiceDecision, detail: InvoiceDetail | null) {
  if (!decision.has_agent_decision) {
    return [
      {
        title: "Assurance",
        detail: "No governed decision has been recorded for this invoice yet.",
      },
      {
        title: "Ingest",
        detail: `${detail?.lines.length ?? decision.metadata.line_count ?? 0} invoice lines imported through Waypoint.`,
      },
    ];
  }
  return [
    {
      title: "Decision",
      detail: `${decision.decision} · ${decision.category} · ${decision.overpayment_display}`,
    },
    {
      title: "Manufacturing context",
      detail: `${decision.supplier_name}${decision.scenario_name ? ` · ${decision.scenario_name}` : ""}`,
    },
    {
      title: "Contract / policy basis",
      detail: decision.basis_summary ?? `${decision.basis_types.length} basis types attached`,
    },
    {
      title: "Evidence",
      detail: `${decision.source} (${detail?.evidence.length ?? decision.evidence_count} references)`,
    },
    {
      title: "Ingest",
      detail: `${detail?.lines.length ?? decision.metadata.line_count ?? 0} invoice lines imported through Waypoint.`,
    },
  ];
}

function formatMoney(value: number) {
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatCurrency(value: string, currency = "USD") {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return value;
  }
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

function formatCategory(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatMetadataValue(value: unknown) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
}
