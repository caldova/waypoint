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
| 6 | Embedding model | model deployment | `text-embedding-3-large` (planned) | pending | Vectorize contract chunks for search | usage | `az cognitiveservices ... deployment create` |
| 7 | Storage account | `Microsoft.Storage/storageAccounts` | `stsyhurnetrksxc` (planned) | pending | Blob `knowledge` container = KB source docs | ~$0 (few MB) | TBD (`az storage account create`) |
| 8 | Blob container | storage container | `knowledge/contracts/` | pending | Holds contract markdown (`contracts_kb_upload.py`) | incl. | `ledgerfield contracts-kb upload` |
| 9 | Azure AI Search | `Microsoft.Search/searchServices` | `srch-syhurnetrksxc` (planned) | pending | Index host for KB retrieval | Basic ≈ $75/mo | TBD (`az search service create`) |
| 10 | Search connection | project connection | `contracts-search` (planned) | pending | Lets project/KB reach Search | incl. | `azd ai connection` / bicep |
| 11 | Storage connection | project connection | `contracts-storage` (planned) | pending | Lets KB knowledge source reach blobs | incl. | `azd ai connection` / bicep |
| 12 | Knowledge source | FoundryIQ knowledge source | `contracts-ks` (planned) | pending | Azure Blob source feeding the index | incl. | Foundry KB API — **method TBD** |
| 13 | Knowledge base | FoundryIQ knowledge base | `contracts-kb` (planned) | pending | Exposes `knowledge_base_retrieve` | incl. | Foundry KB API — **method TBD** |
| 14 | Toolbox | Foundry toolbox | `contracts-kb` (planned) | pending | Federates KB retrieve as server-side MCP | incl. | `azd ai toolbox` (see `deploy_toolbox.py`) |

## Open decisions

- **Search SKU:** planning **Basic** (matches every working KB in the sub:
  `rg-forge`, `rg-waypoint-e2e-*`). Free tier (F, $0, 1/sub) would host a few
  markdown docs but is risky for Foundry integrated vectorization — revisit only
  if cost matters more than reliability.
- **KB creation method (rows 12–13):** `azd ai` has **no** `knowledge` command and
  `GET /knowledgeBases` 404s on the versions tried. Must confirm the Foundry
  knowledge-base data-plane API/SDK (or portal) before scripting — the one gap the
  repo does not already cover. The blob writer (row 8) and toolbox (row 14) are
  already scripted.
- **Managed vs BYO search:** sticking with BYO Azure AI Search (the repo's proven
  `contracts-ks`/`contracts-kb` shape) unless the project supports a managed
  FoundryIQ knowledge base that skips standing up our own Search service.

## Automation target (later)

1. Fold rows 6–11 into `infra` as `AI_PROJECT_DEPENDENT_RESOURCES` (search +
   storage + connections) and an added embedding deployment, so `azd provision`
   stands up the substrate.
2. A single `create-foundryiq` script does rows 8, 12–14 (upload → knowledge
   source → knowledge base → toolbox), idempotent like `contracts_kb_upload.py`.
3. Verify with `tools/deploy/scripts/verify_kb_retrieval_trace.py`.
