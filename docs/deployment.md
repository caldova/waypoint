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
every push to `main` that touches `apps/waypoint/**` and on demand from
**Actions → Deploy Waypoint app**.

The workflow runs `aspire deploy` (via `tools/deploy/scripts/aspire_deploy.sh`)
against the existing `waypoint-rg` resource group. PostgreSQL is an existing
Flexible Server and is not provisioned; Fabric/OneLake is not enabled.
The Caldova subscription auto-stops PostgreSQL after hours, so the workflow
starts the server first if it is stopped. After the
deploy it checks API `/health` (200), unauthenticated `/api/runs` (401), and the
web root (200).

All target values live in the `caldova` GitHub Environment (deployments limited
to the `main` branch), so the repository-level `AZURE_*` variables used by the
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
| `WAYPOINT_WEB_CUSTOM_DOMAIN` | variable | Optional web custom domain (`app.caldova.com`). |
| `WAYPOINT_WEB_CERTIFICATE_NAME` | variable | Managed certificate name for the web domain. |
| `WAYPOINT_API_CUSTOM_DOMAIN` | variable | Optional API custom domain (`api.caldova.com`). |
| `WAYPOINT_API_CERTIFICATE_NAME` | variable | Managed certificate name for the API domain. |
| `POSTGRES_APP_PASSWORD` | secret | Password for the `waypoint_app` DB role. |

(1) Contributor + User Access Administrator on `waypoint-rg` only.

Custom domains must be declared through these variables. `aspire deploy`
re-applies each container app's ingress, so a domain bound only in the portal or
CLI is removed on the next deploy. For a new domain, create the DNS records and
the environment managed certificate first, then set both variables.

The OIDC federated credential trusts
`repo:caldova@297935432/waypoint@1301973660:environment:caldova` (this repository
uses immutable OIDC subject claims).

> The previous one-click workflow that provisioned the app and a seven-agent
> fleet together has been retired. Its orchestration remains available in git
> history if a stage needs to be re-derived for the app deployment.

### PR previews

Every pull request that changes `apps/waypoint/web` gets its own copy of the
web app, much like Azure Static Web Apps or Netlify deploy previews. Reviewers
can click through the UI, including `/es`, alongside the code diff.

- **When:** the [Preview Waypoint web workflow](../.github/workflows/preview-web.yml)
  deploys on each push to a same-repository PR. It posts the links in a single PR
  comment that it updates in place, and shows them as the PR's `preview`
  deployment. The preview is deleted when the PR closes, and a nightly sweep
  removes anything a missed close event left behind. Fork PRs are skipped
  because they can't get Azure credentials.
- **What runs:** `web-pr-<number>` is a Container App built from the PR's head
  commit. It scales to zero when idle, so the first load after a while takes
  about 20 seconds, and idle previews cost nothing.
- **Data:** previews call the **shared production API** through the web server's
  `/api` proxy, and reviewers sign in with their normal Caldova account. Actions
  taken in a preview, such as **Run assurance**, change real demo data.
- **Isolation:** PR code reaches Azure only through the
  `waypoint-preview-deployer` identity, through the `preview` GitHub
  Environment. That identity:
  - has Contributor on `waypoint-preview-rg` only, which holds its own registry
    and Container Apps environment;
  - owns only the preview sign-in app, `waypoint-preview-web`, whose redirect
    URIs it adds and removes for each PR.

  It can't change the production apps, images, or the `waypoint` app
  registration. Because a preview runs PR code in the reviewer's signed-in
  session, only open previews of PRs you trust.

Everything is declared in Bicep under [infra/preview](../infra/preview):

- `main.bicep` covers the resource group plus the Entra objects, through the
  [Microsoft Graph Bicep extension](https://learn.microsoft.com/graph/templates/bicep/overview-bicep-templates-for-graph):
  both app registrations, the OIDC credential, admin consent, and the Graph
  permission.
- `resources.bicep` covers the registry, pull identity, and environment.
- `app.bicep` covers one PR's container app.

`tools/deploy/scripts/preview_web.sh` only adds the glue Bicep can't express:
per-PR redirect URIs on the shared sign-in app, image cleanup, and the
closed-PR sweep.

**One-time setup** needs a tenant admin who can grant Microsoft Graph app
permissions and admin consent, and `gh` admin on the repository. The script
deploys `main.bicep` and then creates the GitHub environment. Preview first,
then run it:

```bash
bash tools/deploy/scripts/preview_setup.sh --dry-run
bash tools/deploy/scripts/preview_setup.sh
```

The script derives everything from the production `caldova` environment and
`waypoint-rg`, including the immutable OIDC subject format, and is safe to
rerun. If the region has no Container Apps capacity (`AKSCapacityHeavyUsage`),
rerun it with `--environment-location <region>`, for example `northeurope`.
Until setup runs, the workflow skips with a notice.

It creates the `preview` environment with these variables:

| Name | Purpose |
| --- | --- |
| `AZURE_CLIENT_ID` | `waypoint-preview-deployer` OIDC identity. |
| `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | Caldova tenant and subscription. |
| `PREVIEW_RESOURCE_GROUP` | `waypoint-preview-rg`. |
| `PREVIEW_MSAL_CLIENT_ID` | `waypoint-preview-web` sign-in app. |
| `WAYPOINT_MSAL_TENANT_ID` | Entra tenant for sign-in. |
| `WAYPOINT_MSAL_API_SCOPE` | Production API scope (`api://<waypoint>/user_impersonation`). |
| `WAYPOINT_PREVIEW_API_URL` | API the previews proxy to. |

To debug a preview, stream its logs:
`az containerapp logs show -g waypoint-preview-rg -n web-pr-<number> --follow`.
To remove one by hand, run
`PREVIEW_RESOURCE_GROUP=waypoint-preview-rg PR_NUMBER=<number> MSAL_CLIENT_ID=<preview app> bash tools/deploy/scripts/preview_web.sh destroy`.

To remove PR previews entirely, run the uninstall. It deletes the `preview`
GitHub environment, `waypoint-preview-rg` with every preview in it, and both
preview app registrations, which takes their service principals, OIDC
credential, Graph grant, and consent with them. It only deletes what setup
tagged, and without `--yes` it prints the plan:

```bash
bash tools/deploy/scripts/preview_setup.sh --uninstall
bash tools/deploy/scripts/preview_setup.sh --uninstall --yes
```

Deleted app registrations stay restorable in Entra for 30 days.

## Quality and optimization

Agent quality and optimization run through `castia eval` and `castia optimize`.
Use `contract-policy-expert` for FoundryIQ-only answer quality and
`contract-agent` for workflow/writeback correctness, backed by the datasets and graders in
[modules/evals](../modules/evals/README.md) and the Agent Optimizer / RFT assets
in [modules/optimization](../modules/optimization/README.md).

## Versions

`main` is the only long-lived branch. Earlier lines are kept as tags:
[`v1`](https://github.com/caldova/waypoint/tree/v1) (the original `main`) and
[`v2`](https://github.com/caldova/waypoint/tree/v2) (the former `v2` branch,
now merged into `main`).
