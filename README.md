<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="https://raw.githubusercontent.com/caldova/.github/main/profile/assets/caldova-logo-white.svg"
    />
    <source
      media="(prefers-color-scheme: light)"
      srcset="https://raw.githubusercontent.com/caldova/.github/main/profile/assets/caldova-logo-color.svg"
    />
    <img
      src="https://raw.githubusercontent.com/caldova/.github/main/profile/assets/caldova-logo-color.svg"
      width="560"
      alt="Caldova"
    />
  </picture>
</p>

<h1 align="center">Waypoint</h1>

<p align="center">
  <strong>
    One repo. One Azure deployment. One live, contract-grounded story.
  </strong>
  <br />
  From synthetic business records to hosted Foundry agents and governed
  application workflows.
</p>

<p align="center">
  <a href="https://github.com/caldova/waypoint/actions/workflows/deploy.yml">
    <img
      alt="Deploy to Azure"
      src="https://img.shields.io/badge/1._Deploy_to_Azure-0969DA?style=for-the-badge&amp;logo=githubactions&amp;logoColor=white"
    />
  </a>
  <a href="https://github.com/copilot/app/launch?open=ghapp%3A%2F%2Fsession%2Fnew%3Frepo%3Dcaldova%252Fwaypoint%26mode%3Dinteractive%26prompt%3DStart%2520the%2520Pharmashield%2520Foundry%2520demo.">
    <img
      alt="Open the presenter guide"
      src="https://img.shields.io/badge/2._Present_the_Demo-57606A?style=for-the-badge"
    />
  </a>
</p>

<p align="center">
  <a href="docs/getting-started.md">Developer setup</a>
  ·
  <a href="docs/architecture.md">Architecture</a>
  ·
  <a href="docs/status.md">Project status</a>
</p>

Waypoint is Caldova's invoice assurance workspace for contract manufacturing.
Caldova is a fictional pharmaceutical operations company used to demonstrate
how a real enterprise application can combine business records, governed agent
workflows, evaluation, optimization, and deployment automation.

> [!NOTE]
> All suppliers, invoices, contracts, policies, findings, and evidence in this
> repository are synthetic demo data.

## Deploy once, present the story

