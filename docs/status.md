# Project status

Waypoint is a public reference application for the fictional Caldova company.
All suppliers, invoices, contracts, policies, findings, and evidence are
synthetic demo data.

## Current shape

- Invoice assurance runs on a single [castia](https://github.com/sethjuarez/castia)-based
  `contract-agent`, deployed to the **caldova** Foundry project in **West US**.
  It serves the responses, activity, and invocations protocols from one entry
  point.
- The agent's evidence and status tools are read-only; a single governed writer
  is the only path that persists results into Waypoint.
- FoundryIQ (`contracts-kb`) is the wired evidence plane, verified live end to
  end: the hosted agent reaches it through a single aggregating Foundry toolbox
  (`contract-toolbox`) and returns grounded, cited answers. WorkIQ, WebIQ,
  FabricIQ, and Fabric/OneLake source modules remain in the repository for
  future development — each joins by attaching a connection and republishing the
  toolbox, with no agent redeploy.
- The Waypoint invoice queue exposes single-invoice assurance and a batch
  envelope for up to 25 unique invoices with four concurrent starts.
- Local CI covers the Waypoint API and web app, corpus seed generation, the
  single-agent compile check, and deployment tooling.

## Quality and optimization

Quality and optimization run through `castia eval` and `castia optimize` against
`contract-agent`, backed by Caliber datasets, deterministic graders, and
calibration in `modules/evals`, and the Agent Optimizer / RFT assets in
`modules/optimization`.

## Recently completed (v2 line)

- Collapsed the retired multi-agent fleet into a single castia `contract-agent`
  serving all three protocols; deleted the fleet scaffolding, its infra, and the
  old fleet deploy pipeline + quality workflows.
- Stood up the FoundryIQ evidence plane (embedding model, storage, knowledge
  source, `contracts-kb` knowledge base, KB MCP connection) and the single
  aggregating `contract-toolbox` — all tracked in
  [`foundryiq-provisioning.md`](foundryiq-provisioning.md).
- Deployed the hosted `contract-agent` and proved retrieval live: a `responses`
  invoke returns a grounded rejected-batch billing answer quoting the Aster
  Ridge SOW + Quality Release & Billability Policy.
- Granted the agent instance managed identity `Foundry User` at project scope so
  the Responses model service can enumerate + call the toolbox (fixed the 403 on
  tool enumeration); captured for infra automation in the ledger.

## Still in progress

- Wiring the agent's **Waypoint API** tools end to end (`WAYPOINT_API_BASE_URL`)
  so tool-driven assurance runs write back against a live Waypoint API — the
  toolbox/KB retrieval half is done and verified.
- Rebuilding single-agent deploy-pipeline test coverage: the fleet-era
  `test_agent_model_configuration.py` was removed with the retired pipeline, so
  the lean single-agent deploy path is currently under-tested.
- Region availability remains a deployment consideration: Azure AI Search,
  Foundry, and both model deployments must be healthy and co-located.
- Calibrated decision confidence remains future work that requires a reviewed
  calibration artifact.
- Microsoft 365 and Teams publishing remains manual and admin-gated.

## Public caveats

- This is a reference application, not a supported Microsoft product.
- Do not treat the demo configuration as production security guidance without
  an independent review.
