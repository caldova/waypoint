# Caldova agents Foundry buildout

This is the working ledger for standing up a clean Foundry project for the
three-agent Castia portfolio and turning the manual steps into repeatable infra.

## Target environment

| Field | Proposed value | Notes |
| --- | --- | --- |
| azd environment | `caldova-agents` | Keeps this buildout separate from the proven `caldova` environment. |
| Resource group | `rg-caldova-agents` | Set with `AZURE_RESOURCE_GROUP`; otherwise Bicep derives `rg-${AZURE_ENV_NAME}`. |
| Foundry project | `caldova-agents` | Set `AZURE_AI_PROJECT_NAME=caldova-agents` instead of the default `ai-project-${environmentName}`. |
| Foundry account | `ai-account-wfckthnpbzzia` | Created by `azd provision`; keep the concrete value in azd env and use docs only for tracking. |
| Region | `westus` | Keep Foundry, Azure AI Search, embedding, and model deployments co-located. |
| Hosted agents | `contract-expert`, `contract-policy-expert`, `contract-agent` | Declared in repo-root `azure.yaml`. |
| Toolbox | `contract-toolbox` | Starts with FoundryIQ; later adds WorkIQ, WebIQ, and FabricIQ lanes. |

Do not put subscription IDs, tenant IDs, endpoints, resource IDs, or tokens in
git. Capture them in the azd environment and in this ledger only as placeholders.

## Existing Bicep surface to reuse

| Need | Existing surface | Status |
| --- | --- | --- |
| Resource group | `infra/main.bicep` | Ready. |
| Foundry account/project | `infra/core/ai/ai-project.bicep` | Ready; set `AZURE_AI_PROJECT_NAME=caldova-agents`. |
| Reuse existing project | `infra/core/ai/existing-ai-project.bicep` | Ready; use only if we intentionally target an existing account/project. |
| Model deployments | `aiProjectDeploymentsJson` in `infra/main.parameters.json` | Ready for `gpt-6-astra` agents, `gpt-5.5` KB synthesis, and the embedding deployment required by FoundryIQ. |
| ACR for hosted container agents | `infra/core/host/acr.bicep` via dependent resource union | Ready for `contract-agent` Docker deploy. |
| Code-deploy hosted agents | repo-root `azure.yaml` | Ready for `contract-expert` and `contract-policy-expert`. |
| Monitoring/App Insights | `enableMonitoring` + `infra/core/monitor/*` | Ready. |
| Azure AI Search | `infra/core/search/azure_ai_search.bicep` | Ready as a dependent resource when `AI_PROJECT_DEPENDENT_RESOURCES` includes `azure_ai_search`. |
| Storage for KB source docs | `infra/core/storage/storage.bicep` | Ready as a dependent resource when `AI_PROJECT_DEPENDENT_RESOURCES` includes `storage`. |
| Project connections | `aiProjectConnectionsJson` + `infra/core/ai/connection.bicep` | Ready for declared connections; toolbox-specific remote-tool connection still needs script coverage. |

## Manual buildout ledger

Update this table as each step is performed. Anything marked "manual now" is a
candidate for the first automation pass.