The complete demo path has two parts: deploy the shared Azure environment,
then open the live presenter experience. If your team already has a working
Waypoint environment with `waypoint-agent`, skip directly to
[Present the demo](#2-present-the-demo).

### 1. Deploy the demo environment

#### Configure deployment access once

> [!IMPORTANT]
> A deployment owner must establish GitHub-to-Azure OIDC trust once for this
> repository in each target tenant. The repeatable deployment is one click after this
> trust is configured. No Azure client secret is stored in GitHub.

The deployment owner needs:

- an Azure identity that can create app registrations, service principals,
  resource groups, and role assignments;
- repository administrator access;
- Azure CLI, GitHub CLI, and `jq`; and
- an authenticated Azure and GitHub CLI session.

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

The bootstrap is idempotent. It creates or reuses the deployment identity,
configures GitHub's federated credential, assigns the required Azure roles, and
writes the repository variables consumed by the deployment workflow.

See [Azure deployment](docs/deployment.md) for permissions, optional settings,
parallel environments, and troubleshooting.

#### Run the deployment

[![Open the Deploy Azure workflow](https://img.shields.io/badge/Open_Deploy_Azure-0969DA?style=flat-square&logo=githubactions&logoColor=white)](https://github.com/caldova/waypoint/actions/workflows/deploy.yml)

1. Select **Run workflow**.
2. Keep the defaults for a first deployment.
3. Start the workflow and follow the acceptance job through completion.

> **Current status caveat.** A fresh deployment depends on Azure-side
> hosted-agent provisioning and co-located knowledge-base resources being healthy
> in the selected region. A brand-new run can fail at the agent-deploy stage for
> reasons outside this repository. See [Azure deployment](docs/deployment.md)
> before a first run.

The default path deploys:

- the Waypoint web application, API, PostgreSQL database, authentication, and
  telemetry;
- the synthetic corpus and Waypoint seed data;
- the Foundry project, hosted-agent `gpt-5.5` deployment, KB `gpt-5-mini`
  deployment, embedding deployment, search, and `contracts-kb`;
- the single `waypoint-agent`, which serves every surface and owns the sole
  governed write path into Waypoint; and
- an acceptance artifact proving endpoint health, agent availability, a
  completed assurance run, and real KB retrieval with no fallback.

The launch package is FoundryIQ-only. Fabric/OneLake, WorkIQ, WebIQ, and
FabricIQ modules remain in the repository for future development but are not
inputs, stages, resources, or agents in the one-click deployment.

The full deployment targets the **caldova** Foundry project in **West US**.
Hosted agents use `gpt-5.5`, while `contracts-kb` answer synthesis uses
co-located `gpt-5-mini`, and acceptance fails if the run falls back. Region
selection still matters because Azure AI Search, Foundry, both model
deployments, and hosted-agent provisioning must all be healthy in the selected
region — see [Azure deployment](docs/deployment.md) before choosing a region. In the app, a reviewer can run assurance for one
invoice or select up to 25 visible invoices and start a batch. The batch starts
at most four new runs concurrently, reuses active invoice runs, and reports
independent accepted, reused, not-found, or start-failed outcomes. Every run
invokes `waypoint-agent`, which persists its result only through the agent's
single governed writer.

For the exact batch steps and the controlled evaluation-to-release flow, see
[Agent quality operations](docs/quality-operations.md).

### 2. Present the demo

[![Launch the demo in GitHub Copilot](https://img.shields.io/badge/Launch_in_GitHub_Copilot-57606A?style=for-the-badge)](https://github.com/copilot/app/launch?open=ghapp%3A%2F%2Fsession%2Fnew%3Frepo%3Dcaldova%252Fwaypoint%26mode%3Dinteractive%26prompt%3DStart%2520the%2520Pharmashield%2520Foundry%2520demo.)

The launcher opens GitHub Copilot, clones or opens this repository, starts an
interactive session, and supplies the kickoff prompt. The repo-scoped skill and
canvas load from `.github/skills/` and `.github/extensions/`; no separate plugin
installation is required.

Before running the live audit, authenticate Azure CLI on the presenter machine
to the tenant containing the deployment. If you open the repository manually,
ask Copilot:

> Start the Pharmashield Foundry demo.

The repo-scoped skill opens the **Pharmashield · Foundry live demo** canvas. It
discovers the deployed Foundry project, checks that `waypoint-agent` is
available, and enables one primary action: **Run grounded audit**.

The Aster Ridge story is live:

- the hosted agent receives the canonical invoice question;
- Foundry IQ calls `knowledge_base_retrieve`;
- Trace shows the exact query, returned contract text, and source references;
  and
- the presenter can distinguish invoice-only proof from contract-grounded
  evidence without starting Ollama, Aspire, or the Waypoint web app.

[![Open the complete presenter guide](https://img.shields.io/badge/Open_Presenter_Guide-57606A?style=flat-square)](docs/foundry-demo.md)

## What the reference app demonstrates

| Capability | What it shows |
| --- | --- |
| Application | A production-style Waypoint app with API, web UI, auth, telemetry, and PostgreSQL persistence. |
| Corpus | A realistic synthetic domain corpus: suppliers, contracts, policies, invoice facts, scenarios, seed data, and generated documents. |
| Agents | A single castia-based `waypoint-agent` for invoice assurance: read-only evidence and status tools, multi-protocol surfaces, and one governed write boundary. |
| Evaluations | Foundry-native evaluations plus Caliber datasets, graders, golden cases, calibration, and quality gates. |
| Optimization | Foundry Agent Optimizer and Caliber RFT/RLE planning, cost-quality tradeoffs, promotion metadata, and telemetry backfill workflows. |
| Deployment | An idempotent workflow for the app, corpus, agent, cloud resources, seed data, and cross-system wiring. |

## How it works

```mermaid
flowchart LR
    Corpus[Synthetic invoices<br/>contracts and policies]
    App[Waypoint<br/>governed system of record]
    Agent[waypoint-agent<br/>read-only evidence + FoundryIQ]
    Writer[Governed writer<br/>sole write path]
    Evals[Evaluate and optimize]

    Corpus --> App
    Corpus --> Agent
    App --> Agent
    Agent --> Writer
    Writer --> App
    Agent --> Evals
```

Waypoint remains the governed boundary. The agent's evidence and status tools
are read-only, and its single governed writer is the only path allowed to write
governed run results.

## The Caldova story

Caldova relies on contract manufacturers to produce medicines, packaging,
testing, logistics, and release services. Those suppliers send complex
invoices that must be reconciled against contracts, policies, purchase orders,
batch records, quality events, capacity approvals, and market context.

Waypoint helps teams review those invoices, investigate evidence, track
findings, manage governed cases, and prepare approved actions. Agents assist
with evidence gathering and recommendations, but Waypoint remains the system
of record for decisions, writes, audit, and approvals.

## Develop locally

The local development path is separate from the seller demo. It exercises the
Waypoint application, corpus tooling, agents, evaluations, and deployment
checks without requiring the presenter canvas.

- [Getting started](docs/getting-started.md)
- [Waypoint application runtime](apps/waypoint/README.md)
- [Architecture](docs/architecture.md)
- [Project status](docs/status.md)

## Repository map

| Path | Caldova responsibility |
| --- | --- |
| `apps/waypoint/` | Waypoint itself: Aspire AppHost, FastAPI API, React web app, infrastructure, tests, and product docs. |
| `modules/corpus/` | Synthetic suppliers, contracts, policies, invoice scenarios, seed generation, document generation, and upload tooling. |
| `modules/agents/` | The single `waypoint-agent` (castia-based, multi-protocol) and its WaypointIQ toolbox/OpenAPI contract. |
| `modules/evals/` | Datasets, graders, calibration, quality gates, and repeatable checks for agent behavior. |
| `modules/optimization/` | Optimizer artifacts, RFT/RLE materials, cost-quality demos, promotion metadata, and telemetry-backed improvement planning. |
| `tools/deploy/` | Environment discovery, preflight, Key Vault, MSAL, OIDC, deployment, seed import, wiring, and acceptance tooling. |
| `.github/extensions/` | Copilot canvas extensions used to inspect, demonstrate, and operate the reference system. |
| `.github/skills/` | Repo-scoped Copilot skills, including the one-step Pharmashield Foundry demo launcher. |

## Documentation

| Guide | Purpose |
| --- | --- |
| [Project status](docs/status.md) | Validated paths, current caveats, and work still in progress. |
| [Getting started](docs/getting-started.md) | Local developer prerequisites and validation commands. |
| [Azure deployment](docs/deployment.md) | Deploying the single agent (azd + castia) and the app. |
| [Foundry demo](docs/foundry-demo.md) | Live Pharmashield presenter workflow and fidelity contract. |
| [Architecture](docs/architecture.md) | Application, corpus, agent, evaluations, optimization, and deployment layers. |
| [Agent quality operations](docs/quality-operations.md) | Full batch assurance and the five-step run, inspect, measure, improve, and release workflow. |
| [Data disclaimer](docs/data-disclaimer.md) | Scope and handling of the synthetic Caldova data set. |
| [Repository settings](docs/repository-settings.md) | Recommended settings for publishing and operating the repository. |

See [Security](SECURITY.md), [Contributing](CONTRIBUTING.md), and
[Support](SUPPORT.md) for public-use expectations.
