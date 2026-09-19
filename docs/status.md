# Project status

Waypoint is a public reference application for the fictional Caldova company.
All suppliers, invoices, contracts, policies, findings, and evidence are
synthetic demo data.

## Current shape

- The agent portfolio is now three thin [castia](https://github.com/sethjuarez/castia)
  apps:
  - `contract-expert`: prompt-grounded keynote/video demo with invoice,
    contract, and policy context in the baseline prompt.
  - `contract-policy-expert`: FoundryIQ-only Teams/Q&A agent for grounded
    contract and policy answers.
  - `contract-agent`: full multi-IQ workhorse for assurance runs, status,
    orchestration, and governed writeback.
- The workhorse's evidence and status tools are read-only; a single governed
  writer is the only path that persists results into Waypoint.
- FoundryIQ (`contracts-kb`) is the wired evidence plane, verified live end to
  end through the aggregating Foundry toolbox (`contract-toolbox`). WorkIQ,
  WebIQ, and FabricIQ attach to `contract-agent` as additional toolbox lanes.
- The `caldova-agents` Foundry project is live in `rg-caldova-agents`.
  Hosted agents run on `gpt-6-astra`; the Search-backed `contracts-kb` answer
  synthesis remains on `gpt-5.5` because Azure AI Search rejected
  `gpt-6-astra` as an unsupported knowledge-base model on 2026-09-18.
- The Waypoint invoice queue exposes single-invoice assurance and a batch
  envelope for up to 25 unique invoices with four concurrent starts.
- Local CI covers the Waypoint API and web app, corpus seed generation, the
  agent compile checks, and deployment tooling.

## Quality and optimization

Quality and optimization run through `castia eval` and `castia optimize`.
`contract-policy-expert` is the cleanest first target for FoundryIQ-only
grounded answer quality; `contract-agent` keeps the workflow/writeback eval
surface. Both are backed by Caliber datasets, deterministic graders, calibration
in `modules/evals`, and the Agent Optimizer / RFT assets in
`modules/optimization`. The intended model ladder is `gpt-6-astra` as the
teacher/live baseline, then RFT down to a lower-cost MAI candidate once Foundry
confirms which MAI model supports the RFT workflow; `MAI-Thinking-1` is visible
in the `westus` model catalog, while explicit `*-finetune` quota currently
appears for `mai-code-1.1-flash`.

## Recently completed (v2 line)

- Collapsed the retired multi-agent fleet into a Castia-based agent portfolio:
  prompt-grounded `contract-expert`, FoundryIQ-only `contract-policy-expert`,
  and full multi-IQ `contract-agent`.
- Stood up the FoundryIQ evidence plane (embedding model, storage, knowledge
  source, `contracts-kb` knowledge base, KB MCP connection) and the single
  aggregating `contract-toolbox` — all tracked in
  [`caldova-agents-buildout.md`](caldova-agents-buildout.md).
- Deployed all three hosted agents to `caldova-agents`:
  `contract-expert:4`, `contract-policy-expert:4`, and `contract-agent:3`.
- Proved `contracts-kb` retrieval live: a direct Search retrieve call returns a
  grounded rejected-batch billing answer quoting the Aster Ridge SOW + Quality
  Release & Billability Policy.
- Granted each agent instance managed identity `Foundry User` at project scope
  so the Responses model service can enumerate + call the toolbox.

## Still in progress

- Wiring `contract-agent` **Waypoint API** tools end to end (`WAYPOINT_API_BASE_URL`)
  so tool-driven assurance runs write back against a live Waypoint API — the
  toolbox/KB retrieval half is done and verified.
- Rebuilding agent deploy-pipeline test coverage: the fleet-era
  `test_agent_model_configuration.py` was removed with the retired pipeline, so
  the lean Castia deploy path is currently under-tested.
- Region availability remains a deployment consideration: Azure AI Search,
  Foundry, and both model deployments must be healthy and co-located.
- Automating the manual `caldova-agents` buildout ledger steps remains future
  work: Search knowledge-source/base creation, remote-tool connection, toolbox
  publish, and agent instance RBAC are proven manually but not yet scripted.
- Calibrated decision confidence remains future work that requires a reviewed
  calibration artifact.
- Microsoft 365 and Teams publishing remains manual and admin-gated.

## Public caveats

- This is a reference application, not a supported Microsoft product.
- Do not treat the demo configuration as production security guidance without
  an independent review.
