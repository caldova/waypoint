# Architecture

Waypoint is a monorepo reference application for Caldova's synthetic contract
manufacturing invoice-assurance scenario.

## Repository layers

| Layer | Path | Responsibility |
| --- | --- | --- |
| Application | `apps/waypoint/` | Governed API, web UI, PostgreSQL, auth, telemetry, assurance operations, and audit. |
| Corpus | `modules/corpus/` | Synthetic suppliers, contracts, policies, invoices, scenarios, seed generation, and upload tooling. |
| Agents | `modules/agents/` | Hosted agents, prompts, toolboxes, orchestration, and the recorder write boundary. |
| Evaluations | `modules/evals/` | Caliber datasets, graders, calibration, and repeatable quality gates. |
| Optimization | `modules/optimization/` | Foundry Agent Optimizer, RFT/RLE planning, cost-quality views, and promotion metadata. |
| Deployment | `tools/deploy/` | OIDC, Key Vault, MSAL, manifests, probes, and lower-level deployment helpers. |

The root `/.github/workflows/deploy.yml` composes all layers into one Azure
environment.

## Default assurance flow

```mermaid
flowchart LR
    Corpus[Synthetic corpus] --> App[Waypoint<br/>system of record]
    Corpus --> KB[contracts-kb]
    Reviewer[Reviewer<br/>one or many invoices] --> App
    Analyst[invoice-analyst<br/>read-only] --> App
    App --> Orchestrator[assurance-orchestrator]
    Orchestrator --> Expert[contract-policy-expert<br/>FoundryIQ]
    KB --> Expert
    Expert --> Orchestrator
    Orchestrator --> Recorder[waypoint-recorder<br/>sole writer]
    Recorder --> App
    Orchestrator --> Quality[Run → inspect → measure<br/>improve → approve release]
```

The one-click launch architecture has one evidence plane: FoundryIQ through
`contract-policy-expert` and `contracts-kb`. WorkIQ, WebIQ, FabricIQ, and
Fabric/OneLake source modules remain available for future development, but the
launch workflow does not deploy or wire them.

## Governance invariants

1. Waypoint is the system of record.
2. Evidence experts and `invoice-analyst` are read-only.
3. `assurance-orchestrator` owns deterministic lifecycle and synthesis.
4. `waypoint-recorder` is the only agent that writes governed results.
5. Runs are invoice-scoped, bounded, correlated, and terminally finalized.
6. Missing evidence must be reported as unavailable rather than fabricated.
7. Secrets live outside source control.

## Deployment and quality

The launch deployment includes the app, corpus, Foundry resources, the four
launch agents, seed import, assurance wiring, and live acceptance.

Agent quality follows Foundry-native evaluation and Agent Optimizer plus Caliber
datasets, deterministic graders, calibration, telemetry harvesting, and RFT/RLE
planning. The retired P2M framework is not part of the architecture.

Deployment acceptance intentionally proves one invoice per invocation. The
application also provides a batch envelope over the same invoice-scoped
lifecycle: up to 25 unique invoices, four concurrent starts, active-run reuse,
ordered results, and independent failures.

Agent quality operations are intentionally separate from the application write
path. The authenticated `/quality` page explains a five-step loop — run,
inspect, measure, improve, and release with approval — and links to
`.github/workflows/agent-quality-operations.yml`. GitHub Actions owns
credentials, evidence artifacts, and protected approvals; the browser does not
execute cloud operations.
