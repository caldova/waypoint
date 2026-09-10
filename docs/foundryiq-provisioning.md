# FoundryIQ `contracts-kb` provisioning ledger

Living record of every Azure resource we **create** or **reuse** to stand up the
FoundryIQ contract/policy knowledge base and its toolbox for `contract-agent`, so
this can be folded into automated infra (bicep `AI_PROJECT_DEPENDENT_RESOURCES` +
a `create-foundryiq` script) later. Update the table as each step lands.

## Target scope

| Field | Value | Source |
| --- | --- | --- |
| Subscription | `<AZURE_SUBSCRIPTION_ID>` | `azd env get-values` |
| Resource group | `rg-caldova` | env `AZURE_RESOURCE_GROUP` |
| Foundry account | `ai-account-syhurnetrksxc` | env `AZURE_AI_ACCOUNT_NAME` |
| Foundry project | `ai-project-caldova` | env `AZURE_AI_PROJECT_NAME` |
| Project endpoint | `<FOUNDRY_PROJECT_ENDPOINT>` | env `FOUNDRY_PROJECT_ENDPOINT` |
| Region | `westus` | env `AZURE_LOCATION` |
| Resource token | `syhurnetrksxc` | account name suffix |

Co-location rule (README/deployment): Azure AI Search, Foundry, the embedding
deployment, and the chat model **must share the region** or `knowledge_base_retrieve`
runs cross-region and the demo falls back. Everything below is pinned to `westus`.

## Resource ledger

State legend: **exists** (already there, reuse as-is) · **create** (we make it) ·
**pending** (planned, not yet made) · **done** (created + verified).

| # | Resource | Type | Name | State | Purpose | Est. cost | How created |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Foundry account | `Microsoft.CognitiveServices/accounts` | `ai-account-syhurnetrksxc` | exists | Hosts project + model deployments | incl. | azd (root infra) |
| 2 | Foundry project | `.../accounts/projects` | `ai-project-caldova` | exists | Agent + KB + toolbox home | incl. | azd (root infra) |
| 3 | Chat model | model deployment | `gpt-5.5` | exists | Agent reasoning + KB answer synthesis | usage | azd (`aiProjectDeploymentsJson`) |
| 4 | Container registry | `Microsoft.ContainerRegistry` | `crsyhurnetrksxc` | exists | Hosted-agent images | ~$5/mo | azd (root infra) |
| 5 | App Insights | `Microsoft.Insights/components` | `appi-syhurnetrksxc` | exists | Traces (retrieval verification) | usage | azd (root infra) |
| 6 | Embedding model | model deployment | `text-embedding-3-large` | **done** | Vectorize contract chunks for search | usage | `az cognitiveservices ... deployment create` (GlobalStandard, cap 50) |
| 7 | Storage account | `Microsoft.Storage/storageAccounts` | `stsyhurnetrksxc` | **done** | Blob `knowledge` container = KB source docs | ~$0 (few MB) | `az storage account create` (Standard_LRS, westus) |
| 8 | Blob container | storage container | `knowledge/contracts/` | **done** | 18 docs (15 contracts + 3 policies) uploaded | incl. | `ledgerfield upload-contracts-kb --include-policies` |
| 9 | Azure AI Search | `Microsoft.Search/searchServices` | `srch-syhurnetrksxc` | **done** | Index host for KB retrieval | Basic ≈ $75/mo | `az search service create` (basic, westus, 1x1) |
| 10 | Search MI + RBAC | system-assigned identity | `srch-syhurnetrksxc` MI | **done** | KS reaches blob + embedding model keyless | incl. | `az search service update --identity-type SystemAssigned` + Storage Blob Data Reader (storage) + Cognitive Services User (Foundry) |
| 11 | Storage connection | project connection | — | **n/a** | KS reaches blobs via `ResourceId=` + search MI (row 10), no project connection needed | — | — |
| 12 | Knowledge source | Azure AI Search `knowledgeSource` (`azureBlob`) | `contracts-ks` | **done** | Blob source; Search chunks + vectorizes (minimal mode) | incl. | Search REST `PUT /knowledgesources/contracts-ks` (`2026-08-01-preview`) → gen'd datasource/indexer/skillset/index |
| 13 | Knowledge base | Azure AI Search `knowledgeBase` | `contracts-kb` | **done** | Orchestrates retrieval → `knowledge_base_retrieve` (18/18 docs, retrieve verified) | incl. | Search REST `PUT /knowledgebases/contracts-kb` (`2026-08-01-preview`), gpt-5.5 answerSynthesis |
| 14 | KB MCP connection | Foundry project connection (`RemoteTool`/MCP) | `contracts-kb-mcp` | **done** | Lets the toolbox reach the KB MCP endpoint, keyless (project MI) | incl. | `azd ai connection create --kind remote-tool --auth-type project-managed-identity --audience https://search.azure.com` |
| 15 | Toolbox | Foundry toolbox | `contract-toolbox` | **done** | Single aggregating investigative toolbox; federates `contracts-kb-mcp___knowledge_base_retrieve` server-side | incl. | `azd ai toolbox create contract-toolbox --from-file toolbox.yaml` (`modules/agents/contract-agent/toolbox.yaml`) |
| 16 | Search RBAC + reader grants | search config + role assignments | `srch-syhurnetrksxc` | **done** | KB MCP endpoint accepts AAD; project/account MI + self can retrieve | incl. | `az search service update --auth-options aadOrApiKey --aad-auth-failure-mode http403` + `Search Index Data Reader` to self, project MI, account MI |
| 17 | Hosted agent | Foundry hosted agent | `contract-agent:1` | **done** | The single castia agent; all 3 protocols (activity/responses/invocations). Platform auto-attaches `contract-toolbox` | usage | `azd deploy contract-agent` (container image in ACR row 4) |
| 18 | Agent-identity RBAC | role assignment | agent instance MI `<AGENT_INSTANCE_PRINCIPAL_ID>` | **done** | Lets the Responses model service enumerate + call the toolbox MCP as the container MI (fixes HTTP 403 on `tools/list`) | incl. | `Foundry User` at **project** scope. NOTE: the agent **blueprint** principal is `agentIdentityBlueprintPrincipal` and **cannot** take role assignments — grant the **instance** MI (`azd ai agent show` → `instance_identity.principal_id`). Propagation ~5–10 min |

