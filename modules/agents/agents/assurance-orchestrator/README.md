# Assurance Orchestrator

`assurance-orchestrator` coordinates a bounded, single-invoice assurance run.
Its workflow is code-owned: the model does not decide whether to open, finalize,
or hand off the run.

## Responsibilities

1. Normalize the invoice request.
2. Open or reuse the invoice-scoped active Waypoint run.
3. Read the invoice and governed Waypoint context.
4. Run deterministic reconciliation checks.
5. Invoke the enabled evidence experts.
6. Normalize and synthesize an assurance outcome.
7. Hand the final plan to `waypoint-recorder`.
8. Finalize success, timeout, or error.

The orchestrator does not persist governed results directly.
`waypoint-recorder` is the sole agent writer.

## Default evidence

The root deployment enables only FoundryIQ by default:

| Lane | Agent | Default |
| --- | --- | --- |
| FoundryIQ | `contract-policy-expert` | On |
| WorkIQ | `collaboration-evidence-expert` | Off |
| WebIQ | `market-evidence-expert` | Off |
| FabricIQ | `operations-data-expert` | Off |

Optional endpoints are wired only when their lane is selected.

## Runtime budget

Each run executes under `constraints.max_runtime_minutes`, with a default of 30
minutes. Operations can override the default with:

```text
ASSURANCE_ORCHESTRATOR_MAX_RUNTIME_MINUTES=30
```

Keep this below Waypoint's stale-run reaper TTL with enough margin for recorder
finalization.

## Local run

```bash
cd modules/agents/agents/assurance-orchestrator
uv sync --frozen
uv run python -m assurance_orchestrator
```

Configure the Foundry project, model, Waypoint endpoint, and selected expert
endpoints through the agent's environment template. Do not commit local
environment files or credentials.

## Validation

Run the agent-local workflow, harness, evidence-contract, and lifecycle tests
from this directory. Also run module discovery before deployment:

```bash
cd modules/agents
python scripts/discover_agents.py
```

## Deployment

The canonical full deployment is the root
`/.github/workflows/deploy.yml`. Its acceptance job selects one invoice from the
deployed Waypoint work queue, invokes this hosted agent, and verifies that
`waypoint-recorder` produced a newly finalized correlated run.

Batch assurance is not part of the current validated runtime.
