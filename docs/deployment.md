# Azure deployment

Waypoint now has a root GitHub Actions entry point for repeatable Azure deployment:

```text
.github/workflows/deploy.yml
```

The current default path deploys the Waypoint app, Fabric/OneLake corpus storage,
and the full hosted agent suite. Assurance Orchestrator still starts with only
the WebIQ and FoundryIQ internal fan-out lanes enabled; WorkIQ and FabricIQ are
deployed but disabled in the orchestrator until their tenant-specific
Microsoft 365 and Fabric connections are ready.

| Component | Deploys by default | Active in Assurance Orchestrator fan-out by default | Notes |
| --- | --- | --- | --- |
| Waypoint app/API | Yes | N/A | Aspire deploy provisions the app runtime, PostgreSQL, auth settings, and optional Fabric hooks. |
| `invoice-analyst` | Yes | N/A | Hosted analyst surface. |
| `assurance-orchestrator` | Yes | N/A | Coordinates invoice assurance and applies the fan-out lane flags below. |
| WorkIQ / `collaboration-evidence-expert` | Yes | No | Kept off until live Microsoft 365 access is configured. WorkIQ evidence is user-scoped; headless runs legitimately see no M365 data. |
| WebIQ / `market-evidence-expert` | Yes | Yes | External/web evidence lane. |
| FoundryIQ / `contract-policy-expert` | Yes | Yes | Contract/policy knowledge lane; requires the Search knowledge-base MCP connection. |
| FabricIQ / `operations-data-expert` | Yes | No | Kept off until Fabric/OneLake resources and semantic data are ready. |
| `waypoint-recorder` | Yes | N/A | Write-boundary agent endpoint is prewired for the orchestrator. |

## Required GitHub variables

Configure these as repository or environment variables before running **Actions -> Deploy Azure**:

| Variable | Purpose |
| --- | --- |
| `AZURE_CLIENT_ID` | Entra application/client id for the GitHub OIDC deploy identity. |
| `AZURE_TENANT_ID` | Tenant id. |
| `AZURE_SUBSCRIPTION_ID` | Subscription id. |
| `AZURE_LOCATION` | Azure region. Defaults to `swedencentral` when omitted. |
| `AZURE_RESOURCE_GROUP` | App resource group for Waypoint/Aspire. Defaults to `rg-waypoint` when omitted. |

The workflow creates or reuses a deployment Key Vault in the **state resource group** (separate from the app RG). The KV is named `kv-waypoint-<env+sub-hash>` by default unless overridden, so parallel environments in the same subscription never collide. It stores generated-once API keys and PostgreSQL passwords there so reruns are stable and no generated secret needs to be copied into GitHub.

## Optional variables

