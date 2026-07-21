# Assurance Orchestrator

Assurance Orchestrator is a read-only invoice assurance scout for testing Forge against the
Waypoint API. The name nods to Luca Assurance Orchestrator, the accounting pioneer.

The first pass is intentionally narrow:

- Read Waypoint work, runs, action types, cases, invoices, decisions, findings,
  evidence, contract documents, and policies.
- Run a read-only invoice assurance scout flow that summarizes domain truth and
  prepares correlation metadata.
- Carry `waypoint_case_id`, `waypoint_run_id`, and `waypoint_action_id` fields
  for later Foundry/App Insights correlation.
- Never create cases, stage recommendations or approvals, authorize actions, or
  POST run metadata.

## Planning docs

The next Assurance Orchestrator phases are split into focused planning docs:

- [Demo storyline and narrative](docs/storyline.md) explains the business story,
  demo beats, control boundaries, and proof points.
- [Workflow implementation plan](docs/workflow-implementation.md) maps the
  invoice assurance flow into deterministic service stages, LLM-guided stages,
  fan-out validators, events, tests, invocation modes, controller-agent
  handoff, and Waypoint write phases.
- [Fine-tuning plan](docs/fine-tuning.md) describes how repeated approved runs
  become training and evaluation data for smaller, cheaper task models.

## Target invoice assurance workflow

The next phase turns Assurance Orchestrator from a read-only Waypoint scout into an invoice
assurance orchestrator. The intended flow is batch-oriented, but a "batch" can
contain a single invoice PDF so local testing and production execution share the
same path.

Assurance Orchestrator should treat invoice assurance as operational and financial
reconciliation, not basic accounts-payable matching. The core join is contract
pricing + PO or authorized work + receipts or shipments + batch records +
quality status and release logs + milestones + materials + capacity + invoice
lines.

1. **Ingest invoice PDFs and supplier context.** Receive a batch manifest that
   identifies one or more invoice PDFs, source locations, optional supplier
   hints, and known Waypoint correlation fields. Extract or normalize supplier,
   invoice number/date/due date, currency, total, line descriptions, quantities,
   unit prices, PO, SKU, batch/shipment, and milestone references.
2. **Extract invoice facts with Content Understanding.** Use Azure AI Content
   Understanding to extract canonical invoice fields and document evidence
   spans. Preserve source-page and source-span references so every later
   judgement can cite the PDF evidence that caused it.
3. **Resolve governing evidence.** Attach supplier, contract, scenario, policy,
   and operational context: supplier contract/MSA/SOW, quality agreement,
   applicable finance and quality policies, PO/change approval,
   receipt/shipment record, batch record, QA release/deviation/hold log,
   milestone acceptance, material consumption, capacity schedule, and supplier
   correspondence.
4. **Run deterministic checks first.** Check duplicate invoice/line, PO match,
   delivered-vs-billed or receipt match, rate table/tier/MOQ/discount/escalation
   and true-up math, released quantity, milestone approval, material
   pass-through, capacity minimums, and invoice timing triggers.
5. **Fan out specialist validation.** Use IQ validators in parallel for evidence
   that requires search, enterprise context, structured data, or contract/policy
   grounding. Each validator returns normalized findings, confidence, evidence,
   and recommended next action candidates without mutating Waypoint.
6. **Use language reasoning where it matters.** Apply LLM-style reasoning to
   contract clauses, quality agreement terms, policy basis, messy supplier line
   descriptions, IP-sensitive/process-sensitive context, and supplier-response
   drafting.
7. **Synthesize evidence-backed judgements.** Merge validator results into
   decisions with status, severity/category, amount at risk, explanation,
   evidence IDs/URIs/excerpts, contract document IDs, policy IDs, basis summary,
   and recommended next action.
8. **Route the decision.** Approve clean matches, review variances, recover
   duplicate or overpaid amounts, escalate quality/compliance/IP/supplier
   governance risks, and prepare a dispute packet when withholding or credit is
   needed.
9. **Post to Waypoint only after the write contract is explicit.** The current
   tools stay read-only. A later write phase should create or update cases,
   findings, evidence, recommendations, run metadata, and action drafts through
   governed Waypoint endpoints. It must not authorize actions or approvals
   unless a separate human-approved production workflow explicitly allows that.

### Validation fan-out

Assurance Orchestrator should treat each IQ as a specialist evidence source and normalize the
results into a shared finding shape before synthesis:

