# Pharmashield Foundry-only demo

This repository includes a committed Copilot skill and canvas for the live
Pharmashield Aster Ridge story directly from GitHub Copilot to a hosted
Microsoft Foundry expert, without the Waypoint web interface.

## Start in one step

[![Launch the demo in GitHub Copilot](https://img.shields.io/badge/Launch_in_GitHub_Copilot-57606A?style=for-the-badge)](https://github.com/copilot/app/launch?open=ghapp%3A%2F%2Fsession%2Fnew%3Frepo%3Dcaldova%252Fwaypoint%26mode%3Dinteractive%26prompt%3DStart%2520the%2520Pharmashield%2520Foundry%2520demo.)

The launcher uses GitHub Copilot's hosted deep-link handoff to clone or open
this repository, start an interactive session, and supply the kickoff prompt.
The project-scoped skill and canvas load from the repository automatically; no
separate plugin installation is required.

To launch manually, open this repository in GitHub Copilot and say:

> Start the Pharmashield Foundry demo.

The repo skill opens the **Pharmashield · Foundry live demo** canvas. The canvas
uses the current `az login`, discovers the deployed Foundry project, and presents
one primary action: **Run grounded audit**.

No package installation or local service startup is required.

## Prerequisites

- Azure CLI is installed and `az login` is authenticated to the target tenant.
- The **Deploy contract-agent** workflow has successfully deployed
  `contract-agent` and uploaded `contracts-kb`.
- The signed-in identity can invoke the hosted `contract-agent`.

The canvas does not deploy Azure resources. If these prerequisites are absent,
its readiness panel stays blocked and identifies the missing boundary.

## Live-fidelity contract

The surface presents one Foundry contract-expert story:

- the Aster Ridge invoice is the business context for the live audit;
- the Anatomy panel names the live `gpt-5.5` deployment and shows Model +
  Instructions + Context + Memory + Tools;
- Chat asks the audit question, Trace proves live retrieval, and Connection
  explains how the explicit model, approved knowledge, and instructions form the
  expert; and
- the journey rail hands the story into Waypoint delivery, evaluation,
  optimization, and workforce governance.

The model shown in the canvas comes from the selected hosted agent's live
deployment metadata, with the repository's `gpt-5.5` deployment default used
only when that metadata is unavailable. Keeping the model explicit is
intentional: different agents can use different models for their jobs.

The canvas calls the hosted agent directly through the Foundry Responses
endpoint in background mode. It displays the result as grounded only when the
response contains a real `knowledge_base_retrieve` MCP call with a successful,
non-empty tool result. A failed invocation is displayed as ungrounded. The
canvas never substitutes a canned answer or fabricated retrieval trace.

The Chat result leads with a seller-readable **Foundry audit at a glance**:
live-grounded contract exceptions, deterministic invoice arithmetic, and two
priority findings. The rate finding explicitly reconciles the invoice's listed
unit rate with its effective line rate before calculating the contract-priced
amount and potential recovery. Confidence and verified source references remain visible;
the complete evidence set and unresolved questions are available through
progressive disclosure.

Trace follows the canonical event order: **Calling Foundry IQ**, **Query sent to
the knowledge base**, **knowledge_base_retrieve returned**, **Grounded findings**,
then **Citations**. Overview and Trace reference counts share the same trust
boundary: only references in a successful retrieval result qualify. The returned
rate, discount, batch-fee, and packaging clauses are highlighted only when those
words occur in the live tool output.

The included Aster Ridge invoice is the demo's business artifact. Contract
conclusions still come exclusively from the live FoundryIQ knowledge base.

The hosted `contract-agent` remains a read-only evidence expert on this surface.
If the
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
