# Azure deployment

Waypoint deploys from the monorepo through the root GitHub Actions workflow:

```text
.github/workflows/deploy.yml
```

This is the canonical deployment guide. The default full deployment and an
unchanged rerun have both been validated. The rerun reused generated secrets,
the MSAL application, data services, and Foundry infrastructure, and skipped
hosted-agent versions whose deploy inputs were unchanged.

## Default deployment

| Component | Default | Notes |
| --- | --- | --- |
| Waypoint app/API | On | Aspire deploys the web app, API, PostgreSQL, auth, and telemetry. |
| Corpus seed | On | The corpus module generates and imports `waypoint-seed.json`. |
| Fabric/OneLake storage | Off | Opt in only when exercising the FabricIQ lane. |
| `invoice-analyst` | On | Read-only hosted analyst surface. |
| `assurance-orchestrator` | On | Coordinates one invoice-assurance run. |
| `contract-policy-expert` | On | The only evidence expert enabled by default; uses FoundryIQ and `contracts-kb`. |
| `waypoint-recorder` | On | The sole agent authorized to write governed results to Waypoint. |
| WorkIQ / `collaboration-evidence-expert` | Off | Opt in after tenant-specific Microsoft 365 access is configured. |
| WebIQ / `market-evidence-expert` | Off | Opt in after its connection and deployment path is ready. |
| FabricIQ / `operations-data-expert` | Off | Opt in after a real Fabric Data Agent path is ready. |

The default hosted fleet is exactly `invoice-analyst`,
`assurance-orchestrator`, `contract-policy-expert`, and
`waypoint-recorder`. Enabling an optional IQ input adds its expert to both the
deployment matrix and orchestrator fan-out.

## One-time OIDC bootstrap

The workflow uses GitHub OIDC and stores no Azure client secret. A deployment
owner runs the idempotent bootstrap once:

```bash
az login
gh auth login

tools/deploy/scripts/oidc.sh \
  --owner caldova \
  --repo waypoint \
  --subscription-id "$(az account show --query id -o tsv)" \
  --app-name waypoint-gha-oidc \
  --branch main \
  --pull-request
```

The bootstrap creates or reuses the Entra application and service principal,
adds branch and pull-request federated credentials, assigns the requested Azure
roles, grants the Graph permissions needed to manage the Waypoint app
registration, and writes the repository configuration consumed by the workflow.
See [OIDC setup](../modules/agents/docs/OIDC_SETUP.md) for permissions and
troubleshooting.

## Required repository variables

| Variable | Purpose |
| --- | --- |
| `AZURE_CLIENT_ID` | Client ID of the GitHub OIDC deployment identity. |
| `AZURE_TENANT_ID` | Target Entra tenant ID. |
| `AZURE_SUBSCRIPTION_ID` | Target Azure subscription ID. |
| `AZURE_LOCATION` | Azure region; defaults to `swedencentral`. |
| `AZURE_RESOURCE_GROUP` | Waypoint app resource group; defaults to `rg-waypoint`. |

The workflow creates or reuses a Key Vault in a separate state resource group.
It generates API keys and PostgreSQL passwords once and reuses them on later
runs; generated secrets do not need to be copied into GitHub.

## Optional configuration

| Variable or input | Purpose |
| --- | --- |
| `AZURE_STATE_RESOURCE_GROUP` | State resource group; defaults to `rg-waypoint-state`. |
| `DEPLOY_KEY_VAULT_NAME` | Override the derived Key Vault name. |
| `WAYPOINT_POSTGRES_SERVER_NAME` | Reuse a stable PostgreSQL Flexible Server name. |
| `WAYPOINT_POSTGRES_FIREWALL_RULES_JSON` | Override PostgreSQL firewall rules. |
| `WAYPOINT_MSAL_CLIENT_ID` | Reuse an existing Waypoint app registration. |
| `WAYPOINT_MSAL_DISPLAY_NAME` | Override the app registration display name. |
| `AZURE_AI_PROJECT_ENDPOINT` / `AZURE_AI_PROJECT_ID` | Reuse an existing Foundry project. |
| `AZURE_AI_ACCOUNT_NAME` / `AZURE_AI_PROJECT_NAME` | Reuse Foundry resources by name. |
| Model and embedding variables | Override the default `gpt-5.5` and `text-embedding-3-large` deployments. |
| `workiq_enabled` | Add the WorkIQ expert and lane. |
| `webiq_enabled` | Add the WebIQ expert and lane. |
| `foundryiq_enabled` | Enable FoundryIQ; defaults to `true`. |
| `fabriciq_enabled` | Add the FabricIQ expert and lane. |

## Run the deployment

1. Open **Actions -> Deploy Azure -> Run workflow**.
2. Keep `deploy_app`, `deploy_agents`, `provision_agents`, and `seed_data`
   enabled for a first run.
3. Leave `fabric_provision_enabled` disabled for the default FoundryIQ path.
4. Leave WorkIQ, WebIQ, and FabricIQ disabled unless their external dependencies
   are configured.
5. Follow the **Acceptance and evidence** job through completion.

The workflow is safe to rerun. It reconciles named resources, reuses Key Vault
secrets, updates the existing MSAL registration, and compares hosted-agent
deployment inputs with active versions before deploying a new version. This
skip-on-unchanged behavior is agent-level selectivity; it is not a batch
assurance feature.

