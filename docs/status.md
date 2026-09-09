# Project status

Waypoint is a public reference application for the fictional Caldova company.
All suppliers, invoices, contracts, policies, findings, and evidence are
synthetic demo data.

## Current shape

- Invoice assurance runs on a single [castia](https://github.com/sethjuarez/castia)-based
  `waypoint-agent`, deployed to the **caldova** Foundry project in **West US**.
  It serves the responses, activity, and invocations protocols from one entry
  point.
- The agent's evidence and status tools are read-only; a single governed writer
  is the only path that persists results into Waypoint.
- FoundryIQ (`contracts-kb`) is the wired evidence plane. WorkIQ, WebIQ,
  FabricIQ, and Fabric/OneLake source modules remain in the repository for
  future development.
- The Waypoint invoice queue exposes single-invoice assurance and a batch
  envelope for up to 25 unique invoices with four concurrent starts.
- Local CI covers the Waypoint API and web app, corpus seed generation, the
  single-agent compile check, and deployment tooling.

## Quality and optimization

Quality and optimization run through `castia eval` and `castia optimize` against
`waypoint-agent`, backed by Caliber datasets, deterministic graders, and
calibration in `modules/evals`, and the Agent Optimizer / RFT assets in
`modules/optimization`.

## Still in progress

- Wiring the agent's tools end to end (`WAYPOINT_API_BASE_URL` + toolbox) so
  tool-driven assurance runs complete against a live Waypoint API.
- Region availability remains a deployment consideration: Azure AI Search,
  Foundry, and both model deployments must be healthy and co-located.
- Calibrated decision confidence remains future work that requires a reviewed
  calibration artifact.
- Microsoft 365 and Teams publishing remains manual and admin-gated.

## Public caveats

- This is a reference application, not a supported Microsoft product.
- Do not treat the demo configuration as production security guidance without
  an independent review.
