# Project status

Waypoint is a public reference application for the fictional Caldova company.
All suppliers, invoices, contracts, policies, findings, and evidence are
synthetic demo data.

## Validated paths

- The monorepo's full default Azure deployment completed successfully.
- An unchanged rerun completed successfully while reusing stable resources and
  skipping unchanged hosted-agent versions.
- The default runtime fleet is `invoice-analyst`,
  `assurance-orchestrator`, `contract-policy-expert`, and
  `waypoint-recorder`.
- Only FoundryIQ evidence is enabled by default. WorkIQ, WebIQ, and FabricIQ are
  explicit opt-ins.
- Deployment acceptance selects a live invoice from Waypoint, invokes the hosted
  orchestrator, and verifies a newly finalized, correlated run written through
  `waypoint-recorder`.
- The Waypoint invoice queue exposes single-invoice assurance and a batch
  envelope for up to 25 unique invoices with four concurrent starts.
- Live batch validation proved independent accepted/not-found outcomes, active
  run reuse on an immediate repeat, terminal completion, and correlated traces.
- Local CI covers the Waypoint API and web app, corpus seed generation, agent
  and integration compilation, deployment tooling, acceptance probes, secret
  scanning, and clean-copy validation.

## Quality and optimization

The supported quality path is Foundry-native evaluation and Agent Optimizer
combined with Caliber datasets, deterministic graders, calibration, telemetry
harvesting, and RFT/RLE planning. The retired P2M framework is not part of the
repository.

The authenticated `/quality` page presents this as a five-step controlled loop:
run assurance, inspect traces, measure quality, improve the agent, and release
with approval. The backing workflow is
`.github/workflows/agent-quality-operations.yml`. Historical optimizer and RFT
results remain reference-only and cannot satisfy mutation gates.

## Still in progress

- WorkIQ needs tenant-specific Microsoft 365 access and a known-positive
  evidence case before it should be enabled.
- WebIQ remains optional while its connection and deployment path are completed.
- FabricIQ remains optional until it is backed by a real Fabric Data Agent
  evidence source.
- The agent quality workflow cannot be manually dispatched from this branch
  until its workflow file exists on the default branch.
- Microsoft 365 and Teams publishing remains manual and admin-gated.
- Optimization assets and plans are included, but live jobs require configured
  Foundry resources and reviewed promotion decisions.

## Public caveats

- This is a reference application, not a supported Microsoft product.
- Do not treat the demo configuration as production security guidance without
  an independent review.
