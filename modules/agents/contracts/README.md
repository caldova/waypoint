# contracts

`contracts` is the stub for Waypoint's Teams-first contract intake autopilot.
It is intentionally deployable before the new Waypoint Contracts API exists, so
the product name, protocols, and future tool contract can settle while the API
surface is built.

## Intended flow

1. A user emails a contract PDF to the Contracts inbox.
2. A Foundry routine wakes this hosted agent on a schedule.
3. The agent polls the inbox through a future Graph/WorkIQ connector.
4. New attachments are deduped and registered in Waypoint as contract artifacts.
5. Content Understanding extracts values.
6. Evidence tools gather FoundryIQ, WebIQ, WorkIQ, FabricIQ, and Waypoint
   evidence.
7. Teams users ask Contracts about the latest or prior contracts.
8. On request, Contracts generates a document, stores it in SharePoint, and
   shares it after user approval.

## Current behavior

The agent registers all three Castia protocols:

| Protocol | Purpose |
| --- | --- |
| `responses` | Foundry Playground / direct chat. |
| `activity` | Teams-style conversational surface. |
| `invocations` | Structured routine and agent-to-agent work commands. |

For the deployment spike, keep work surfaces separated:

- `responses` is the Foundry Playground / direct chat surface.
- `activity` is the Teams / AI Teammate chat surface.
- `invocations` is the structured work-command surface for routines and future
  agent-to-agent calls.

Hosted mailbox reads happen on Teams turns only. Users email PDFs to the hire's
mailbox (for example `contracts@caldova.com`), then ask in Teams; the agent reads
just that user's messages with the hire's agentic-user token and registers new
attachments in Waypoint. Only PDFs from the inbox's own domain are read; set
`CONTRACTS_ALLOWED_SENDER_DOMAINS` (comma-separated) to allow others. A scheduled
routine cannot do this yet: only Agent 365
turns bind the hosted credential to the hired instance that owns the mailbox, so
off Teams the tool returns `needs_teams_turn`.

Users can also attach a PDF to the Teams message itself; the same tool downloads
it (Teams `file.download.info`) and registers it with `source: teams_upload`.

After ingest the agent reviews each new document in the same turn: it lists the
user's prior artifacts (`find_prior_contracts`, backed by
`GET /api/contracts/artifacts`), checks policy with FoundryIQ, records cited
findings as evidence (`record_contract_findings`), and marks the artifact
processed. Hosted ingest no longer writes placeholder evidence.

In the local playground, ask about an emailed contract to run the fixture inbox
path. Pass `artifact_type: "invoice"` to force the agent-local invoice fixture.

The same structured surface supports invoice work queries against the Waypoint
records/work APIs:

```json
{
  "operation": "query_invoices",
  "invoice_number": "SUP-001-2026-10",
  "include_context": true
}
```

Use `query_invoices` for seeded or live invoice conversations. When exactly one
invoice is selected, it also fetches `/api/invoices/{invoice_id}/context` so the
answer can cite findings, evidence, contract documents, policies, and cases from
Waypoint rather than relying on model memory.

Use `get_deployment_diagnostics` before and after each deploy to confirm the
non-secret runtime fingerprint that the hosted agent sees:

```json
{
"operation": "get_deployment_diagnostics"
}
```

The result includes configured-value presence, SharePoint report readiness,
`CONTRACTS_AGENT_BUILD_ID`, `CONTRACTS_AGENT_DEPLOYMENT_STAGE`, and rollout
guidance for hosted sessions. It intentionally reports only presence and
non-secret values, never tokens or credentials.

The baseline agent config also declares the read-only FoundryIQ contract/policy
knowledge-base tool. The model sees it as `foundry_iq_retrieve`; the agent
dispatches each call to the toolbox MCP tool
`contracts-kb-mcp___knowledge_base_retrieve`.

