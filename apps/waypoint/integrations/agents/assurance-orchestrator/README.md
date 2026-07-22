# Assurance Orchestrator integration

This directory retains app-side integration assets for
`assurance-orchestrator`. The canonical hosted agent source and runtime guide
live under
[`modules/agents/agents/assurance-orchestrator`](../../../../../modules/agents/agents/assurance-orchestrator/README.md).

Waypoint invokes the hosted orchestrator from the assurance API for one invoice.
The batch endpoint is an orchestration envelope over that same invoice-scoped
operation; it does not change the hosted agent contract. The API returns
accepted operations while hosted runs continue. The orchestrator owns
deterministic lifecycle, evidence fan-out, and synthesis; `waypoint-recorder`
remains the sole writer.

The root deployment wires:

- the Waypoint API and scoped reader access
- the `contract-policy-expert` FoundryIQ endpoint by default
- optional WorkIQ, WebIQ, and FabricIQ endpoints when selected
- the `waypoint-recorder` endpoint

Planning documents under `docs/` describe earlier design phases and are retained
for historical context. They are not the current runtime contract.

The validated app path supports one invoice or a batch of up to 25 unique
invoices. Batch starts are capped at four concurrent invoices, active runs are
reused, and one invoice failure does not roll back another accepted run.
