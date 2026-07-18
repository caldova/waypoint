# Pharmashield Foundry-only demo

This repository includes a committed Copilot skill and canvas for the live
Pharmashield Aster Ridge story without Ollama, a local model, or the Waypoint web
interface.

## Start in one step

Open this repository in GitHub Copilot and say:

> Start the Pharmashield Foundry demo.

The repo skill opens the **Pharmashield · Foundry live demo** canvas. The canvas
uses the current `az login`, discovers the deployed Foundry project, and presents
one primary action: **Run grounded audit**.

No package installation or local service startup is required.

## Prerequisites

- Azure CLI is installed and `az login` is authenticated to the target tenant.
- The root **Deploy Azure** workflow has successfully deployed the default
  FoundryIQ fleet and uploaded `contracts-kb`.
- The signed-in identity can invoke the hosted `contract-policy-expert`.

The canvas does not deploy Azure resources. If these prerequisites are absent,
its readiness panel stays blocked and identifies the missing boundary.

## Live-fidelity contract

The surface follows the canonical Pharmashield Part 2 story:

- the same Aster Ridge invoice carries forward from the local proof of concept;
- the Anatomy panel restores Model + Instructions + Context + Memory and adds the
  fifth production block, Tools;
- Chat asks the same audit question, Trace proves live retrieval, and Connection
  explains the three moves from proof of concept to production; and
- the journey rail hands the story into Waypoint delivery, evaluation,
  optimization, and workforce governance.

The canvas calls the hosted agent directly through the Foundry Responses
endpoint in background mode. It displays the result as grounded only when the
response contains a real `knowledge_base_retrieve` MCP call with a successful,
non-empty tool result. A failed invocation is displayed as ungrounded. The
canvas never substitutes a canned answer or fabricated retrieval trace.

Trace follows the canonical event order: **Calling Foundry IQ**, **Query sent to
the knowledge base**, **knowledge_base_retrieve returned**, then **Citations**.
The returned rate, discount, batch-fee, and packaging clauses are highlighted
only when those words occur in the live tool output.

The included Aster Ridge invoice is a demo fixture retained from the canonical
Pharmashield story. Contract conclusions still come exclusively from the live
FoundryIQ knowledge base.

The hosted `contract-policy-expert` remains a read-only evidence expert. If the
retrieved sources do not prove a purchase-order authorization, the canvas keeps
that question unresolved instead of reproducing the scripted demo's conclusion.

The canvas follows the Copilot app appearance, updates live when the host theme
changes, and uses the operating system appearance only as a fallback. Its light
and dark palettes are complete and independent; it intentionally does not add a
separate theme setting.

## Committed assets

| Path | Purpose |
| --- | --- |
| `.github/skills/pharmashield-foundry-demo/SKILL.md` | Trigger phrases, launch behavior, readiness contract, and presenter talk track. |
| `.github/extensions/pharmashield-foundry-demo/` | Project-scoped canvas, dependency-free Foundry client, renderer, tests, and hero invoice fixture. |
