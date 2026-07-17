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
packages, start Aspire, or open the Waypoint web app. After opening, report the
readiness state in one sentence and stop. The presenter starts the live agent
from the canvas with **Start live Foundry audit**.

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

1. **Frame:** "We are skipping the fragile laptop setup and starting at the
   production destination: Microsoft Foundry."
2. **Inspect:** "The job is still invoice assurance. The production model and
   instructions are hosted; Foundry IQ adds our approved contract knowledge."
3. **Run:** Click **Start live Foundry audit**. "This is the real hosted Contract
   Policy Expert, using my tenant identity—not a local simulation."
4. **Prove:** Open **Live trace** after completion. "The tool call, query, returned
   clause text, and source references are the proof that this is grounded."
5. **Land:** "The invoice can expose its own line-math inconsistency. Foundry
   resolves what requires enterprise context: contracted rates and packaging
   authorization."

## Readiness contract

The canvas needs:

1. Azure CLI installed.
2. `az login` authenticated to the tenant containing the deployment.
3. A deployed Foundry project with `contract-policy-expert`.
4. The FoundryIQ `contracts-kb` connection and uploaded Aster Ridge contract.

Use the root **Deploy Azure** workflow with the default FoundryIQ lane to create
items 3–4. Do not bypass a failed readiness check with a scripted response.