## KB creation method (confirmed)

FoundryIQ retrieval **is Azure AI Search agentic retrieval**. The `knowledgeSource`
and `knowledgeBase` are first-class objects **on the Search service** (not the
Foundry project endpoint — which is why `GET {project}/knowledgeBases` 404s),
created via Search REST at api-version **`2026-08-01-preview`** (GA `2026-04-01`;
preview is required for gpt-5.5 + LLM query planning/answer synthesis):

- `PUT https://{search}.search.windows.net/knowledgesources/contracts-ks?api-version=2026-08-01-preview`
  — kind `azureBlob`, `connectionString: "ResourceId=<storage-id>"` (keyless via the
  search MI, row 10), `containerName: knowledge`, `folderPath: contracts`,
  `ingestionParameters.contentExtractionMode: minimal` +
  `disableImageVerbalization: true` (text markdown, no Content Understanding /
  chat model), `embeddingModel` = `text-embedding-3-large` (row 6). Search
  auto-generates the datasource/indexer/skillset/index and runs ingestion.
  Gotcha: `chatCompletionModel` must be **omitted** when `disableImageVerbalization`
  is true, else 400.
- `PUT https://{search}.search.windows.net/knowledgebases/contracts-kb?api-version=2026-08-01-preview`
  — references `contracts-ks`, `models` = gpt-5.5 (query planning + synthesis),
  `outputMode: answerSynthesis`, `retrievalReasoningEffort.kind: low`. Retrieve is
  `POST /knowledgebases/contracts-kb/retrieve` with `messages[]`. A Foundry
  **connection** to the Search service + a **toolbox** (row 15) then surface it to
  the agent as `knowledge_base_retrieve`.