Contracts has its own Foundry toolbox, `contracts-toolbox` (`toolbox.yaml`),
separate from the `contract-toolbox` used by `contract-policy-expert`, so new
lanes never change the policy expert's evaluated tool surface. Hosted runs set
`TOOLBOX_NAME=contracts-toolbox` and the version-less
`TOOLBOX_CONTRACTS_TOOLBOX_MCP_ENDPOINT`, so publishing a new toolbox version
needs no redeploy. When the endpoint resolves, the agent exposes the KB tool on
every surface as a client-side function that calls the toolbox `tools/call`, so
each call gets a local `execute_tool foundry_iq_retrieve` span. Local fixture
mode can still run without the toolbox endpoint.

To add a lane (WorkIQ, WebIQ, FabricIQ, ...):

1. Store any credential in a Foundry project connection (never in the repo or
   agent env), e.g. `azd ai connection create <connection> --kind remote-tool
   --auth-type custom-keys --custom-key "<header>=<key>"`. Then
   `azd ai toolbox connection add contracts-toolbox <connection>` and
   `azd ai toolbox publish contracts-toolbox <version>`.
2. For an IQ lane, add a local `<source>_iq_*` wrapper that calls
   `toolbox.call_toolbox_tool` (see `webiq.py`) so spans carry the IQ kind.
   For a non-IQ lane, add its exact MCP tool names (from `tools/list`) to
   `CONTRACTS_TOOLBOX_TOOLS` in `agent/toolsets.py`; Castia preflights them and
   projects them as `toolbox`-typed tools. Redeploy either way.

WebIQ is lane `contracts-webiq-mcp` (`https://api.microsoft.ai/v3/mcp`). Its
API key lives only in that project connection; the toolbox sends it as
`x-apikey`. The model sees `web_iq_search` (web or news) and `web_iq_browse`.
Rotate the key with `azd ai connection create contracts-webiq-mcp ... --force`;
no redeploy is needed.

Agentic-user Graph tools (mail, OneDrive) stay local: they need the Teams
turn's agentic user token, which a toolbox call does not carry.

### IQ tool telemetry

Each `execute_tool` span carries `gen_ai.tool.type` naming the IQ source behind
the tool:

| `gen_ai.tool.type` | Tools |
| --- | --- |
| `foundry_iq` | `foundry_iq_retrieve` |
| `web_iq` | `web_iq_search`, `web_iq_browse` |
| `work_iq` | `read_inbox`, `send_email`, `reply_email`, `create_document` (Activity only) |
| `function` | Waypoint API and local tools (`poll_contracts_inbox`, `get_last_contract`, `draft_contract_report`, `query_invoices`, diagnostics) |

**Adding an IQ-backed tool:** give it both IQ monikers so telemetry shows its
source.

- Set `kind` to the IQ source (`foundry_iq`, `work_iq`, `fabric_iq`, ...). This
  becomes `gen_ai.tool.type`.
- Prefix the model-facing name with that source (e.g. `foundry_iq_retrieve`),
  so the span reads `execute_tool <source>_iq_<action>`. Dispatch to the
  underlying MCP/Graph name inside the impl, as `toolbox.py` does.

Castia's built-in Graph tools keep their Castia names and get only the
`work_iq` kind.

The tools in `tools.py` are API-ready scaffolds. For local smoke tests, the
agent can source an actual fixture PDF from disk instead of checking a mailbox.
`CONTRACTS_DOCUMENT_SOURCE_MODE=auto` selects:

- `local` when the Waypoint API URL is localhost or unset.
- `hosted` when the API URL is non-local.

Set `CONTRACTS_DOCUMENT_SOURCE_MODE=local` to force local PDF sourcing. By
default the local source reads `fixtures/contracts/aster-ridge-sow.pdf` as a
`contract` artifact. Pass `"artifact_type": "invoice"` in a structured
invocation to exercise the same email-intake route with a Ledgerfield invoice
PDF from `fixtures/invoices`, or set `CONTRACTS_LOCAL_DOCUMENT_KIND=invoice` as
a process default for manual runs. `CONTRACTS_LOCAL_PDF_PATH` /
`CONTRACTS_LOCAL_INVOICE_PDF_PATH` can point at a specific fixture.

