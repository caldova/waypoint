# contract-agent

The full Caldova invoice-assurance workhorse, built on
[`castia`](https://github.com/sethjuarez/castia). It owns multi-IQ evidence
gathering, workflow orchestration, and the sole governed write path into
Waypoint.

## Protocols

One handler set in `main.py` serves all three Foundry wire protocols:

| Protocol | Handler | Surface |
| --- | --- | --- |
| `responses` | `assurance` | App-triggered invoice-assurance runs (critical path). |
| `activity` | `ask` | Teams / AI Teammate Q&A and status (Adaptive Cards later). |
| `invocations` | `invoked` | Callable as a Foundry tool / agent-to-agent. |

## Responsibilities

Evidence gathering, analyst Q&A/status, assurance runs, and governed writeback
all happen in one Castia app. The live FoundryIQ lane attaches through Castia's
server-side toolbox MCP spec; Waypoint API tools provide structured
status/evidence and the centralized `record_assurance` writer is the only
mutating capability.

Use the smaller sibling agents for narrower story/eval targets:

- `contract-expert` — prompt-grounded demo expert with no IQ tools.
- `contract-policy-expert` — FoundryIQ-only Teams/Q&A expert.

## Local development

```bash
cd modules/agents
uv sync
cd contract-agent
..\.venv\Scripts\python.exe main.py
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