Simplification option: a `files`/upload knowledge source would drop the storage
account + blob writer (rows 7–8, 11), but `azureBlob` matches the repo's proven
`contracts_kb_upload.py` path and is the reliable default for the demo.

## Toolbox wiring (confirmed)

The KB is surfaced to `contract-agent` through a **single Foundry project-scoped
toolbox** (the user's chosen aggregation point) — so future investigative lanes
(WorkIQ / WebIQ / FabricIQ) join by attaching another connection and republishing
the toolbox's default version, with **no agent redeploy**.

- **Connection `contracts-kb-mcp`** (`RemoteTool`/MCP): `target` = the KB agentic
  MCP endpoint `https://srch-syhurnetrksxc.search.windows.net/knowledgebases/contracts-kb/mcp?api-version=2026-08-01-preview`;
  `auth-type project-managed-identity`, `audience https://search.azure.com`.
  Keyless — the toolbox calls Search as the project MI (row 16 grant). No admin
  key stored anywhere.
- **Toolbox `contract-toolbox`** (`modules/agents/contract-agent/toolbox.yaml`):
  attaches `contracts-kb-mcp` under `connections`. Federates one tool,
  `contracts-kb-mcp___knowledge_base_retrieve`. No `policies` block — the account's
  `Microsoft.Default` RAI name is **rejected** by the toolbox runtime (`tools/list`
  → `bad_request`), so RAI is left at the service default.
- **Agent wiring:** `TOOLBOX_CONTRACT_TOOLBOX_MCP_ENDPOINT` (azd env) points at the
  **version-less** endpoint `{project}/toolboxes/contract-toolbox/mcp?api-version=v1`,
  which always serves the published default version. `toolbox.py` discovers it as a
  named managed-identity lane (headless-safe, all federated tools offered).
- **Verified e2e:** MCP `tools/list` shows `knowledge_base_retrieve`; a live
  `tools/call` returned a grounded, multi-reference answer from the Aster Ridge SOW
  + invoice policies through the keyless project-MI connection. **Live hosted agent
  confirmed:** `azd ai agent invoke contract-agent --protocol responses` (rejected-batch
  billing question) returned a grounded answer quoting the SOW ("not billable for
  rejected batches") + the Quality Release & Billability Policy — full path
  agent → `contract-toolbox` → `contracts-kb-mcp` → FoundryIQ KB (needs row 18 grant).

## Open decisions

- **Search SKU:** planning **Basic** (matches every working KB in the sub:
  `rg-forge`, `rg-waypoint-e2e-*`). Free tier (F, $0, 1/sub) would host a few
  markdown docs but is risky for Foundry integrated vectorization — revisit only
  if cost matters more than reliability.
- **KB creation method (rows 12–13):** RESOLVED — Azure AI Search agentic
  retrieval (`knowledgeSources`/`knowledgeBases` on the Search service via preview
  REST). See "KB creation method (confirmed)" above.
- **Managed vs BYO search:** sticking with BYO Azure AI Search (the repo's proven
  `contracts-ks`/`contracts-kb` shape) unless the project supports a managed
  FoundryIQ knowledge base that skips standing up our own Search service.

## Automation target (later)

1. Fold rows 6–11 into `infra` as `AI_PROJECT_DEPENDENT_RESOURCES` (search +
   storage + connections) and an added embedding deployment, so `azd provision`
   stands up the substrate.
2. A single `create-foundryiq` script does rows 8, 12–16 (upload → knowledge
   source → knowledge base → KB MCP connection → toolbox → RBAC), idempotent like
   `contracts_kb_upload.py`.
3. **Post-deploy agent-identity grant (row 18):** after `azd deploy contract-agent`,
   resolve the agent **instance** MI (`azd ai agent show` → `instance_identity.principal_id`)
   and assign it `Foundry User` at project scope, then allow ~5–10 min propagation.
   The blueprint principal can't take role assignments, so this must key off the
   instance MI. Gate it on `enableHostedAgents` in the deploy pipeline.
4. Verify with `tools/deploy/scripts/verify_kb_retrieval_trace.py`.