When `WAYPOINT_API_BASE_URL` is unset, local fixture mode is enabled so the
playground can exercise the flow without the future API:

- `poll_contracts_inbox` reads `fixtures/contracts/aster-ridge-sow.pdf` and
  seeds a mock Aster Ridge contract artifact.
- `get_last_contract` resolves that mock artifact.
- `draft_contract_report` takes report Markdown written by the model
  (`markdown`, `title`), renders it to DOCX with quilldown, and keeps both
  under `.contracts-state/reports/`. Without `markdown` it renders a minimal
  metadata summary. DOCX is the primary `file_url`.
- `query_invoices` requires `WAYPOINT_API_BASE_URL`; it is intentionally
  API-backed so Flow 2 conversations use seeded/live Waypoint data.

Report publishing uses `report_publisher.py`. `CONTRACTS_REPORTS_PUBLISH_MODE`
is `auto` (default), `local`, `onedrive`, or `sharepoint`:

| Mode | When `auto` picks it | Result |
|---|---|---|
| `onedrive` | Activity turn with an agentic user (Teams / M365) | DOCX uploaded to the agent's own OneDrive (`/me/drive`, folder `CONTRACTS_REPORTS_ONEDRIVE_FOLDER`, default `Contracts Reports`) and shared with the requester's Entra object id (`CONTRACTS_REPORTS_SHARE_ROLE`, default `read`; no invitation email) |
| `sharepoint` | Drive and folder ids are set | DOCX uploaded to the agent-owned SharePoint folder with an organization view link |
| `local` | Otherwise (Responses / playground turns) | `file://` DOCX URL plus Markdown sidecar |

OneDrive uses the agentic user token and the consented `Files.ReadWrite` scope.
`/responses` turns carry no Activity, so they never publish to OneDrive.

- SharePoint mode uploads the DOCX with Microsoft Graph using the hosted
  identity and creates an organization view link. Required environment:
  `CONTRACTS_REPORTS_DRIVE_ID` and `CONTRACTS_REPORTS_FOLDER_ITEM_ID`.
- The tool does not silently fall back if OneDrive or SharePoint upload
  fails; it returns `status: report_publish_failed` so the Teams answer does not
  claim a document was shared.

When `WAYPOINT_API_BASE_URL` points at a local Waypoint API, the same PDF-backed
intake path registers the artifact through `/api/contracts/intake/messages/upsert`.
In hosted mode, mailbox polling intentionally returns
`hosted_mailbox_not_implemented` until the Graph/WorkIQ connector is wired.

## Deployment smoke telemetry

Set these optional values before a smoke deploy:

```powershell
azd env set CONTRACTS_AGENT_BUILD_ID "<short-git-sha-or-smoke-id>"
azd env set CONTRACTS_AGENT_DEPLOYMENT_STAGE "smoke"
azd env set CONTRACTS_LOG_LEVEL "INFO"
```

The agent writes structured JSON log lines prefixed with
`contracts.telemetry`. Current events include:

- `contracts_deployment_diagnostics_checked`
- `contracts_capabilities_checked`
- `contracts_inbox_poll_completed`
- `contracts_invoice_query_completed`
- `contracts_report_publish_started`
- `contracts_report_publish_succeeded`
- `contracts_report_publish_failed`
- `contracts_report_draft_completed`

After `azd deploy contracts --no-prompt`, smoke a fresh hosted session through
the Invocations protocol:

```powershell
azd ai agent invoke contracts --protocol invocations --new-session --input-file .\modules\agents\contracts\smoke-diagnostics.json
```

or send the same JSON string through the Foundry Agent Playground canvas. Then
use `azd ai agent monitor contracts --tail 100` for the hosted session log, or
query App Insights for `contracts.telemetry` to see which Graph/SharePoint,
Content Understanding, Waypoint API, and toolbox settings are present in the
published runtime.

