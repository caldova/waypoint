# Caldova Waypoint

Waypoint is Caldova's invoice assurance workspace for contract manufacturing. Caldova is a fictional pharmaceutical operations company used to demonstrate how a real enterprise application can combine business records, governed agent workflows, evaluation, optimization, and deployment automation.

This repository is both the Waypoint product codebase and the reference implementation behind the demo. It is intentionally organized like a real company system: the application is the center, and the surrounding modules show how Caldova grounds, operates, evaluates, improves, and deploys that application.

> [!NOTE]
> We are publishing this reference app early so the architecture, code, and demo assets are available as soon as possible. Local validation paths are in place, but some cloud deployment flows are still being exercised and documented.

## The Caldova story

Caldova relies on contract manufacturers to produce medicines, packaging, testing, logistics, and release services. Those suppliers send complex invoices that must be reconciled against contracts, policies, purchase orders, batch records, quality events, capacity approvals, and market context.

Waypoint is Caldova's system of record for that assurance process. It helps teams review supplier invoices, investigate evidence, track findings, manage governed cases, and prepare approved actions. Agents assist with evidence gathering and recommendations, but Waypoint remains the governed boundary for decisions, writes, audit, and approvals.

## What the reference app demonstrates

| Capability | What it shows |
| --- | --- |
| Application | A production-style Waypoint app with API, web UI, auth, telemetry, persistence, and Fabric/OneLake integration. |
| Corpus | A realistic synthetic domain corpus: suppliers, contracts, policies, invoice facts, scenarios, seed data, and generated documents. |
| Agents | A multi-agent invoice assurance workflow with orchestrators, evidence experts, analyst surfaces, and write-boundary agents. |
| Evaluations | Datasets, graders, golden cases, calibration, and eval plans for measuring agent quality. |
| Optimization | Prompt optimization, RFT/RLE planning, cost-quality tradeoffs, promotion metadata, and telemetry backfill workflows. |
| Deployment | Scripts and workflows for standing up the app, corpus, agents, cloud resources, and cross-system wiring. |

## Start here

- `docs/status.md` explains what has been validated and what is still in progress.
- `docs/getting-started.md` contains the current local validation path.
- `docs/deployment.md` explains the repeatable GitHub Actions deployment path.
- `docs/foundry-demo.md` launches the one-click, Foundry-only Pharmashield presenter story.
- `docs/architecture.md` explains the app, corpus, agents, evals, optimization, and deployment layers.
- `docs/data-disclaimer.md` describes the synthetic Caldova data set.
- `docs/compatibility.md` explains why a few package and CLI names still use compatibility names.
- `docs/repository-settings.md` lists recommended public repository settings.
- `SECURITY.md`, `CONTRIBUTING.md`, and `SUPPORT.md` set expectations for public use.

## Repository map

| Path | Caldova responsibility |
| --- | --- |
| `apps/waypoint/` | Waypoint itself: Aspire AppHost, FastAPI API, React web app, infrastructure, tests, and product docs. |
| `modules/corpus/` | The business ground truth for the demo: suppliers, contracts, policies, invoice scenarios, seed generation, document generation, and upload tooling. |
| `modules/agents/` | Caldova's agent fleet: WaypointIQ contracts, prompts, toolboxes, orchestrator, evidence experts, analyst surfaces, eval assets, and agent deployment/publish tooling. |
| `modules/evals/` | Quality gates: datasets, graders, calibration, eval planning, and repeatable checks for agent behavior. |
| `modules/optimization/` | Improvement workflows: optimizer artifacts, RFT/RLE materials, cost-quality demos, and telemetry-backed improvement planning. |
| `tools/deploy/` | Deployment orchestration for the full Caldova Waypoint environment. |
| `.github/extensions/` | Copilot canvas extensions used to inspect, demonstrate, and operate parts of the reference system. |
| `.github/skills/` | Repo-scoped Copilot skills, including the one-step Pharmashield Foundry demo launcher. |

The module names are intentionally simple and public-facing. They describe the role each part plays in Caldova's system rather than exposing the original internal project codenames used during development.