| Validator | Purpose | Example evidence |
| --- | --- | --- |
| **WebIQ** | Check external market and financial context to decide whether a price variance, surcharge, recovery, or collection effort is commercially reasonable. | Prevailing rates, inflation signals, supplier/industry trend summaries, public financial context. |
| **Fabric IQ** | Validate invoice integrity against structured operational and finance data. | Supplier master data, PO tables, goods receipt, batch records, payment status, duplicate invoice checks, historical rate cards. |
| **WorkIQ** | Validate invoice claims against work communications and collaboration artifacts. | Email threads, Teams messages, meeting notes, approvals, supplier correspondence, exception discussions. |
| **Foundry IQ** | Ground policy, contract, and supplier-document interpretation in indexed knowledge. | Invoice reconciliation policy, dispute/recovery procedure, supplier MSAs, SOWs, rate cards, quality agreements. |

### Ledgerfield reconciliation vocabulary

Use Ledgerfield terminology consistently:

- invoice assurance
- supplier invoice validation
- contract compliance and contractual adherence
- payment leakage and contract leakage
- invoice discrepancy management
- procure-to-pay controls
- three-way matching extended with contract and pharma-manufacturing context
- evidence-backed exception
- recovery opportunity
- CMO
- quality agreement
- batch production/control records
- quality release
- MOQ
- true-up

Useful status vocabulary includes `matched`, `variance`, `disputed`, and
`escalated` at the reconciliation layer. Current Waypoint seed statuses include
`open`, `review`, `approved`, `recover`, `escalate`, and `closed`.

### Policy basis

Ground judgements in these Ledgerfield policies:

- **Invoice Reconciliation Policy.** Invoices must be reconciled against
  contract terms/pricing, POs/change authorizations, receipts/shipments, batch
  records, quality release, milestones, materials, and capacity. Reconciliation
  states are Matched, Variance, Disputed, and Escalated; approval requires an
  authorized source document.
- **Invoice Dispute and Recovery Procedure.** Dispute packets include supplier,
  invoice, line, disputed amount, contract or policy basis, operational evidence,
  and recommended supplier action. Supplier communications cite controlling
  terms and request correction, credit, backup, or withdrawal.
- **Quality Release and Billability Policy.** Production, release testing, and
  batch administration are billable only after sponsor QA release unless the
  contract defines another trigger. Pending, rejected, and retest charges require
  explicit evidence or approval.

### Judgement and evidence shape

Each synthesized judgement should be traceable and safe to post:

```json
{
  "invoice_id": "INV-2026-08034",
  "waypoint_case_id": null,
  "waypoint_run_id": null,
  "category": "surge_capacity",
  "severity": "high",
  "status": "escalate",
  "money_at_risk": "25000.00",
  "confidence": 0.91,
  "summary": "Unauthorized surge capacity premium was billed before the revised production schedule and PO were approved.",
  "basis_summary": "Supplier capacity agreement plus surge approval and dispute policies.",
  "evidence": [
    {
      "source": "content_understanding",
      "document_id": "invoice-pdf-1",
      "page": 2,
      "span": "line-item-3"
    },
    {
      "source": "foundry_iq",
      "document_id": "contract-cmo-009-bluepeak-biologics-capacity-agreement",
      "excerpt": "Surge capacity fees require written schedule approval."
    }
  ],
  "contradictory_evidence": [],
  "contract_document_ids": [
    "contract-cmo-009-bluepeak-biologics-capacity-agreement"
  ],
  "policy_ids": [
    "policy-invoice-reconciliation-policy",
    "policy-invoice-dispute-and-recovery-procedure"
  ],
  "allowed_action_ids": [
    "draft_supplier_dispute",
    "recommend_recover",
    "request_legal_escalation"
  ],
  "side_effects_performed": false
}
```

### Open implementation decisions

- Whether Waypoint should model PDF ingest as a first-class batch resource or as
  repeated single-invoice runs grouped by `waypoint_run_id`.
- Which service owns PDF storage and document retention: Waypoint, Foundry
  project storage, Fabric/OneLake, or an external document store.
- The exact write endpoints and idempotency keys for posting extracted invoice
  facts, findings, evidence, recommendations, and run metadata.
- The production auth model for Waypoint writes. Delegated Azure CLI auth is
  useful for testing only; hosted Assurance Orchestrator should use app roles/client
  credentials or a managed identity flow once Waypoint supports it.
- Which IQ results are authoritative when validators disagree, and what
  confidence thresholds require human review instead of automated posting.

### Waypoint API target model

After read-only testing, Assurance Orchestrator should target Waypoint's agent control-plane
surfaces in this order:

