import type { MetaFunction } from "react-router";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import {
  HiCheck,
  HiCheckCircle,
  HiChevronRight,
  HiClipboardCopy,
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
import { useModalDialog } from "../hooks/useModalDialog";

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
  supports?: string;
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
  const [runConfirmOpen, setRunConfirmOpen] = useState(false);
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
    setRunConfirmOpen(false);
  }, [selectedDecision?.invoice_id]);

  useEffect(() => {
    if (!selectedDecision) {
      setInvoiceDetail(null);
    }
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
                    <h1 className="text-2xl font-semibold tracking-tight">
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
                    <thead className="sticky top-0 z-10 bg-slate-50 type-label shadow-[0_1px_0_rgba(0,0,0,0.06)]">
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
                              <span className="mt-0.5 block truncate type-meta">
                                {row.supplier_name}
                              </span>
                            ) : null}
                            {row.has_agent_decision && row.agent_run_count > 0 ? (
                              <span className="mt-0.5 flex flex-col type-meta font-normal">
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
                              <span className="mt-0.5 flex items-center gap-1 whitespace-nowrap text-xs font-normal text-indigo-600">
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
                              ? <span className="text-slate-500">—</span>
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
                onRunAssurance={() => {
                  setTriggerError(null);
                  setRunConfirmOpen(true);
                }}
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

            {selectedDecision && runConfirmOpen ? (
              <RunAssuranceConfirmation
                decision={selectedDecision}
                runCount={agentContext?.entries.length || selectedDecision.agent_run_count}
                triggering={triggeringInvoiceId === selectedDecision.invoice_id}
                error={triggerError}
                onConfirm={() => void triggerAssurance(selectedDecision)}
                onClose={() => setRunConfirmOpen(false)}
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useModalDialog(dialogRef, { onClose, initialFocusRef: confirmRef, canClose: !loading });

  return (
    <div
      ref={dialogRef}
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
            <h2 id="batch-assurance-title" className="text-xl font-semibold">
              Start assurance for {rows.length} invoice{rows.length === 1 ? "" : "s"}?
            </h2>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-500 hover:bg-slate-50 disabled:opacity-50"
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
            ref={confirmRef}
            onClick={onConfirm}
            disabled={loading}
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
          <span className="type-label">Decision</span>
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
            className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Search invoice or supplier…"
            className="min-h-8 w-48 rounded-md border border-slate-200 bg-white py-1 pl-7 pr-2 text-xs text-slate-700 placeholder:text-slate-500 focus:border-blue-300 focus:outline-none"
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
      className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ring-1 transition-colors ${
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
        <h2 className="type-section">Decision mix</h2>
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
          <p className="mt-2 type-meta">No decisions in view.</p>
        )}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <h2 className="type-section">Recovery by supplier</h2>
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
          <p className="mt-2 type-meta">No recoverable overpayment in view.</p>
        )}
      </section>

      {severityBreakdown.length > 0 ? (
        <section className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <h2 className="type-section">Severity</h2>
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
          <h2 className="type-section">Top overpayments</h2>
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
                      <span className="block truncate type-meta">
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
          <div className="flex items-center justify-between">
            <h2 className="type-section">Recovery trend</h2>
            <span className="type-meta">{trend.length} days</span>
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

type PlaneKey = "foundryiq" | "fabriciq" | "workiq" | "webiq";

const PLANE_LABELS: Record<string, string> = {
  workiq: "WorkIQ",
  webiq: "WebIQ",
  foundryiq: "FoundryIQ",
  fabriciq: "FabricIQ",
};

// The four IQ planes in the order an auditor reads them: terms first, then the
// operational record, then people, then the outside world.
const IQ_PLANES: Array<{ key: PlaneKey; label: string; scope: string }> = [
  { key: "foundryiq", label: "FoundryIQ", scope: "Contract terms and finance policy" },
  { key: "fabriciq", label: "FabricIQ", scope: "PO, batch and release data in OneLake" },
  { key: "workiq", label: "WorkIQ", scope: "Your Microsoft 365 mail, Teams and files" },
  { key: "webiq", label: "WebIQ", scope: "Public market and regulatory sources" },
];

const AGENT_PLANES: Record<string, PlaneKey> = {
  "contract-policy-expert": "foundryiq",
  "operations-data-expert": "fabriciq",
  "collaboration-evidence-expert": "workiq",
  "market-evidence-expert": "webiq",
  contract: "foundryiq",
  policy: "foundryiq",
};

function planeLabel(lane: FanoutLane): string {
  const key = (lane.plane ?? lane.agent ?? "").toLowerCase().replace(/-expert$/, "");
  return PLANE_LABELS[key] ?? formatCategory(lane.agent || lane.plane || "Expert");
}

function lanePlaneKey(lane: FanoutLane): PlaneKey | null {
  const plane = (lane.plane ?? "").toLowerCase();
  if (plane in PLANE_LABELS) {
    return plane as PlaneKey;
  }
  const agent = (lane.agent ?? "").toLowerCase();
  const mapped = AGENT_PLANES[agent] ?? AGENT_PLANES[plane];
  if (mapped) {
    return mapped;
  }
  const stripped = agent.replace(/-expert$/, "");
  return stripped in PLANE_LABELS ? (stripped as PlaneKey) : null;
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

function parseConfidenceScore(confidence: string | number | null | undefined): number | null {
  if (confidence === null || confidence === undefined || confidence === "") {
    return null;
  }
  const score = Number(confidence);
  return Number.isFinite(score) ? score : null;
}

function confidenceTitle(calibrated: boolean): string {
  return calibrated
    ? "Calibrated decision confidence."
    : "Uncalibrated evidence score; not calibrated decision accuracy.";
}

function formatAgentMoney(value: string | undefined): string {
  const amount = Number(value ?? 0);
  return `$${(Number.isFinite(amount) ? amount : 0).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function agentDecisionToLabel(decision: string): string {
  const normalized = decision.toLowerCase();
  if (normalized === "recover" || normalized === "recovery") return "Recover";
  if (normalized === "escalate") return "Escalate";
  if (normalized === "approve") return "Approve";
  if (normalized === "review") return "Review";
  return decision ? decision.charAt(0).toUpperCase() + decision.slice(1) : decision;
}

function formatRunDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatRunTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
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

const primaryButton =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-blue-600 px-3.5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-wait disabled:opacity-60";
const secondaryButton =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3.5 py-2 text-sm font-semibold text-slate-800 shadow-sm transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60";

interface BasisDocument {
  type: "contract" | "policy";
  id: string;
  title: string;
}

function fallbackDocumentTitle(id: string): string {
  return formatCategory(id.replace(/^(contract|policy)-(sup-\d+-)?/, ""));
}

function matchBasisDocument(ref: string, documents: BasisDocument[]): BasisDocument | null {
  const haystack = ref.toLowerCase();
  return (
    documents.find(
      (document) =>
        haystack.includes(document.id.toLowerCase()) ||
        haystack.includes(document.title.toLowerCase()),
    ) ?? null
  );
}

function DecisionDrawer({
  decision,
  detail,
  loading,
  agentContext,
  agentLoading,
  triggering,
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
  onRunAssurance: () => void;
  onViewActivity: () => void;
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
  onOpenPdf: (uri: string) => void;
  onClose: () => void;
}) {
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  useEffect(() => {
    setSelectedCaseId(null);
  }, [decision.invoice_id]);

  const finding = decision.has_agent_decision ? detail?.findings[0] : undefined;
  const contractIds = finding?.contract_document_ids ?? decision.contract_document_ids;
  const policyIds = finding?.policy_ids ?? decision.policy_ids;
  const basisKey = `${contractIds.join("|")}::${policyIds.join("|")}`;
  const [documentTitles, setDocumentTitles] = useState<Record<string, string>>({});

  useEffect(() => {
    const requests: Array<["contract" | "policy", string]> = [
      ...contractIds.map((id): ["contract", string] => ["contract", id]),
      ...policyIds.map((id): ["policy", string] => ["policy", id]),
    ];
    if (requests.length === 0) {
      setDocumentTitles({});
      return;
    }
    let cancelled = false;
    void Promise.all(
      requests.map(async ([type, id]) => {
        try {
          const response = await tracedFetch(
            "fetchBasisDocumentTitle",
            type === "contract"
              ? `/api/contract-documents/${encodeURIComponent(id)}`
              : `/api/policies/${encodeURIComponent(id)}`,
          );
          if (!response.ok) {
            return null;
          }
          const body = (await response.json()) as { title?: string; name?: string };
          const title = type === "contract" ? body.title : body.name;
          return title ? ([id, title] as const) : null;
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (!cancelled) {
        setDocumentTitles(
          Object.fromEntries(
            results.filter((entry): entry is readonly [string, string] => entry !== null),
          ),
        );
      }
    });
    return () => {
      cancelled = true;
    };
    // basisKey captures the id lists; the arrays themselves are rebuilt every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basisKey]);

  const basisDocuments: BasisDocument[] = [
    ...contractIds.map((id) => ({
      type: "contract" as const,
      id,
      title: documentTitles[id] ?? fallbackDocumentTitle(id),
    })),
    ...policyIds.map((id) => ({
      type: "policy" as const,
      id,
      title: documentTitles[id] ?? fallbackDocumentTitle(id),
    })),
  ];

  const entries = agentContext?.entries ?? [];
  const selectedEntry =
    entries.find((entry) => entry.case.id === selectedCaseId) ?? entries[0] ?? null;
  const newestEntry = entries[0] ?? null;
  const viewingOlderRun = Boolean(selectedEntry && newestEntry && selectedEntry !== newestEntry);
  const recommendation = selectedEntry?.recommendation ?? null;
  const fanout = selectedEntry?.fanout ?? [];
  const drafts = selectedEntry?.drafts ?? [];

  const verdictKey = (
    recommendation?.decision ??
    selectedEntry?.run?.metadata?.decision ??
    decision.agent_decision ??
    decision.decision
  ).toLowerCase();
  const verdictLabel = agentDecisionToLabel(verdictKey);
  const amount = recommendation
    ? formatAgentMoney(recommendation.money_at_risk)
    : formatAgentMoney(decision.overpayment_amount);
  const confidenceScore = parseConfidenceScore(
    recommendation ? recommendation.confidence : decision.confidence,
  );
  const calibrated = recommendation
    ? recommendation.metadata.confidence_calibrated === true
    : decision.confidence_calibrated;
  const decidedAt = recommendation?.created_at ?? decision.agent_run_at;
  const runTotal = entries.length || decision.agent_run_count;
  const runNumber = selectedEntry
    ? entries.length - entries.indexOf(selectedEntry)
    : (decision.agent_run_index ?? runTotal);
  const runId =
    recommendation?.metadata?.waypoint_run_id ?? selectedEntry?.run?.id ?? null;
  const reasoning = recommendation?.reasoning || finding?.summary || decision.reasoning;
  const invoiceTotal = detail ? formatCurrency(detail.total_amount, detail.currency) : null;

  const hasDecision = decision.has_agent_decision;
  const activeRun = decision.has_active_run;
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useModalDialog(dialogRef, { onClose, initialFocusRef: headingRef });

  return (
    <div
      ref={dialogRef}
      className="absolute inset-0 z-30 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-labelledby="decision-drawer-title"
      aria-describedby="decision-drawer-subtitle"
    >
      {/* Pointer-only backdrop; keyboard users close with Escape or the Close button. */}
      <div
        className="absolute inset-0 cursor-default bg-slate-950/20"
        aria-hidden="true"
        onClick={onClose}
      />
      {/* An unnamed <section> keeps the header/footer below from becoming page landmarks. */}
      <section className="relative z-10 flex h-full w-full max-w-[520px] flex-col overflow-hidden border-l border-slate-200 bg-white shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <div className="min-w-0">
            <h2
              ref={headingRef}
              id="decision-drawer-title"
              tabIndex={-1}
              className="truncate rounded-sm text-lg font-semibold text-slate-950 focus-visible:outline-offset-0"
            >
              <span className="sr-only">Decision context for invoice </span>
              {decision.invoice_number}
            </h2>
            <p id="decision-drawer-subtitle" className="truncate text-sm text-slate-600">
              {decision.supplier_name}
              {invoiceTotal ? ` · ${invoiceTotal} invoiced` : ""}
            </p>
          </div>
          <button
            className="-mr-1.5 shrink-0 rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
            type="button"
            onClick={onClose}
          >
            <HiX className="h-5 w-5" aria-hidden="true" />
            <span className="sr-only">Close decision context</span>
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          {hasDecision ? (
            <>
              <section
                aria-labelledby="case-verdict"
                className="border-b border-slate-200 bg-slate-50 px-5 pb-5 pt-4"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <DecisionPill decision={verdictLabel} />
                  {decision.category ? (
                    <span className="text-xs text-slate-600">
                      {formatCategory(decision.category)}
                    </span>
                  ) : null}
                </div>
                <h3
                  id="case-verdict"
                  className="mt-2 text-balance text-xl font-semibold leading-snug tracking-tight text-slate-950 sm:text-2xl"
                >
                  <VerdictHeadline
                    verdict={verdictKey}
                    label={verdictLabel}
                    amount={amount}
                    supplier={decision.supplier_name}
                    invoiceTotal={invoiceTotal}
                  />
                </h3>
                {reasoning ? (
                  <p className="mt-2 max-w-[65ch] text-sm leading-6 text-slate-700">{reasoning}</p>
                ) : null}

                {viewingOlderRun && newestEntry ? (
                  <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-inset ring-amber-200">
                    You're viewing an older run. The current decision is Run {entries.length}:{" "}
                    {agentDecisionToLabel(
                      newestEntry.recommendation?.decision ??
                        newestEntry.run?.metadata?.decision ??
                        "",
                    ) || "pending"}
                    .
                  </p>
                ) : null}

                <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-slate-200 pt-3 text-sm">
                  <div className="min-w-0">
                    <dt className="text-xs text-slate-600">Confidence</dt>
                    <dd
                      className="mt-0.5 font-semibold tabular-nums text-slate-950"
                      title={confidenceScore === null ? undefined : confidenceTitle(calibrated)}
                    >
                      {confidenceScore === null ? "Not reported" : `${Math.round(confidenceScore * 100)}%`}
                    </dd>
                    {confidenceScore !== null ? (
                      <dd className="text-xs text-slate-600">
                        {calibrated ? "Calibrated" : "Evidence score, not calibrated"}
                      </dd>
                    ) : null}
                  </div>
                  <div className="min-w-0">
                    <dt className="text-xs text-slate-600">Decided</dt>
                    <dd className="mt-0.5 font-semibold text-slate-950">
                      {decidedAt ? formatRunDate(decidedAt) : "Not recorded"}
                    </dd>
                    {decidedAt ? (
                      <dd className="text-xs text-slate-600">{formatRunTime(decidedAt)}</dd>
                    ) : null}
                  </div>
                  <div className="min-w-0">
                    <dt className="text-xs text-slate-600">Run</dt>
                    <dd className="mt-0.5 font-semibold text-slate-950">
                      {runTotal > 0 ? `Run ${runNumber} of ${runTotal}` : "Not recorded"}
                    </dd>
                    {runId ? (
                      <dd className="truncate font-mono text-xs text-slate-600" title={runId}>
                        {runId}
                      </dd>
                    ) : null}
                  </div>
                </dl>

                {entries.length > 1 && selectedEntry ? (
                  <RunSwitcher
                    entries={entries}
                    selectedCaseId={selectedEntry.case.id}
                    onSelectCase={setSelectedCaseId}
                  />
                ) : null}
              </section>

              {agentLoading ? (
                <p className="px-5 py-6 text-sm text-slate-600">Loading clauses and evidence…</p>
              ) : (
                <>
                  <ClauseSection
                    basisSummary={finding?.basis_summary ?? decision.basis_summary}
                    fanout={fanout}
                    verdict={verdictKey}
                    documents={basisDocuments}
                    onOpenDocument={onOpenDocument}
                  />
                  <EvidenceSection
                    fanout={fanout}
                    verdict={verdictKey}
                    records={loading ? [] : (detail?.evidence ?? [])}
                    documents={basisDocuments}
                    onOpenDocument={onOpenDocument}
                  />
                  <SupplierSection
                    verdict={verdictKey}
                    supplier={decision.supplier_name}
                    drafts={drafts}
                  />
                  <NextStepSection
                    verdict={verdictKey}
                    amount={amount}
                    supplier={decision.supplier_name}
                    recommendation={recommendation}
                    drafts={drafts}
                    pdfUri={decision.pdf_uri}
                    basisDocuments={basisDocuments}
                    onOpenPdf={onOpenPdf}
                    onOpenDocument={onOpenDocument}
                  />
                </>
              )}
            </>
          ) : (
            <NotRunCase
              activeRun={activeRun}
              triggering={triggering}
              onRunAssurance={onRunAssurance}
              onViewActivity={onViewActivity}
            />
          )}

          <InvoiceRecordDetails
            decision={decision}
            detail={detail}
            finding={finding}
            loading={loading}
            onOpenPdf={onOpenPdf}
          />
        </div>

        {hasDecision ? (
          <footer className="flex items-center justify-between gap-3 border-t border-slate-200 bg-white px-5 py-3">
            <p className="min-w-0 text-xs text-slate-600">
              {activeRun
                ? "A new assurance run is in progress."
                : "A re-run opens a new case. Earlier runs stay in the history."}
            </p>
            {activeRun ? (
              <button
                type="button"
                onClick={onViewActivity}
                className={`${secondaryButton} shrink-0 whitespace-nowrap`}
              >
                View active run
                <HiExternalLink className="h-4 w-4" aria-hidden="true" />
              </button>
            ) : (
              <button
                type="button"
                onClick={onRunAssurance}
                disabled={triggering}
                className={`${secondaryButton} shrink-0 whitespace-nowrap`}
              >
                <HiRefresh
                  className={triggering ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                  aria-hidden="true"
                />
                {triggering ? "Starting…" : "Re-run assurance…"}
              </button>
            )}
          </footer>
        ) : null}
      </section>
    </div>
  );
}

function VerdictHeadline({
  verdict,
  label,
  amount,
  supplier,
  invoiceTotal,
}: {
  verdict: string;
  label: string;
  amount: string;
  supplier: string;
  invoiceTotal: string | null;
}) {
  const money = <span className="tabular-nums">{amount}</span>;
  switch (verdict) {
    case "recover":
    case "recovery":
      return (
        <>
          Recover {money} from {supplier}
        </>
      );
    case "escalate":
      return <>Escalate {money} before payment</>;
    case "review":
      return <>Hold {money} for human review</>;
    case "approve":
      return invoiceTotal ? (
        <>
          Approve <span className="tabular-nums">{invoiceTotal}</span> for payment
        </>
      ) : (
        <>Approve for payment</>
      );
    default:
      return (
        <>
          {label}: {money} at risk
        </>
      );
  }
}

function RunSwitcher({
  entries,
  selectedCaseId,
  onSelectCase,
}: {
  entries: AgentCaseEntry[];
  selectedCaseId: string;
  onSelectCase: (caseId: string) => void;
}) {
  const count = entries.length;
  return (
    <div className="mt-3">
      <p id="run-switcher-label" className="text-xs text-slate-600">
        {count} runs on this invoice, newest first
      </p>
      <div
        className="mt-1.5 flex flex-wrap gap-1.5"
        role="radiogroup"
        aria-labelledby="run-switcher-label"
      >
        {entries.map((entry, index) => {
          const active = entry.case.id === selectedCaseId;
          const runDecision = (
            entry.recommendation?.decision ??
            entry.run?.metadata?.decision ??
            ""
          ).toLowerCase();
          return (
            <button
              key={entry.case.id}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onSelectCase(entry.case.id)}
              title={formatRunDateTime(entry.case.created_at)}
              className={[
                "inline-flex min-h-8 items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs transition-colors",
                active
                  ? "border-blue-300 bg-white text-blue-900 ring-1 ring-blue-200"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-100",
              ].join(" ")}
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: decisionColor(agentDecisionToLabel(runDecision)) }}
                aria-hidden="true"
              />
              <span className="font-semibold">Run {count - index}</span>
              {runDecision ? <span>{agentDecisionToLabel(runDecision)}</span> : null}
              {index === 0 ? <span className="text-slate-600">· current</span> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function CaseSection({
  id,
  title,
  meta,
  children,
}: {
  id: string;
  title: string;
  meta?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="border-b border-slate-200 px-5 py-5">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id={id} className="text-base font-semibold text-slate-950">
          {title}
        </h3>
        {meta ? <span className="shrink-0 text-xs text-slate-600">{meta}</span> : null}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function StanceTag({ supports, verdict }: { supports?: string; verdict: string }) {
  if (!supports) {
    return null;
  }
  const stance = supports.toLowerCase();
  if (stance === "governs") {
    return (
      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
        Governing term
      </span>
    );
  }
  const agrees = agentDecisionToLabel(stance) === agentDecisionToLabel(verdict);
  return agrees ? (
    <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium text-slate-700">
      Supports {agentDecisionToLabel(stance).toLowerCase()}
    </span>
  ) : (
    <span className="rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-900 ring-1 ring-inset ring-amber-200">
      Points to {agentDecisionToLabel(stance).toLowerCase()}
    </span>
  );
}

function SourceReference({
  sourceRef,
  documents,
  onOpenDocument,
}: {
  sourceRef: string;
  documents: BasisDocument[];
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
}) {
  const cleaned = cleanSourceRef(sourceRef);
  if (/^https?:\/\//i.test(cleaned)) {
    let label = cleaned;
    try {
      const url = new URL(cleaned);
      label = `${url.hostname}${url.pathname === "/" ? "" : url.pathname}`;
    } catch {
      // Keep the raw reference when it isn't a parseable URL.
    }
    return (
      <a
        href={cleaned}
        target="_blank"
        rel="noreferrer"
        className="inline-flex max-w-full items-center gap-1 break-all font-medium text-blue-700 hover:text-blue-900 hover:underline"
      >
        {label}
        <HiExternalLink className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      </a>
    );
  }
  const match = matchBasisDocument(cleaned, documents);
  if (match) {
    return (
      <button
        type="button"
        onClick={() => onOpenDocument(match.type, match.id)}
        className="text-left font-medium text-blue-700 hover:text-blue-900 hover:underline"
      >
        {cleaned}
      </button>
    );
  }
  return <span className="font-medium text-slate-700">{cleaned}</span>;
}

function CitationItem({
  item,
  verdict,
  documents,
  onOpenDocument,
  quote = false,
}: {
  item: FanoutEvidenceItem;
  verdict: string;
  documents: BasisDocument[];
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
  quote?: boolean;
}) {
  return (
    <li className="py-2.5">
      <p className="text-sm leading-6 text-slate-800">
        {item.claim ? (quote ? `“${item.claim}”` : item.claim) : "(no citation text)"}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-600">
        {item.source_ref ? (
          <SourceReference
            sourceRef={item.source_ref}
            documents={documents}
            onOpenDocument={onOpenDocument}
          />
        ) : null}
        <StanceTag supports={item.supports} verdict={verdict} />
        {typeof item.confidence === "number" ? (
          <span className="tabular-nums">{Math.round(item.confidence * 100)}% confidence</span>
        ) : null}
      </div>
    </li>
  );
}

function ClauseSection({
  basisSummary,
  fanout,
  verdict,
  documents,
  onOpenDocument,
}: {
  basisSummary: string | null;
  fanout: FanoutLane[];
  verdict: string;
  documents: BasisDocument[];
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
}) {
  const clauses = fanout
    .filter((lane) => lanePlaneKey(lane) === "foundryiq")
    .flatMap((lane) => lane.evidence ?? []);
  const empty = !basisSummary && clauses.length === 0 && documents.length === 0;

  return (
    <CaseSection
      id="case-clauses"
      title="Contract and policy basis"
      meta={
        clauses.length > 0
          ? `${clauses.length} clause${clauses.length === 1 ? "" : "s"} cited`
          : undefined
      }
    >
      {empty ? (
        <p className="text-sm leading-6 text-slate-600">
          No contract or policy basis is attached to this decision. Treat it as unsupported until
          a reviewer ties it to a clause.
        </p>
      ) : (
        <>
          {basisSummary ? (
            <p className="text-sm leading-6 text-slate-700">{basisSummary}</p>
          ) : null}
          {clauses.length > 0 ? (
            <ol className="mt-1 divide-y divide-slate-100">
              {clauses.map((item, index) => (
                <CitationItem
                  key={`${item.source_ref ?? "clause"}-${index}`}
                  item={item}
                  verdict={verdict}
                  documents={documents}
                  onOpenDocument={onOpenDocument}
                  quote
                />
              ))}
            </ol>
          ) : (
            <p className="mt-2 text-sm leading-6 text-slate-600">
              FoundryIQ didn't record clause-level citations for this run. The documents below
              are the basis on file.
            </p>
          )}
          {documents.length > 0 ? (
            <ul className="mt-3 divide-y divide-slate-100 rounded-md border border-slate-200">
              {documents.map((document) => (
                <li key={`${document.type}-${document.id}`}>
                  <button
                    type="button"
                    onClick={() => onOpenDocument(document.type, document.id)}
                    className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-slate-50"
                  >
                    <HiDocumentText
                      className={
                        document.type === "contract"
                          ? "h-4 w-4 shrink-0 text-indigo-700"
                          : "h-4 w-4 shrink-0 text-cyan-700"
                      }
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-900">
                        {document.title}
                      </span>
                      <span className="block text-xs text-slate-600">
                        {document.type === "contract" ? "Contract" : "Policy"}
                      </span>
                    </span>
                    <span className="shrink-0 text-xs font-semibold text-blue-700">Open</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </CaseSection>
  );
}

function EvidenceSection({
  fanout,
  verdict,
  records,
  documents,
  onOpenDocument,
}: {
  fanout: FanoutLane[];
  verdict: string;
  records: EvidenceReference[];
  documents: BasisDocument[];
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
}) {
  const byPlane = new Map<PlaneKey, FanoutLane[]>();
  const other = new Map<string, FanoutLane[]>();
  for (const lane of fanout) {
    const key = lanePlaneKey(lane);
    if (key) {
      byPlane.set(key, [...(byPlane.get(key) ?? []), lane]);
    } else {
      const label = planeLabel(lane);
      other.set(label, [...(other.get(label) ?? []), lane]);
    }
  }
  const citationTotal = fanout.reduce((sum, lane) => sum + (lane.evidence?.length ?? 0), 0);
  const planesUsed = byPlane.size + other.size;

  return (
    <CaseSection
      id="case-evidence"
      title="Evidence by source"
      meta={
        citationTotal > 0
          ? `${citationTotal} citation${citationTotal === 1 ? "" : "s"} · ${planesUsed} source${planesUsed === 1 ? "" : "s"}`
          : undefined
      }
    >
      <div className="divide-y divide-slate-200 border-t border-slate-200">
        {IQ_PLANES.map((plane) => {
          const lanes = byPlane.get(plane.key) ?? [];
          const items = lanes.flatMap((lane) => lane.evidence ?? []);
          const summary = lanes.map((lane) => lane.summary).filter(Boolean).join(" ");
          return (
            <EvidenceGroup
              key={plane.key}
              label={plane.label}
              scope={plane.scope}
              count={items.length}
            >
              {lanes.length === 0 ? (
                <p className="text-sm text-slate-600">Nothing recorded for this run.</p>
              ) : plane.key === "foundryiq" ? (
                <p className="text-sm leading-6 text-slate-600">
                  {summary ? `${summary} ` : ""}
                  {items.length > 0
                    ? "Clauses are listed under Contract and policy basis."
                    : "No clause-level citations recorded."}
                </p>
              ) : (
                <>
                  {summary ? <p className="text-sm leading-6 text-slate-600">{summary}</p> : null}
                  {items.length > 0 ? (
                    <ul className="divide-y divide-slate-100">
                      {items.map((item, index) => (
                        <CitationItem
                          key={`${item.source_ref ?? "evidence"}-${index}`}
                          item={item}
                          verdict={verdict}
                          documents={documents}
                          onOpenDocument={onOpenDocument}
                        />
                      ))}
                    </ul>
                  ) : null}
                </>
              )}
            </EvidenceGroup>
          );
        })}
        {Array.from(other.entries()).map(([label, lanes]) => {
          const items = lanes.flatMap((lane) => lane.evidence ?? []);
          const summary = lanes.map((lane) => lane.summary).filter(Boolean).join(" ");
          return (
            <EvidenceGroup key={label} label={label} scope="Third-party source" count={items.length}>
              {summary ? <p className="text-sm leading-6 text-slate-600">{summary}</p> : null}
              <ul className="divide-y divide-slate-100">
                {items.map((item, index) => (
                  <CitationItem
                    key={`${item.source_ref ?? "evidence"}-${index}`}
                    item={item}
                    verdict={verdict}
                    documents={documents}
                    onOpenDocument={onOpenDocument}
                  />
                ))}
              </ul>
            </EvidenceGroup>
          );
        })}
        {records.length > 0 ? (
          <EvidenceGroup
            label="Invoice records"
            scope="Records attached to the finding"
            count={records.length}
            noun="record"
          >
            <ul className="divide-y divide-slate-100">
              {records.map((record) => (
                <li key={record.id} className="py-2.5">
                  <p className="text-sm font-medium text-slate-800">{record.title}</p>
                  {record.excerpt ? (
                    <p className="mt-0.5 text-sm leading-6 text-slate-700">{record.excerpt}</p>
                  ) : null}
                  <p className="mt-1 text-xs text-slate-600">
                    {formatCategory(record.evidence_type)}
                  </p>
                  <DocumentLink label="Open record" uri={record.uri} compact />
                </li>
              ))}
            </ul>
          </EvidenceGroup>
        ) : null}
      </div>
    </CaseSection>
  );
}

function EvidenceGroup({
  label,
  scope,
  count,
  noun = "citation",
  children,
}: {
  label: string;
  scope: string;
  count: number;
  noun?: string;
  children: ReactNode;
}) {
  return (
    <div className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-sm">
          <span className="font-semibold text-slate-950">{label}</span>
          <span className="text-slate-600"> · {scope}</span>
        </p>
        {count > 0 ? (
          <span className="shrink-0 text-xs tabular-nums text-slate-600">
            {count} {noun}
            {count === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function CopyButton({
  text,
  label,
  variant = "secondary",
}: {
  text: string;
  label: string;
  variant?: "primary" | "secondary";
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  useEffect(() => {
    if (state === "idle") {
      return;
    }
    const timer = window.setTimeout(() => setState("idle"), 2400);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  };

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={variant === "primary" ? primaryButton : secondaryButton}
    >
      {state === "copied" ? (
        <HiCheck className="h-4 w-4" aria-hidden="true" />
      ) : (
        <HiClipboardCopy className="h-4 w-4" aria-hidden="true" />
      )}
      <span aria-live="polite">
        {state === "copied"
          ? "Copied"
          : state === "failed"
            ? "Couldn't copy. Select the text instead."
            : label}
      </span>
    </button>
  );
}

function SupplierSection({
  verdict,
  supplier,
  drafts,
}: {
  verdict: string;
  supplier: string;
  drafts: CaseDraft[];
}) {
  const draft = drafts.find((candidate) => candidate.draft_type === "supplier_dispute") ?? null;

  return (
    <CaseSection id="case-supplier" title={`For ${supplier}`}>
      {draft ? (
        <>
          <p className="text-sm font-semibold text-slate-900">{draft.title}</p>
          <blockquote className="mt-2 whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-6 text-slate-800">
            {draft.body}
          </blockquote>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
            <CopyButton text={draft.body} label="Copy paragraph" />
            <p className="text-xs text-slate-600">
              Drafted by {draft.created_by} on {formatRunDateTime(draft.created_at)}. Read it
              before you send it.
            </p>
          </div>
        </>
      ) : verdict === "approve" ? (
        <p className="text-sm leading-6 text-slate-600">
          Nothing to send. Approved invoices don't need a supplier message.
        </p>
      ) : (
        <p className="text-sm leading-6 text-slate-600">
          No supplier draft was written for this run. The reasoning at the top is for reviewers,
          not the supplier. If you dispute the line, write your message from the clauses above.
        </p>
      )}
    </CaseSection>
  );
}

const NEXT_STEPS: Record<string, { title: (supplier: string, amount: string) => string; body: string }> = {
  recover: {
    title: (supplier, amount) => `Request a ${amount} credit from ${supplier}`,
    body: "Copy the paragraph above into an email from your supplier mailbox, attach the invoice PDF, then record the credit in AP.",
  },
  review: {
    title: (_supplier, amount) => `Hold ${amount} and make the call`,
    body: "The agents couldn't settle this one. Read the clauses and the evidence that points the other way, then approve or dispute the line.",
  },
  escalate: {
    title: (_supplier, amount) => `Hold ${amount} and escalate`,
    body: "Don't pay or dispute this line yet. Send the escalation packet to the owner named in the dispute procedure.",
  },
  approve: {
    title: () => "Release for payment",
    body: "The invoice reconciles to the contract and operations data. Nothing to recover.",
  },
};

function NextStepSection({
  verdict,
  amount,
  supplier,
  recommendation,
  drafts,
  pdfUri,
  basisDocuments,
  onOpenPdf,
  onOpenDocument,
}: {
  verdict: string;
  amount: string;
  supplier: string;
  recommendation: CaseRecommendation | null;
  drafts: CaseDraft[];
  pdfUri: string | null;
  basisDocuments: BasisDocument[];
  onOpenPdf: (uri: string) => void;
  onOpenDocument: (type: "contract" | "policy", id: string) => void;
}) {
  const key = verdict === "recovery" ? "recover" : verdict;
  const step = NEXT_STEPS[key];
  const escalationDraft = drafts.find((draft) => draft.draft_type === "escalation_packet");
  const reviewerNotes = drafts.filter((draft) => draft.draft_type !== "supplier_dispute");
  const proposed = recommendation?.proposed_next_actions ?? [];
  const contract = basisDocuments.find((document) => document.type === "contract");

  let primary: ReactNode = null;
  if (key === "escalate" && escalationDraft) {
    primary = (
      <CopyButton text={escalationDraft.body} label="Copy escalation packet" variant="primary" />
    );
  } else if (key === "review" && contract) {
    primary = (
      <button
        type="button"
        className={primaryButton}
        onClick={() => onOpenDocument(contract.type, contract.id)}
      >
        <HiDocumentText className="h-4 w-4" aria-hidden="true" />
        Open the contract
      </button>
    );
  }

  return (
    <CaseSection id="case-next-step" title="Your next step">
      <p className="text-base font-semibold text-slate-950">
        {step ? step.title(supplier, amount) : `Decide what to do with ${amount}`}
      </p>
      <p className="mt-1 max-w-[65ch] text-sm leading-6 text-slate-700">
        {step ? step.body : "Read the clauses and evidence above before acting."}
      </p>
      {proposed.length > 0 ? (
        <p className="mt-2 text-sm text-slate-700">
          <span className="text-slate-600">Agent proposed: </span>
          {proposed.map(formatActionLabel).join(", ")}.
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {primary}
        {pdfUri ? (
          <button
            type="button"
            className={primary ? secondaryButton : primaryButton}
            onClick={() => onOpenPdf(pdfUri)}
          >
            <HiDocumentText className="h-4 w-4" aria-hidden="true" />
            Open invoice PDF
          </button>
        ) : null}
      </div>
      <p className="mt-3 text-xs text-slate-600">
        Waypoint records the case. It doesn't send email or post approvals from this panel.
      </p>
      {reviewerNotes.length > 0 ? (
        <details className="group mt-3 border-t border-slate-200 pt-3">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-semibold text-slate-800">
            <HiChevronRight
              className="h-4 w-4 text-slate-500 transition-transform group-open:rotate-90"
              aria-hidden="true"
            />
            Reviewer notes ({reviewerNotes.length})
          </summary>
          <ul className="mt-2 space-y-3">
            {reviewerNotes.map((draft) => (
              <li key={draft.id}>
                <p className="text-sm font-medium text-slate-900">{draft.title}</p>
                <p className="text-xs text-slate-600">{formatCategory(draft.draft_type)}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                  {draft.body}
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </CaseSection>
  );
}

function NotRunCase({
  activeRun,
  triggering,
  onRunAssurance,
  onViewActivity,
}: {
  activeRun: boolean;
  triggering: boolean;
  onRunAssurance: () => void;
  onViewActivity: () => void;
}) {
  if (activeRun) {
    return (
      <section aria-labelledby="case-verdict" className="border-b border-slate-200 px-5 py-6">
        <DecisionPill decision="Pending" />
        <h3 id="case-verdict" className="mt-2 text-xl font-semibold text-slate-950 sm:text-2xl">
          Agents are working on this invoice
        </h3>
        <p className="mt-2 max-w-[65ch] text-sm leading-6 text-slate-700">
          The case appears here once the run records a decision. Follow each expert's progress in
          Activity.
        </p>
        <button type="button" onClick={onViewActivity} className={`mt-4 ${primaryButton}`}>
          View active run
          <HiExternalLink className="h-4 w-4" aria-hidden="true" />
        </button>
      </section>
    );
  }

  return (
    <section aria-labelledby="case-verdict" className="border-b border-slate-200 px-5 py-6">
      <DecisionPill decision="Not run" />
      <h3 id="case-verdict" className="mt-2 text-xl font-semibold text-slate-950 sm:text-2xl">
        No decision yet
      </h3>
      <p className="mt-2 max-w-[65ch] text-sm leading-6 text-slate-700">
        Running assurance sends this invoice to the cloud agent pipeline. Four experts check it
        against their sources, then Waypoint records one decision: approve, review, recover or
        escalate.
      </p>
      <ul className="mt-4 divide-y divide-slate-200 border-y border-slate-200">
        {IQ_PLANES.map((plane) => (
          <li key={plane.key} className="flex items-baseline justify-between gap-4 py-2 text-sm">
            <span className="font-semibold text-slate-950">{plane.label}</span>
            <span className="text-right text-slate-700">{plane.scope}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 max-w-[65ch] text-sm leading-6 text-slate-700">
        You'll get the verdict and amount, the clauses it rests on, evidence by source, a
        paragraph for the supplier when there's something to send, and your next step.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <button
          type="button"
          onClick={onRunAssurance}
          disabled={triggering}
          className={primaryButton}
        >
          <HiSparkles
            className={triggering ? "h-4 w-4 animate-pulse" : "h-4 w-4"}
            aria-hidden="true"
          />
          {triggering ? "Starting assurance…" : "Run assurance…"}
        </button>
        <p className="text-xs text-slate-600">Can take several minutes. You'll confirm first.</p>
      </div>
    </section>
  );
}

function InvoiceRecordDetails({
  decision,
  detail,
  finding,
  loading,
  onOpenPdf,
}: {
  decision: InvoiceDecision;
  detail: InvoiceDetail | null;
  finding: Finding | undefined;
  loading: boolean;
  onOpenPdf: (uri: string) => void;
}) {
  const lines = detail?.lines ?? [];
  const trail = decisionTrail(decision, detail);
  if (finding?.summary) {
    trail.splice(1, 0, { title: "Recorded finding", detail: finding.summary });
  }
  const summaryClass =
    "flex min-h-11 cursor-pointer list-none items-center gap-1.5 px-5 py-2.5 text-sm font-semibold text-slate-800 hover:bg-slate-50";
  const chevron = (
    <HiChevronRight
      className="h-4 w-4 shrink-0 text-slate-500 transition-transform group-open:rotate-90"
      aria-hidden="true"
    />
  );

  return (
    <div className="divide-y divide-slate-200">
      <details className="group">
        <summary className={summaryClass}>
          {chevron}
          Invoice lines
          <span className="ml-auto text-xs font-normal text-slate-600">
            {loading ? "Loading…" : `${lines.length} line${lines.length === 1 ? "" : "s"}`}
          </span>
        </summary>
        <div className="px-5 pb-4">
          {lines.length > 0 ? (
            <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
              {lines.map((line) => (
                <li key={line.id} className="px-3 py-2 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-medium text-slate-900">{line.description}</p>
                    <p className="shrink-0 font-semibold tabular-nums text-slate-900">
                      {formatCurrency(line.amount, detail?.currency)}
                    </p>
                  </div>
                  <p className="mt-0.5 text-xs text-slate-600">
                    {line.sku ? `SKU ${line.sku}` : "No SKU"}
                    {line.purchase_order ? ` · ${line.purchase_order}` : " · No PO"}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-600">
              {loading ? "Loading invoice lines…" : "No invoice lines were imported."}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <PreviewDocumentButton label="Invoice PDF" uri={decision.pdf_uri} onOpen={onOpenPdf} />
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-600">
              <OneLakeIcon className="h-4 w-4 shrink-0" />
              Documents come from Microsoft OneLake
            </span>
          </div>
        </div>
      </details>
      <details className="group">
        <summary className={summaryClass}>
          {chevron}
          Decision trail
        </summary>
        <ol className="px-5 pb-4">
          {trail.map((item) => (
            <li key={item.title} className="grid grid-cols-[20px_minmax(0,1fr)] gap-3">
              <div className="relative flex justify-center">
                <span className="relative z-10 mt-1 flex h-5 w-5 items-center justify-center rounded-full bg-blue-50 text-blue-700 ring-4 ring-white">
                  <HiCheckCircle className="h-4 w-4" aria-hidden="true" />
                </span>
                <span className="absolute bottom-0 top-7 w-px bg-slate-200" aria-hidden="true" />
              </div>
              <div className="pb-4">
                <p className="text-sm font-semibold text-slate-900">{item.title}</p>
                <p className="mt-0.5 text-sm leading-6 text-slate-700">{item.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}

function RunAssuranceConfirmation({
  decision,
  runCount,
  triggering,
  error,
  onConfirm,
  onClose,
}: {
  decision: InvoiceDecision;
  runCount: number;
  triggering: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  useModalDialog(dialogRef, { onClose, initialFocusRef: cancelRef, canClose: !triggering });

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="run-assurance-title"
      aria-describedby="run-assurance-guidance"
      onClick={triggering ? undefined : onClose}
    >
      <section
        className="w-full max-w-md overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="px-5 pb-2 pt-5">
          <h2 id="run-assurance-title" className="text-lg font-semibold text-slate-950">
            Run assurance for {decision.invoice_number}?
          </h2>
          <div id="run-assurance-guidance" className="mt-2 space-y-2 text-sm leading-6 text-slate-700">
            <p>
              This starts the cloud agent pipeline for {decision.supplier_name}. Four experts
              gather evidence, then a decision is recorded. It can take several minutes, and
              you'll follow it in Activity.
            </p>
            <p>
              If a run is already active for this invoice, Waypoint reuses it instead of starting
              another. Each new run uses hosted agent capacity and may incur usage cost.
            </p>
            {runCount > 0 ? (
              <p>
                This will be run {runCount + 1}. Earlier runs stay in the run history.
              </p>
            ) : null}
          </div>
          {error ? (
            <p
              className="mt-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800"
              role="alert"
            >
              {error}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2 px-5 pb-5 pt-3">
          <button
            ref={cancelRef}
            type="button"
            className={secondaryButton}
            onClick={onClose}
            disabled={triggering}
          >
            Cancel
          </button>
          <button
            type="button"
            className={primaryButton}
            onClick={onConfirm}
            disabled={triggering}
          >
            {triggering ? (
              <HiRefresh className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <HiSparkles className="h-4 w-4" aria-hidden="true" />
            )}
            {triggering ? "Starting assurance…" : "Start assurance run"}
          </button>
        </div>
      </section>
    </div>
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
      ? "text-red-700"
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
  const score = parseConfidenceScore(confidence);
  if (score === null) {
    if (hasDecision && !calibrated) {
      return (
        <span
          className="inline-flex rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 ring-1 ring-slate-200"
          title={confidenceTitle(false)}
        >
          Not calibrated
        </span>
      );
    }
    return <span className="type-meta">—</span>;
  }
  if (!calibrated) {
    return (
      <span
        className="inline-flex rounded-md bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 ring-1 ring-slate-200"
        title={confidenceTitle(false)}
      >
        {Math.round(score * 100)}%
      </span>
    );
  }
  return (
    <span
      className={`inline-flex rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ${confidenceTone(score)}`}
      title={confidenceTitle(true)}
    >
      {Math.round(score * 100)}%
    </span>
  );
}

function SourceCount({ sources, planes }: { sources: number; planes: number }) {
  if (sources <= 0 && planes <= 0) {
    return (
      <span className="type-meta" title="No expert evidence recorded for this invoice yet.">
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
        <span className="type-meta">
          {sources} {sourceWord} cited
        </span>
      ) : null}
    </span>
  );
}

function BasisPills({ basisTypes }: { basisTypes: Array<"contract" | "policy"> }) {
  if (basisTypes.length === 0) {
    return <span className="type-meta">Unmapped</span>;
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useModalDialog(dialogRef, { onClose, initialFocusRef: headingRef });

  return (
    <div
      ref={dialogRef}
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
            <h2 ref={headingRef} tabIndex={-1} className="rounded-sm text-xl font-semibold">
              {title}
            </h2>
            <p className="mt-0.5 text-sm text-slate-600">{subtitle}</p>
          </div>
          <button
            type="button"
            className="rounded-md p-1 text-slate-500 hover:bg-slate-50"
            onClick={onClose}
          >
            <HiX className="h-5 w-5" aria-hidden="true" />
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
      <div className="border-b border-slate-100 px-4 py-2 type-label">
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
      <p className="type-label">Metadata</p>
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
