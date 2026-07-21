# Waypoint hosted agents

This module contains Waypoint's Microsoft Foundry hosted agents, shared
infrastructure, toolboxes, prompts, deployment helpers, and agent-local
evaluation contracts.

## Runtime fleet

The root deployment ships four agents by default:

- `invoice-analyst` - read-only human-facing Q&A and status
- `assurance-orchestrator` - deterministic single-invoice coordinator
- `contract-policy-expert` - read-only FoundryIQ evidence
- `waypoint-recorder` - sole Waypoint writer

The following evidence experts are opt-in:

- `collaboration-evidence-expert` - WorkIQ
- `market-evidence-expert` - WebIQ
- `operations-data-expert` - FabricIQ

FoundryIQ is the only evidence lane enabled by default.

## Structure

```text
modules/agents/
├── agents/          # one hosted-agent source directory per service
├── iqs/             # reusable IQ/toolbox contracts
├── infra/           # shared Foundry, Search, storage, registry, and telemetry IaC
├── scripts/         # discovery, toolbox, deploy, smoke, and publish helpers
├── docs/            # pipeline and operating guides
└── azure.yaml       # hosted service declarations
```

Each agent owns its container entry point, `agent.yaml`, `prompt.md`, dependency
manifest, and tests. `azure.yaml` is the source of truth for deployable hosted
services.

## Local development

```bash
cd modules/agents/agents/assurance-orchestrator
uv sync --frozen
uv run python -m assurance_orchestrator
```

Other agents can be started from their own source directory with the command in
their `agent.yaml` or README.

## Validation

```bash
cd modules/agents
python -m compileall -q agents scripts
python scripts/discover_agents.py
python scripts/prompt_agent_plan.py --check
```

Run agent-local tests from the changed agent directory.

## Deployment

The canonical deployment is the root workflow documented in
[docs/deployment.md](../../docs/deployment.md). It provisions shared Foundry
resources, deploys the selected agent matrix, wires the orchestrator and seller
operation, and runs live acceptance.

`azd provision` and `azd deploy <agent>` remain useful for isolated agent
development, but they are not the canonical full-environment path.

## Governance

- Evidence experts and `invoice-analyst` are read-only.
- `assurance-orchestrator` owns orchestration and lifecycle, not governed
  persistence.
- `waypoint-recorder` is the sole agent writer.
- WorkIQ is user-scoped.
- Missing optional evidence must be reported honestly, never replaced with
  fabricated evidence.

## Quality

Foundry-native evaluation contracts live with agents. Shared datasets, graders,
calibration, and RFT/RLE planning live under `modules/evals`; optimization
artifacts live under `modules/optimization`. P2M is retired.

See [Agent catalog](docs/AGENT_CATALOG.md) and
[Current state](docs/FORGE_CURRENT_STATE.md).