| Purpose | Endpoint | Notes |
| --- | --- | --- |
| Work discovery | `GET /api/work` | Returns `WorkQueueItem[]` with invoice/finding/case IDs, severity, status, category, summary, money at risk, and classification. |
| Preferred prompt context | `GET /api/invoices/{invoice_id}/context?include_sensitive=false` | Returns `InvoiceContextBundle` with invoice, contract documents, policies, cases, allowed actions, redactions, and metadata. Prefer this over ad hoc raw reads once moving past smoke tests. |
| Domain truth reads | `GET /api/invoices`, `GET /api/invoices/{id}`, `GET /api/invoice-decisions`, `GET /api/findings?invoice_id=...`, `GET /api/evidence?invoice_id=...&finding_id=...`, `GET /api/contract-documents/{id}`, `GET /api/policies/{id}` | Read-only grounding for invoices, findings, evidence, contract documents, and policies. |
| Closed action vocabulary | `GET /api/actions/types` | Returns server-owned action types with `id`, `required_role`, `approval_gate`, `external_side_effect`, and metadata. |
| Run anchors | `GET /api/runs?case_id=...`, `POST /api/runs` | `POST /api/runs` accepts `case_id?`, `name`, `foundry_agent_name?`, `foundry_conversation_id?`, `app_insights_operation_id?`, and metadata. |

Waypoint does not currently expose raw PDF upload or batch-ingest endpoints for
agent runtime use. Current invoice documents are referenced by `Invoice.pdf_uri`
and `Invoice.html_uri`. Demo/corpus import is admin-only through
`POST /api/admin/seed/ledgerfield` with structured Ledgerfield seed data. Until
Waypoint adds a runtime ingest endpoint, Assurance Orchestrator should treat PDF/batch ingest as
upstream Ledgerfield corpus generation or a future Waypoint admin import path,
not as an agent-side operation.

### Waypoint write contract target

All write surfaces below are admin-gated today and should remain disabled in
Assurance Orchestrator until the auth model, idempotency, and human approval boundary are
explicit:

| Write step | Endpoint | Payload highlights |
| --- | --- | --- |
| Create/find case | `GET /api/cases?invoice_id=...&finding_id=...`, `POST /api/cases` | `invoice_id`, `finding_id?`, `title?`, `summary?`, `classification?`, metadata. |
| Recommendation | `POST /api/cases/{case_id}/recommendations` | `decision` (`approve`, `recover`, `escalate`, `review`), reasoning, confidence, money at risk, evidence IDs, proposed next actions, `foundry_response_id?`, metadata. |
| Draft artifact | `POST /api/cases/{case_id}/drafts` | `draft_type` (`supplier_dispute`, `escalation_packet`, `approval_summary`), title, body, source recommendation, classification, metadata. |
| Proposed action | `POST /api/cases/{case_id}/actions` | `action_type_id`, title, description, optional draft/recommendation IDs, metadata. |
| Approval | `POST /api/cases/{case_id}/approvals` | Proposed action ID, decision (`approved`, `rejected`), justification, artifact details, `idempotency_key`, metadata. |
| Authorized intent | `POST /api/actions/{action_id}/authorize` | Optional approval ID, `idempotency_key`, `foundry_snapshot`, metadata. |
| Decision audit | `GET /api/audit/decisions` | Admin-only audit trail. |

Waypoint intentionally records **authorized intent**, not direct execution.
Action types are server-owned and closed. `ActionType.external_side_effect`
declares whether a proposed action implies downstream side effects. Assurance Orchestrator must
not invent arbitrary commands or directly execute supplier, ERP, payment, or
email side effects.

The first write-enabled phase should stage recommendations, drafts, and proposed
actions only. Human/admin approval and `POST /api/actions/{action_id}/authorize`
should remain a separate controlled step. Anything decision-relevant from
Foundry/Assurance Orchestrator output must be snapshotted into Waypoint at decision time; traces
alone are not a durable decision record.

### Correlation and idempotency

Every invocation should carry `waypoint_case_id`, `waypoint_run_id`, and
`waypoint_action_id` when applicable. Also persist Foundry/App Insights
identifiers when available: `foundry_agent_name`, `foundry_conversation_id`,
`foundry_response_id`, `app_insights_operation_id`, and later eval/model/dataset
references.

Explicit server-side idempotency currently exists for approval and authorization:
`CaseApprovalCreate.idempotency_key` and `AuthorizeIntentCreate.idempotency_key`.
Do not assume broad idempotency for case, recommendation, draft, or action
creation yet. Assurance Orchestrator should generate stable idempotency keys for approval and
authorization, and keep client-side dedupe/correlation keys in `metadata` for
earlier write steps until Waypoint formalizes idempotency across all writes.

### Auth posture

The deployed Waypoint API is public but fail-closed: governed routes require an
Entra bearer token and deployed API docs/OpenAPI are disabled. Current testing
uses a delegated tenant token with the configured API scope. Production hosted
Assurance Orchestrator should move to client credentials, app roles, or a principal allow-list
before autonomous service use.

### Ledgerfield source references

This workflow is grounded in the Ledgerfield project:

- `docs/pharma_cmo_reconciliation.md`
- `docs/waypoint-narrative-grounding.md`
- `data/README.md`
- `data/policies/source-markdown/invoice-reconciliation-policy.md`
- `data/policies/source-markdown/invoice-dispute-and-recovery-procedure.md`
- `data/policies/source-markdown/quality-release-billability-policy.md`
- `data/scenarios/invoice-assurance-scenarios.json`
- `data/waypoint/invoice-decisions.json`
- `data/waypoint/waypoint-seed.json`