| Variable | Purpose |
| --- | --- |
| `AZURE_STATE_RESOURCE_GROUP` | State resource group for the deployment Key Vault. Defaults to `rg-waypoint-state`. |
| `DEPLOY_KEY_VAULT_NAME` | Override the generated deployment Key Vault name. |
| `WAYPOINT_POSTGRES_SERVER_NAME` | Stable PostgreSQL Flexible Server name. Recommended after the first successful run. |
| `WAYPOINT_POSTGRES_FIREWALL_RULES_JSON` | Override PostgreSQL firewall rules. The default permits Azure services for the app path. |
| `WAYPOINT_MSAL_CLIENT_ID` | Reuse an existing Waypoint app registration. If absent, the workflow creates one named `waypoint`. |
| `WAYPOINT_MSAL_DISPLAY_NAME` | Override the MSAL app registration display name (default `waypoint`). |
| `AZURE_AI_PROJECT_ENDPOINT` / `AZURE_AI_PROJECT_ID` | Deploy agents into an existing Foundry project instead of provisioning one. |
| `AZURE_AI_ACCOUNT_NAME` / `AZURE_AI_PROJECT_NAME` | Reuse an existing Foundry account/project by name. |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `MODEL_NAME`, `MODEL_VERSION`, `MODEL_SKU_NAME`, `MODEL_CAPACITY` | Override the chat model deployment used by hosted agents. |
| `AZURE_AI_EMBEDDING_DEPLOYMENT_NAME`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_MODEL_VERSION`, `EMBEDDING_MODEL_SKU_NAME`, `EMBEDDING_MODEL_CAPACITY` | Override the embedding deployment used by FoundryIQ knowledge retrieval. |
| Workflow inputs `workiq_enabled`, `webiq_enabled`, `foundryiq_enabled`, `fabriciq_enabled` | Control Assurance Orchestrator fan-out lanes. Defaults are WorkIQ off, WebIQ on, FoundryIQ on, FabricIQ off. |

## Running the deployment

1. In GitHub, open **Actions -> Deploy Azure -> Run workflow**.
2. Leave `deploy_app`, `deploy_agents`, `provision_agents`, and `seed_data` enabled for a first run.
3. Leave `fabric_provision_enabled` enabled for a full deployment. Keep
   `fabriciq_enabled` disabled until the Fabric Data Agent path is ready.
4. Re-run safely as needed. The workflow reuses Key Vault secrets, app registrations, Azure resources, and Foundry project infrastructure where possible.

## Parallel / non-destructive environments

Supply the following `workflow_dispatch` string inputs to spin up a fully independent parallel environment in the same subscription. Omit all of them for the default standalone deployment (backwards compatible).

| Input | Purpose | Default |
| --- | --- | --- |
| `azure_location` | Azure region override. | `AZURE_LOCATION` repo var or `swedencentral` |
| `app_resource_group` | App resource group for Waypoint/Aspire. Key Vault is always in the state RG. | `AZURE_RESOURCE_GROUP` repo var or `rg-waypoint` |
| `state_resource_group` | Separate state resource group for the deployment Key Vault. | `AZURE_STATE_RESOURCE_GROUP` repo var or `rg-waypoint-state` |
| `key_vault_name` | Override Key Vault name. Derived as `kv-waypoint-<env+sub-hash>` when empty. | derived |
| `msal_display_name` | MSAL app registration display name (unique per parallel env). | `WAYPOINT_MSAL_DISPLAY_NAME` var or `waypoint` |
| `postgres_server_name` | PostgreSQL Flexible Server name (unique per parallel env). | `WAYPOINT_POSTGRES_SERVER_NAME` var or derived |
| `fabric_capacity_name` | Fabric capacity name override. | `WAYPOINT_FABRIC_CAPACITY_NAME` var or `waypointcorpus` |
| `fabric_workspace_name` | Fabric workspace name. | `WAYPOINT_FABRIC_WORKSPACE_NAME` var or `waypoint-corpus` |
| `fabric_lakehouse_name` | Fabric lakehouse name. | `WAYPOINT_FABRIC_LAKEHOUSE_NAME` var or `corpus` |
| `azd_env_name` | azd environment name (also scopes the Key Vault name hash). | `AZD_ENV_NAME` var or `waypoint-agents` |

Each `azd_env_name` gets its own workflow concurrency slot so parallel environments can run simultaneously without cancelling each other.
For any non-default `azd_env_name`, validation requires explicit app/state
resource groups, MSAL display name, and PostgreSQL server inputs. Fabric
deployments additionally require explicit capacity, workspace, and lakehouse
inputs. Repository-variable fallbacks are intentionally rejected for custom
environments so a partially specified parallel run cannot mutate the default
environment.

## Deployment stages

The workflow runs these stages in order:

1. **validate** — checks required repo variables.
2. **keyvault** — creates/reuses the Key Vault in the state RG; generates-once all API keys and PostgreSQL passwords.
3. **msal** — creates/reuses the single-tenant Waypoint MSAL app registration,
   exposes the v2 `user_impersonation` delegated scope, and reconciles the
   application roles. The deployed tenant is the explicit `AZURE_TENANT_ID`;
   it is not inferred from the signing-in user. The post-deploy app stage unions
   the generated web callback and login URIs into the SPA redirects.
4. **corpus-seed** — generates `waypoint-seed.json` from the ledgerfield corpus.
5. **deploy-app** — deploys Waypoint (Aspire) to Azure Container Apps with PostgreSQL and MSAL wired.
6. **fabric-provision** — *(gated on `fabric_provision_enabled`)* explicitly runs `apps/waypoint/infra/scripts/provision-fabric.sh` to create the Fabric workspace and lakehouse, grants the app MI and deploy SP workspace Member roles, and updates the API container app with `APP_ONELAKE_*` values.
7. **provision-agents** — creates the isolated AI Services account, its
   deployment-principal Foundry roles, and the child project as a durable,
   idempotent bootstrap boundary, then runs `azd provision` once to reconcile
   the complete Foundry environment. It deploys only the shared `gpt-5.5`
   completion model and `text-embedding-3-large`, configures Content
   Understanding to reuse those deployments, and exposes the project endpoint
   and contracts-KB storage/search coordinates as job outputs.
8. **deploy-agents** — matrix job (one leg per hosted agent). Each leg re-selects the azd environment, hydrates all Foundry outputs from the exact `^<env>-[0-9]+$` ARM deployment, seeds Waypoint writer/reader keys from Key Vault, wires API base URL/scope, lane flags, and orchestrator expert endpoints, then deploys the agent.
9. **onelake-upload** — *(gated on Fabric enabled + successful workspace provisioning)* idempotent upload of the ledgerfield corpus to OneLake using `ledgerfield upload-onelake`.
10. **contracts-kb-upload** — *(gated on FoundryIQ enabled + resolved storage coordinates)* idempotent blob sync and reindex using `ledgerfield upload-contracts-kb`.
11. **seed-import** — imports `waypoint-seed.json` into the deployed Waypoint API. Waits for OneLake upload when Fabric is enabled.
12. **acceptance** — runs HTTP probes via `verify_deployment.py` with the KV reader key, verifies every declared hosted agent exists and has an active version, drives a seeded invoice through the hosted orchestrator, confirms the recorder produced a newly updated successful terminal Waypoint run with telemetry correlation, inventories deployed Container Apps, and writes a sanitized JSON evidence artifact tied to `github.sha`. A deployment with disabled IQ lanes is explicitly reported as `partial`; required-stage or probe failures report `failed`.

### Foundry validation

The isolated deployment provisions its own Foundry account and project through
the GitHub OIDC identity. Its model template contains exactly two deployments:
the shared `gpt-5.5` completion model and `text-embedding-3-large`. Content
Understanding reuses the shared completion deployment rather than adding a
second completion model. Account creation and the OIDC principal's account-level
Foundry role assignments complete in a separate deployment. The workflow then
creates the child project with an idempotent resource PUT before `azd`
reconciles the full template. The Bicep reconciler declares that bootstrapped
project as `existing` while continuing to manage its models, roles, connections,
storage, search, registry, and monitoring resources. This avoids the provider's
`715-123420` validation rejection for a project PUT inside a complete ARM
template while retaining a fresh, workflow-owned project. Do not silently reuse
an existing Foundry account/project; that breaks parallel-environment isolation
and makes the deployment evidence misleading.

## Deployment manifest and acceptance probes

`tools/deploy/deployment.manifest.json` is the machine-readable baseline for the
consolidated deployment. It declares the canonical source roots, default
environment shape, expected agent fleet, and HTTP acceptance probes.

After a deployment, run the probes with the deployed URLs:

```bash
python tools/deploy/scripts/verify_deployment.py \
  --manifest tools/deploy/deployment.manifest.json \
  --api-base-url "https://<api-fqdn>" \
  --web-base-url "https://<web-fqdn>" \
  --api-key "$WAYPOINT_READER_API_KEY" \
  --require-authenticated \
  --output deployment-evidence.json
```

The command exits nonzero when a required probe fails. Without `--api-key`,
authenticated probes are reported as skipped unless `--require-authenticated`
is set.

The `acceptance` workflow job runs these probes automatically after every
deployment. Full app+agent+seed runs also use `verify_terminal_run.py` to prove
the orchestrator-to-recorder lifecycle, then upload the combined evidence as a
`deployment-evidence-<sha>` artifact.

## What still needs manual setup

- The GitHub OIDC deploy identity must exist and have sufficient Azure roles before the workflow can log in.
- Foundry model quota/capacity must be available in the selected region.
- FoundryIQ requires the Bicep-managed Azure AI Search knowledge-base MCP connection. If `AZURE_AI_SEARCH_KB_MCP_CONNECTION_NAME` is missing after provisioning, the workflow fails rather than deploying a broken contract-policy expert.
- Microsoft 365/Teams publishing remains manual/admin-gated.
- Fabric/OneLake provisioning is part of the default full deployment. FabricIQ
  fan-out remains disabled by default until its Data Agent connection is ready.
