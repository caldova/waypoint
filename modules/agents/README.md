# Waypoint hosted agent

This module contains Waypoint's single Microsoft Foundry hosted agent and the
reusable IQ/toolbox contract it depends on.

## The agent

`waypoint-agent` is one [castia](https://github.com/sethjuarez/castia)-based
agent that serves every surface. It speaks three protocols from a single
`main:app` entry point:

- **responses** — read-only human-facing Q&A and assurance
- **activity** — Teams / AI Teammate cards
- **invocations** — programmatic single-invoice runs

Evidence and status tools are read-only; a single governed writer
(`record_assurance`) is the sole path that mutates Waypoint. Missing evidence is
reported honestly, never fabricated.

## Structure

```text
modules/agents/
├── agents/waypoint-agent/   # the hosted-agent source (main:app, agent.yaml, tools)
└── iqs/waypoint-iq/         # reusable IQ/toolbox + OpenAPI contract
```

The deployable service is declared in the repo-root `azure.yaml`.

## Local development

```bash
cd modules/agents/agents/waypoint-agent
uv sync --frozen
uv run castia --help
```

## Deployment

Deployed to the `caldova` Foundry project from the repo root:

```bash
azd provision            # shared Foundry resources + gpt-5.5
castia deploy            # reconcile azure.yaml protocols from decorators
azd deploy waypoint-agent
```

## Quality

Shared datasets, graders, calibration, and RFT/RLE planning live under
`modules/evals`; Agent Optimizer and RFT artifacts live under
`modules/optimization`.
