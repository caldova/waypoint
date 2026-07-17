# Pharmashield Foundry-only demo

This repository includes a committed Copilot skill and canvas for the live
Pharmashield Aster Ridge story without Ollama, a local model, or the Waypoint web
interface.

## Start in one step

Open this repository in GitHub Copilot and say:

> Start the Pharmashield Foundry demo.

The repo skill opens the **Pharmashield · Foundry live demo** canvas. The canvas
uses the current `az login`, discovers the deployed Foundry project, and presents
one primary action: **Start live Foundry audit**.

No package installation or local service startup is required.

## Prerequisites

- Azure CLI is installed and `az login` is authenticated to the target tenant.
- The root **Deploy Azure** workflow has successfully deployed the default
  FoundryIQ fleet and uploaded `contracts-kb`.
- The signed-in identity can invoke the hosted `contract-policy-expert`.

The canvas does not deploy Azure resources. If these prerequisites are absent,
its readiness panel stays blocked and identifies the missing boundary.

## Live-fidelity contract

The canvas calls the hosted agent directly through the Foundry Responses
endpoint in background mode. It displays the result as grounded only when the
response contains a real `knowledge_base_retrieve` MCP call. It never substitutes
a canned answer or fabricated retrieval trace.

The included Aster Ridge invoice is a demo fixture retained from the canonical
Pharmashield story. Contract conclusions still come exclusively from the live
FoundryIQ knowledge base.

## Committed assets

| Path | Purpose |
| --- | --- |
| `.github/skills/pharmashield-foundry-demo/SKILL.md` | Trigger phrases, launch behavior, readiness contract, and presenter talk track. |
| `.github/extensions/pharmashield-foundry-demo/` | Project-scoped canvas, dependency-free Foundry client, renderer, tests, and hero invoice fixture. |
