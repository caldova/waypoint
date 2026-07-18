---
name: pharmashield-foundry-demo
description: "Open and guide the one-click, Foundry-only Pharmashield invoice-assurance demo. Use when the user says 'start the Pharmashield demo', 'run the Foundry invoice demo', 'show the Aster Ridge story', 'open the Foundry demo runbook', or asks for the live contract-grounded Chapter 2 Build story without Ollama or the Waypoint web app."
license: MIT
metadata:
  author: Caldova
  version: "1.0.0"
---

# Pharmashield Foundry demo

Open the committed presenter canvas immediately:

- `canvasId`: `pharmashield-foundry-demo`
- `instanceId`: `pharmashield-foundry-demo`
- `input`: `{}`

The canvas performs its own preflight. Do not run Ollama, install npm/Python
packages, start Aspire, or open the Waypoint web app. After opening, report the readiness state in one sentence and stop. The presenter
starts the live agent from the canvas with **Run grounded audit**.

If the canvas is not registered, call `extensions_reload`, confirm
`project:pharmashield-foundry-demo` is ready, and open it again.

## What makes this live

- Azure authentication comes from the presenter's existing `az login`.
- The canvas discovers accessible `Microsoft.CognitiveServices/accounts/projects`
  resources and prefers the current Waypoint/Forge project.
- The primary button calls the hosted `contract-policy-expert` Responses endpoint
  in background mode and polls the real response.
- The answer is labeled grounded only when the hosted response contains an actual
  `knowledge_base_retrieve` MCP tool call.
- There is no canned answer or synthetic trace. A missing agent, knowledge-base
  connection, permission, or model deployment is a visible blocking error.

## Presenter talk track

1. **Promote:** "We proved the workflow locally. This is the same job, the same
   instructions, and the same Aster Ridge invoice—promoted into Foundry."
2. **Anatomy:** Point to Model + Instructions + Context + Memory, then Tools.
   "Foundry adds the fifth part: approved contract knowledge through Foundry IQ."
3. **Connect:** Open **Connection**. "Three moves: use the hosted model, connect
   contract knowledge, and assemble the read-only evidence expert."
4. **Run:** Return to **Chat** and click **Run grounded audit**. "This asks the same
   question as Part 1, now with access to what we actually signed."
5. **Prove:** Open **Trace** after completion. Follow the chronological sequence:
   "Foundry IQ was called, this exact query was sent, this contract text came
   back, and these citations identify the sources." Highlighting appears only
   where those clauses occur in the live retrieval result.
6. **Hand off:** Point to the journey rail. "Waypoint governs the workflow; then
   delivery, evaluation, optimization, and workforce governance compound the
   value."

Do not claim that packaging is unauthorized unless the live retrieved evidence
proves it. The deployed expert is evidence-only; unresolved authorization is the
handoff to the governed Waypoint workflow, not a demo failure.

## Readiness contract

The canvas needs:

1. Azure CLI installed.
2. `az login` authenticated to the tenant containing the deployment.
3. A deployed Foundry project with `contract-policy-expert`.
4. The FoundryIQ `contracts-kb` connection and uploaded Aster Ridge contract.

Use the root **Deploy Azure** workflow with the default FoundryIQ lane to create
items 3–4. Do not bypass a failed readiness check with a scripted response.
