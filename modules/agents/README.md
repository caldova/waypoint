# Waypoint hosted agents

This module contains Caldova's Microsoft Foundry hosted-agent portfolio. The
agents are intentionally thin Castia apps; shared lifecycle and hosting behavior
lives in the `castia` package instead of bespoke repo code.

## Agents

| Agent | Boundary | Protocols |
| --- | --- | --- |
| `contract-expert` | Prompt-grounded keynote/video demo. Contract, policy, and invoice context lives in the baseline prompt. No IQ tools or writeback. | responses |
| `contract-policy-expert` | FoundryIQ-only Teams/Q&A expert. Read-only `knowledge_base_retrieve` grounding for contracts and policies. | responses, activity |
| `contract-agent` | Full multi-IQ workhorse for invoice assurance. Uses FoundryIQ, WorkIQ, WebIQ, FabricIQ, Waypoint API tools, and the single governed write path. | responses, activity, invocations |
| `contracts` | Teams-first contract intake autopilot stub. Establishes the future inbox, artifact, extraction, evidence, and report workflow while the Waypoint Contracts API is built. | responses, activity, invocations |

The first two agents keep the keynote story and the FoundryIQ optimization path
small. The workhorse owns operational composition and persistence.

Model strategy: `gpt-6-astra` is the live hosted-agent and teacher baseline.
The RFT lane should distill/optimize down to a lower-cost MAI candidate when the
Foundry fine-tuning workflow confirms the supported target. `contracts-kb`
answer synthesis is separate and currently stays on `gpt-5.5` because Azure AI
Search does not yet allow `gpt-6-astra` for knowledge bases.

## Structure

```text
modules/agents/
├── contract-expert/          # prompt-grounded demo expert
├── contract-policy-expert/   # FoundryIQ-only contract/policy Q&A
├── contract-agent/           # full multi-IQ assurance workhorse
├── contracts/                # contract inbox/autopilot stub
└── waypoint-iq/              # reusable IQ/toolbox + OpenAPI contract
```

The deployable services are declared in the repo-root `azure.yaml`.

`pyproject.toml` is the source of truth for Python dependencies. The two hosted
code-deploy agents (`contract-expert` and `contract-policy-expert`) also keep a
minimal `requirements.txt` for Foundry remote build, but it only contains
`-e .`, so pip installs the local project and reads the real dependency list from
that agent's `pyproject.toml`.

## Local development

```bash
cd modules/agents
uv sync
uv run castia --help
```

The shared `modules/agents/.venv` installs the common Castia runtime once for
all three agents. `pyrightconfig.json` points VS Code/Pylance at that
environment and treats each agent folder as its own execution root, so local
imports like `contract-agent/tools.py` resolve while browsing the whole
portfolio.

## Deployment

Deploy from the repo root:

```bash
azd provision
azd deploy contract-expert
azd deploy contract-policy-expert
azd deploy contract-agent
azd deploy contracts
```

## Quality

Shared datasets, graders, calibration, and RFT/RLE planning live under
`modules/evals`; Agent Optimizer and RFT artifacts live under
`modules/optimization`. Optimize `contract-policy-expert` first when the target
is grounded contract/policy answer quality; use `contract-agent` evals for
workflow and governed-write correctness.
