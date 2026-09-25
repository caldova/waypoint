# Azure deployment

Waypoint deploys in two independent parts: the **application** (web, API,
PostgreSQL) and the hosted **contract agents** in the caldova Foundry project.
Each has its own workflow.

## The agents

`contract-expert`, `contract-policy-expert`, and `contract-agent` are deployed
with `azd` + [castia](https://github.com/sethjuarez/castia) to the caldova
Foundry project (**West US**), either locally or through the
[Deploy contract agents workflow](../.github/workflows/deploy.yml).

Locally, from the repository root:

```bash
azd provision            # shared Foundry resources + agent/KB model deployments
castia deploy            # reconcile azure.yaml protocols from the agent decorators
azd deploy contract-expert
azd deploy contract-policy-expert
azd deploy contract-agent
```

`azd provision` is only needed on the first run or after infrastructure changes.
`gpt-6-astra` is pinned for hosted agents in `infra/main.parameters.json`;
`contracts-kb` answer synthesis currently stays on co-located `gpt-5.5` because
Azure AI Search rejected `gpt-6-astra` as an unsupported knowledge-base model.
The knowledge base also needs Azure AI Search, Foundry, and the embedding/model
deployments in the **same** region so `knowledge_base_retrieve` does not run
cross-region and fall back.

### CI deployment

The workflow uses GitHub OIDC and stores no Azure client secret. Wire these
repository variables once (see `tools/deploy/scripts/oidc.sh` for the idempotent
bootstrap):

| Variable | Purpose |
| --- | --- |
| `AZURE_CLIENT_ID` | Client ID of the GitHub OIDC deployment identity. |
| `AZURE_TENANT_ID` | Target Entra tenant ID. |
| `AZURE_SUBSCRIPTION_ID` | Target Azure subscription ID. |
| `AZD_ENV_NAME` | azd environment name; defaults to `caldova`. |
| `AZURE_LOCATION` | Azure region; defaults to `westus`. |

Run **Actions → Deploy contract agents**, enabling **provision** on the first run.

For the clean three-agent environment, use the
[`caldova-agents` buildout ledger](caldova-agents-buildout.md). It maps the
manual setup to the existing Bicep modules and tracks the remaining automation
gaps for FoundryIQ, toolbox publishing, RBAC, and acceptance.

## The application

The Waypoint app (Aspire AppHost, FastAPI API, React web, PostgreSQL, auth, and
telemetry) lives in `apps/waypoint` and is deployed to the Caldova tenant by the
[Deploy Waypoint app workflow](../.github/workflows/deploy-app.yml). It runs on
every push to `v2` that touches `apps/waypoint/**` and on demand from
**Actions → Deploy Waypoint app**.

The workflow runs `aspire deploy` (via `tools/deploy/scripts/aspire_deploy.sh`)
against the existing `waypoint-rg` resource group. PostgreSQL is an existing
Flexible Server and is not provisioned; Fabric/OneLake is not enabled.
The Caldova subscription auto-stops PostgreSQL after hours, so the workflow
starts the server first if it is stopped. After the
deploy it checks API `/health` (200), unauthenticated `/api/runs` (401), and the
web root (200).

All target values live in the `caldova` GitHub Environment (deployments limited
to the `v2` branch), so the repository-level `AZURE_*` variables used by the
agent workflow are not affected:

| Name | Kind | Purpose |
| --- | --- | --- |
| `AZURE_CLIENT_ID` | variable | `waypoint-app-gha-oidc` OIDC identity (1). |
| `AZURE_TENANT_ID` | variable | Caldova tenant ID. |
| `AZURE_SUBSCRIPTION_ID` | variable | Caldova subscription ID. |
| `AZURE_LOCATION` | variable | Region (`swedencentral`). |
| `AZURE_RESOURCE_GROUP` | variable | App resource group (`waypoint-rg`). |
| `WAYPOINT_MSAL_TENANT_ID` | variable | Entra tenant for the `waypoint` app registration. |
| `WAYPOINT_MSAL_CLIENT_ID` | variable | `waypoint` API app registration client ID. |
| `WAYPOINT_MSAL_REDIRECT_URI` | variable | Web SPA redirect URI. |
| `WAYPOINT_MSAL_ALLOWED_APP_IDS` | variable | Optional agent app IDs (CSV). |
| `WAYPOINT_POSTGRES_SERVER_NAME` | variable | Existing PostgreSQL Flexible Server name. |
| `POSTGRES_APP_PASSWORD` | secret | Password for the `waypoint_app` DB role. |

(1) Contributor + User Access Administrator on `waypoint-rg` only.

The OIDC federated credential trusts
`repo:caldova@297935432/waypoint@1301973660:environment:caldova` (this repository
uses immutable OIDC subject claims).

> The previous one-click workflow that provisioned the app and a seven-agent
> fleet together has been retired. Its orchestration remains available in git
> history if a stage needs to be re-derived for the app deployment.

## Quality and optimization

Agent quality and optimization run through `castia eval` and `castia optimize`.
Use `contract-policy-expert` for FoundryIQ-only answer quality and
`contract-agent` for workflow/writeback correctness, backed by the datasets and graders in
[modules/evals](../modules/evals/README.md) and the Agent Optimizer / RFT assets
in [modules/optimization](../modules/optimization/README.md).
