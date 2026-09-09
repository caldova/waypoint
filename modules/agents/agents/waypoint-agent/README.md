# waypoint-agent

The single Waypoint invoice-assurance hosted agent, built on
[`castia`](https://github.com/sethjuarez/castia). It replaces the previous
multi-agent fleet (`invoice-analyst`, `assurance-orchestrator`,
`contract-policy-expert`, `waypoint-recorder`) with one agent.

## Protocols

One handler set in `main.py` serves all three Foundry wire protocols:

| Protocol | Handler | Surface |
| --- | --- | --- |
| `responses` | `assurance` | App-triggered invoice-assurance runs (critical path). |
| `activity` | `ask` | Teams / AI Teammate Q&A and status (Adaptive Cards later). |
| `invocations` | `invoked` | Callable as a Foundry tool / agent-to-agent. |

## Responsibilities

Evidence gathering, analyst Q&A / status, the assurance run, and the governed
write — all in one process. Everything is read-only except a **single
centralized write tool** (added in a later step), which is the only thing
allowed to mutate Waypoint.

## Local development

```bash
cd modules/agents/agents/waypoint-agent
cp .env.example .env      # set FOUNDRY_PROJECT_ENDPOINT + AZURE_AI_MODEL_DEPLOYMENT_NAME
uv sync
uv run python main.py     # serves 0.0.0.0:8088
```

Model and instructions resolve from `.agent_configs/baseline/` via castia's
`configured_model()`, so the Foundry Agent Optimizer can tune the prompt with no
code change. Without that config it degrades to environment defaults.

## Lifecycle (castia)

```bash
python -m castia eval check     # offline eval-suite gate
python -m castia optimize --check   # tool baseline drift gate
python -m castia deploy         # reconcile azure.yaml protocols from decorators
```