Each successful hosted `azd deploy` creates a new immutable agent version.
Existing hosted sessions are separate state. For deterministic validation after
an update, start with `--new-session`; for stale sessions, list and stop/delete
old sessions with `azd ai agent sessions`. Teams/activity conversations should
be treated as channel state, so publish/install the new version and start a
fresh Teams chat for the smoke path rather than assuming old chat state was
rebound.

PDF extraction runs through `content_understanding.py`:

- If `CONTENT_UNDERSTANDING_ENDPOINT` is set, the agent calls
  `/contentunderstanding/analyzers/{CONTENT_UNDERSTANDING_ANALYZER_ID}:analyze`
  with the PDF bytes and records the returned JSON in Waypoint.
- If `CONTENT_UNDERSTANDING_USE_FOUNDRY_PROJECT=true`, the endpoint is derived
  from `FOUNDRY_PROJECT_ENDPOINT`.
- Prebuilt analyzers that require model deployments use
  `CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT` as
  `prebuilt-analyzer-completion` and
  `CONTENT_UNDERSTANDING_EMBEDDING_DEPLOYMENT` as
  `prebuilt-analyzer-embedding`.
- `prebuilt-contract` on `aif-caldova` supports `gpt-5.5` but rejects
  `gpt-6-astra`, so the CU-specific completion default is `gpt-5.5` even
  though the Contracts chat model can stay on Astra.
- If neither is set, local smoke tests use deterministic PDF text extraction and
  still post a `content_understanding` extraction record to the local API.

The signed-in developer or hosted identity needs **Cognitive Services Content
Understanding Reader** on the AI Services account that owns the CU endpoint. For
the Caldova project this was assigned at:

```text
/subscriptions/e25e09c9-14a3-431e-9b72-1916344294d3/resourceGroups/rg-caldova/providers/Microsoft.CognitiveServices/accounts/aif-caldova
```

Role definition id:

```text
379c52cb-64de-498c-8b5b-c6170d6c49d4
```

On Microsoft 365 Activity turns, the agent also offers Castia's agentic-user
Microsoft Graph tools. Those tools receive the original Teams/Agent 365 Activity
so Castia can mint the agentic-user token and act as the hired agent's own
mailbox/OneDrive identity:

- `read_inbox` reads recent messages from the agent mailbox.
- `send_email` sends a new message from the agent mailbox.
- `reply_email` replies in-thread to a message read from that mailbox.
- `create_document` creates a Markdown/text document in the agent's OneDrive and
  shares it with the requester.

The Graph tools are intentionally not exposed on plain Responses or Invocations
turns because those surfaces do not carry the Agent 365 `agenticUser` Activity
identity required for mailbox/OneDrive actions.

The Activity surface registers lightweight Castia commands that bypass the model
and return runtime state directly:

- `/version` shows Foundry agent version, Microsoft 365 app version, model, and
  hosted identity metadata.
- `/state` shows configured Contracts surfaces and feature flags.
- `/whoami` shows the Teams/Agent 365 Activity identity shape.
- `/tools` lists the tools exposed on Responses versus Activity turns.
- `/health` checks protocol/model/agentic-user readiness.
- `/trace` prints Activity and conversation IDs for telemetry lookup.

The Activity chat surface is intentionally mode-aware:

- Capability/help prompts return a transparent summary of what is live, what is
  stubbed, and what to try next.
- Latest-invoice prompts return fixture invoice summaries with review status and
  suggested follow-up actions.
- Slash/debug commands bypass the model and return concise runtime diagnostics.

## Package layout

The hosted entrypoint stays tiny in `main.py`; behavior lives under
`agent/`:

