# Assurance Orchestrator integration

This directory retains app-side integration assets for
`assurance-orchestrator`. The canonical hosted agent source and runtime guide
live under
[`modules/agents/agents/assurance-orchestrator`](../../../../../modules/agents/agents/assurance-orchestrator/README.md).

Waypoint invokes the hosted orchestrator from the seller-operated assurance API
for one invoice. The API returns an accepted operation while the hosted run
continues. The orchestrator owns deterministic lifecycle, evidence fan-out, and
synthesis; `waypoint-recorder` remains the sole writer.

The root deployment wires:

- the Waypoint API and scoped reader access
- the `contract-policy-expert` FoundryIQ endpoint by default
- optional WorkIQ, WebIQ, and FabricIQ endpoints when selected
- the `waypoint-recorder` endpoint

Planning documents under `docs/` describe earlier design phases and are retained
for historical context. They are not the current runtime contract.

The current validated seller path is single-invoice. Do not infer a deployed
batch-assurance surface from historical planning assets.