Clean Entra registration creates both the application object and its service
principal, then verifies the delegated `user_impersonation` scope persisted
before deploying the SPA. Split-region Foundry bootstrap reuses the app resource
group at its existing location while creating Foundry resources in
`azure_location`.

The Aspire app job is bounded to 30 minutes with at most two 12-minute
deployment attempts. Unknown failures stop immediately; a recognized transient
gets one recovery attempt. Capacity cleanup is bounded to five minutes. If Azure reports
`ManagedEnvironmentCapacityHeavyUsageError` or `AKSCapacityHeavyUsage`, the
workflow cancels the stalled ARM deployment and removes the partial Container
Apps environment only when it contains no Container Apps. The next bounded
attempt then recreates the environment cleanly instead of updating a poisoned
partial resource indefinitely. Capacity failures on environments containing
applications fail closed and require operator review.

On a clean recreation, Azure RBAC can also report Aspire's deterministic
`AcrPull` assignment as deployed before the recreated managed identity can pull
from the registry. The bounded retry path detects that exact managed-identity
image-pull failure, reconciles `AcrPull` for the sole Aspire identity and
registry, waits for propagation, and retries. Ambiguous identity or registry
inventory fails closed.

Azure DNS can briefly return `no such host` for a newly created ACR while the
Container Apps deployment is resolving its image. That exact registry-resolution
failure receives the same single bounded retry; broader DNS failures remain
fail-fast.

## Deployment stages

1. **validate** checks required configuration and builds the selected agent
   matrix.
2. **keyvault** creates or reuses the state vault and generated-once secrets.
3. **msal** creates or reconciles the single-tenant Waypoint application.
4. **corpus-seed** generates `waypoint-seed.json`.
5. **deploy-app** deploys the Aspire app and PostgreSQL configuration.
6. **fabric-provision** creates or reconciles the OneLake storage path when
   enabled.
7. **provision-agents** reconciles the Foundry project, models, search, and
   shared infrastructure.
8. **deploy-agents** deploys the four default agents plus selected optional
   experts, skipping unchanged active versions.
9. **wire-app-operations** connects the Waypoint API assurance operation to the
   deployed orchestrator.
10. **onelake-upload** and **contracts-kb-upload** publish the corpus to the
    enabled grounding stores.
11. **seed-import** imports the generated Waypoint seed.
12. **acceptance** probes the app, inventories live hosted agents, selects one
    invoice from the deployed work queue, invokes the hosted orchestrator, and
    verifies that the recorder finalized a correlated terminal run.

Deployment acceptance deliberately exercises one invoice. The deployed app also
supports a batch envelope for up to 25 unique invoices with four concurrent
starts, active-run reuse, ordered outcomes, and failure isolation. It uses the
same orchestrator and recorder lifecycle as the single-invoice trigger.

Agent quality work is operated separately through
`.github/workflows/agent-quality-operations.yml`. The workflow exposes
controlled invoice, trace, evaluation, readiness, optimizer, and RFT operations
with sanitized artifacts. It never auto-applies, promotes, or deploys a
candidate. Live RFT submission remains protected by environment approval,
explicit spend acknowledgement, current lineage, and a reviewed first-class
submission command.

## Parallel environments

For a non-default `azd_env_name`, provide explicit isolated values for the app
resource group, state resource group, MSAL display name, PostgreSQL server, and,
when Fabric is enabled, capacity, workspace, and lakehouse names. The workflow
rejects partial custom-environment configuration so it cannot accidentally
mutate the default environment.

Each `azd_env_name` has its own workflow concurrency slot and derived Key Vault
name.

Foundry and the application can use different Azure regions. `azure_location`
controls the Foundry project, hosted agents, and model deployments;
`app_location` controls only the Aspire web/API, PostgreSQL, and Fabric
resources. When `app_location` is empty it inherits `WAYPOINT_APP_LOCATION`,
then `azure_location`, preserving the single-region default. For example, use
`azure_location=swedencentral` with `app_location=northeurope` when Foundry
requires Sweden Central but Container Apps capacity is unavailable there.

## Acceptance evidence

`tools/deploy/deployment.manifest.json` declares the canonical source roots,
default lane flags, expected default fleet, and HTTP probes. The workflow runs
those probes automatically and uploads a sanitized
`deployment-evidence-<sha>` artifact.

To run the HTTP probes independently:

```bash
python tools/deploy/scripts/verify_deployment.py \
  --manifest tools/deploy/deployment.manifest.json \
  --api-base-url "https://<api-fqdn>" \
  --web-base-url "https://<web-fqdn>" \
  --api-key "$WAYPOINT_READER_API_KEY" \
  --require-authenticated \
  --output deployment-evidence.json
```

## Remaining environment-specific setup

- The GitHub OIDC identity must exist and have sufficient Azure and Graph
  permissions.
- Foundry model quota must be available in the selected region.
- FoundryIQ requires the provisioned Azure AI Search knowledge-base MCP
  connection.
- WorkIQ, WebIQ, and FabricIQ require their own opt-in connections and evidence
  sources.
- Microsoft 365 and Teams publishing remains tenant-admin gated.