### Waypoint source references

The API target model is grounded in the Waypoint project:

- `docs/agent-api-control-plane-plan.md`
- `docs/demo-data.md`
- `api/app/modules/records/routes.py`
- `api/app/modules/records/schemas.py`
- `api/app/modules/work/routes.py`
- `api/app/modules/work/schemas.py`
- `api/app/modules/cases/routes.py`
- `api/app/modules/cases/schemas.py`
- `api/app/modules/runs/routes.py`
- `api/app/modules/runs/schemas.py`

## Waypoint configuration

Assurance Orchestrator adds Waypoint tools when `WAYPOINT_API_BASE_URL` is present:

```text
WAYPOINT_API_BASE_URL=https://<api-container-app-fqdn>
WAYPOINT_API_SCOPE=api://<waypoint-api-client-id>/<delegated-scope>
```

The base URL can also be the web proxy base ending in `/api`; the client adapts
paths so both direct API and same-origin proxy testing work.

For local Aspire testing with loopback dev auth, leave `WAYPOINT_API_SCOPE`
empty and Assurance Orchestrator will send no `Authorization` header. For deployed or
MSAL-enabled testing, set the delegated scope. For non-`/.default` delegated
scopes, Assurance Orchestrator shells out to the same Azure CLI token flow used by the
Waypoint API team:

```powershell
az account get-access-token --scope <WAYPOINT_API_SCOPE> --output json
```

Production agents should switch to client credentials or app roles after
Waypoint supports that authorization path.

## Runtime budget configuration

Each run executes under an `asyncio.timeout` budget derived from
`constraints.max_runtime_minutes` (default 30). Exceeding the budget cancels the
run and finalizes it as timed out.

Ops can override the default without changing per-request payloads via:

```text
ASSURANCE_ORCHESTRATOR_MAX_RUNTIME_MINUTES=30
```

Rules:

- Applies only when a request does **not** carry its own
  `constraints.max_runtime_minutes`. An explicit request value always wins.
- Invalid or non-positive values (`abc`, `0`, `-5`, empty) fall back to the
  built-in default of 30.

**OPS NOTE:** Keep this value comfortably below the Waypoint stale-run reaper TTL
(`APP_RUN_REAPER_TTL_SECONDS`, currently `2700`s / 45m in prod). The enforced
`max_runtime` plus a safety margin must stay under the reaper TTL, or
legitimately-progressing runs get false-reaped.

## Run locally

Copy the agent-local environment template first:

```powershell
Copy-Item agents\assurance-orchestrator\.env.example agents\assurance-orchestrator\.env
```

Set `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`, and any
optional Waypoint values in `agents/assurance-orchestrator/.env`. Assurance Orchestrator loads this file
explicitly on startup, including when launched from VS Code.

```bash
cd agents/assurance-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py
```

Then call the local Responses endpoint directly.

## Publishing to Microsoft 365 / Teams (AI Teammate)

Assurance Orchestrator inherits the AI Teammate ("hired digital worker")
path — `agent.yaml` declares `activity_protocol/v1` and the full M365 Agents
SDK env block, and `main.py` mounts `/api/messages` via `activity_protocol.py`.
The activity surface is intentionally tool-less for now because Waypoint auth is
delegated-user testing, not a production AI Teammate flow.

To get your agent into the M365 Copilot store and make hires reply in Teams:

1. **Publish.** From the repo root:

   ```bash
   make publish assurance-orchestrator
   ```

   This chains: bot service + Teams channel → Foundry application →
   M365 publish request → OAuth2 grants on the blueprint SP.

2. **Reset the blueprint client secret.** *Mandatory.* Foundry's API redacts
   the secret to `""` on read, so a missing real value silently breaks every
   hire with AAD `-60018`. Run the `az ad app credential reset` + `azd env set
   <AGENT>_BLUEPRINT_CLIENT_ID/_SECRET` recipe printed by
   `scripts/print_publish_next_steps.py` (also documented in
   [docs/AI_TEAMMATE.md](../../docs/AI_TEAMMATE.md)), then redeploy.

3. **Add the per-instance MI federated credential** on the blueprint app
   manually (one-time, until the Foundry portal exposes a button) — see the
   same doc. Without it, hired chats fail with `AADSTS70021: No matching
   federated identity record found`.

4. **Admin-approve** the publish request at
   <https://admin.cloud.microsoft/#/agents/all/requested>.

For the full recipe, common failure modes, and the `version_selector → @latest`
trap, read [docs/AI_TEAMMATE.md](../../docs/AI_TEAMMATE.md) end-to-end before
your first publish.