| # | Step | Source of truth | Automation state | Evidence to capture |
| --- | --- | --- | --- | --- |
| 1 | Create/select azd environment `caldova-agents` | azd env | done manually | `caldova-agents`, `westus`, `rg-caldova-agents` |
| 2 | Provision Foundry account/project `caldova-agents` | `infra/main.bicep` | done via Bicep | account `ai-account-wfckthnpbzzia`, project `caldova-agents` |
| 3 | Deploy `gpt-6-astra` agent/teacher model | `aiProjectDeploymentsJson` | done via Bicep | version `2026-09-03`, `GlobalStandard`, capacity 50 |
| 3a | Retain `gpt-5.5` KB synthesis model | `aiProjectDeploymentsJson` | done via Bicep | Search KB model allow-list rejected `gpt-6-astra` on 2026-09-18 |
| 3b | Select MAI RFT target | Foundry fine-tuning workflow | discovery pending | `MAI-Thinking-1` is visible in catalog; explicit `*-finetune` quota currently appears for `mai-code-1.1-flash` |
| 4 | Deploy embedding model for FoundryIQ | `aiProjectDeploymentsJson` | done via Bicep | `text-embedding-3-large`, version `1`, `GlobalStandard`, capacity 50 |
| 5 | Provision Search + Storage | `aiProjectDependentResourcesJson` | done via Bicep | search `search-wfckthnpbzzia`, storage `stwfckthnpbzzia`, connections `contracts-kb-search`/`contracts-kb-storage` |
| 6 | Upload contract/policy corpus | `modules/corpus` | done manually | 18 markdown docs uploaded to `knowledge/contracts`; Windows upload used a session-local minimal venv because locked `deltalake` lacks a Windows wheel |
| 7 | Create Search knowledge source/base | Search REST objects | done manually | `contracts-ks`, `contracts-kb`, API `2026-08-01-preview`; indexer processed 18, failed 0 |
| 8 | Create KB MCP remote-tool connection | Foundry project connection | done manually | `contracts-kb-mcp`, project-managed identity, audience `https://search.azure.com` |
| 9 | Publish `contract-toolbox` | `modules/agents/contract-agent/toolbox.yaml` | done manually | version `1`, endpoint written to `TOOLBOX_CONTRACT_TOOLBOX_MCP_ENDPOINT` |
| 10 | Deploy `contract-expert` | repo-root `azure.yaml` | done via azd | active version `4`, model env `gpt-6-astra` |
| 11 | Deploy `contract-policy-expert` | repo-root `azure.yaml` | done via azd | active version `5`, model env `gpt-6-astra`, toolbox env present |
| 12 | Deploy `contract-agent` | repo-root `azure.yaml` | done via azd | active version `3`, model env `gpt-6-astra`, responses/activity/invocations endpoints |
| 13 | Grant hosted agent instance identities | RBAC | done manually | `Foundry User` assigned at project scope for each agent instance MI |
| 14 | Attach WorkIQ lane | toolbox connection | manual now | connection name, auth boundary, activity/headless policy |
| 15 | Attach WebIQ lane | toolbox connection | manual now | connection name and allowed tools |
| 16 | Attach FabricIQ lane | toolbox connection | manual now | connection name and allowed tools |
| 17 | Run acceptance | deploy probes + Foundry invoke | update needed | health, retrieval trace, writeback boundary |

## Automation backlog

1. Add an environment preset for `caldova-agents` that sets
   `AZURE_RESOURCE_GROUP`, `AZURE_AI_PROJECT_NAME`, `ENABLE_HOSTED_AGENTS=true`,
   `AZD_AGENT_SKIP_ACR=false`, and co-located model deployment settings.
2. Extend `aiProjectDeploymentsJson` or deployment setup to include the embedding
   model required by `contracts-kb`.
3. Set `AI_PROJECT_DEPENDENT_RESOURCES` to include Search and Storage for the KB
   substrate, reusing the existing Bicep modules.
4. Promote the proven FoundryIQ manual sequence into an idempotent script:
   upload corpus docs, create/update `contracts-ks`, create/update
   `contracts-kb`, create/update `contracts-kb-mcp`, publish `contract-toolbox`,
   and write `TOOLBOX_CONTRACT_TOOLBOX_MCP_ENDPOINT` to the azd env.
5. Add post-agent-deploy RBAC automation that resolves each hosted agent
   instance managed identity and grants `Foundry User` at project scope.
6. Update acceptance to prove:
   - `contract-expert` answers with prompt-contained evidence and no tools;
   - `contract-policy-expert` calls FoundryIQ and returns cited support; and
   - `contract-agent` can see the multi-IQ toolbox surface while keeping
     `record_assurance` as the only write path.

## Promotion rule

The old `caldova` project remains the known-good demo until this ledger has
green evidence for the new `caldova-agents` environment. Do not repoint the
presenter canvas or keynote docs to `caldova-agents` until rows 10-12 and 17 are
verified.