| Path | Purpose |
| --- | --- |
| `agent/domain/` | Shared business behavior, fixtures, modes, and diagnostics. |
| `agent/protocols/activity/` | Teams / Agent 365 Activity commands, cards, and handlers. |
| `agent/protocols/responses/` | Responses protocol adapter. |
| `agent/protocols/invocations/` | Invocations protocol adapter. |
| `agent/integrations/` | External identity/API helpers such as Activity identity. |
| `agent/tools/` | Castia model-callable tool definitions. |
| `agent/toolsets.py` | Protocol-specific model and toolset composition. |

## Microsoft 365 activation permissions

The autopilot publish metadata requests Microsoft Graph delegated permission
scopes for the agentic-user mailbox and OneDrive access used by Castia's
Graph helpers:

- `Mail.Read` for reading the agent's mailbox.
- `Mail.Send` for sending and replying from the agent's mailbox.
- `Files.ReadWrite` for creating documents in the agent's OneDrive and sharing
  them with the requester.

The Microsoft 365 admin center shows these permissions during the **Pending
activate** approval wizard. They define the agent user's allowed M365 surface;
the Contracts-specific intake/report tools still stay in local fixture / future
API mode until the Waypoint Contracts intake and report APIs are implemented.

## Runtime identities and roles

The agent runs under two identities. Both need **Foundry User** at Foundry
project scope (`AZURE_AI_PROJECT_ID`) and the **`Waypoint.Write`** app role on
the Waypoint API app registration (`WAYPOINT_API_SCOPE`; writer implies reader).
Without Foundry User, `/version` falls back to the configured version with
`foundry_agent_version_error: HTTP 403`, and toolbox calls fail. Without the
Waypoint role, API tools fail with `AADSTS501051` (the API app requires role
assignment).

| Identity | Used for | azd env var |
| --- | --- | --- |
| Hosted instance identity | Responses / Invocations turns | `AGENT_CONTRACTS_INSTANCE_IDENTITY_PRINCIPAL_ID` (set by `azd deploy`) |
| Agent 365 agent identity | Teams / Activity turns | `CONTRACTS_MAILBOX_AGENT_ID` (set once the agent is hired in Teams) |

`azd ai agent show contracts` and `GET /agents/contracts` report only the
instance identity. On Teams turns the runtime calls as the Agent 365 identity,
whose object id `/version` shows as `hosted_instance_client_id`.

`scripts/grant-runtime-roles.ps1` grants both identities their roles; grants
that already exist are skipped. It is a manual step today (candidate for a
`contracts` postdeploy hook). The person running it needs Owner or User Access
Administrator on the project. After a deploy or after hiring a new agent:

```powershell
azd env set CONTRACTS_MAILBOX_AGENT_ID <agent-365-object-id>
pwsh modules/agents/contracts/scripts/grant-runtime-roles.ps1
```

Role changes take 5–10 minutes to propagate. Hosted sessions stay on the
version they were created with; `azd ai agent sessions list --agent-name
contracts` shows which version each session runs.

## Local development

```powershell
cd modules\agents\contracts
uv sync
uv run python main.py
```

Useful local prompts:

```text
What can Contracts do right now?
Check the Contracts inbox.
What was in the last contract I sent?
Draft a contract brief for the latest artifact.
Which invoices have findings?
```

## Remaining work before `v2`

This branch is a good baseline for merging the Contracts agent into `v2`, but
the production story still has a few explicit gaps:

- Replace fixture-mode inbox/artifact/report behavior with the Waypoint
  Contracts API once that surface exists.
- Confirm Agent 365 Activity payloads include `recipient.role=agenticUser` and
  the agentic-user identifier needed by Castia Graph tools in Teams.
- Keep `/version` as the primary field diagnostic and verify it reports the live
  Foundry version after each deploy, not just the configured environment value.
- Continue validating Teams typing/streaming behavior with real Teams turns; the
  agent starts status immediately and does not delay the final response just to
  show typing.
- Wire production telemetry dashboards around Activity turns, tool calls, slash
  diagnostics, and error rates once the Teams path is stable.
