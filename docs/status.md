# Project status

Waypoint is a public reference application for the fictional Caldova company.
All suppliers, invoices, contracts, policies, findings, and evidence are
synthetic demo data.

## Validated paths

- A full deployment completed successfully end to end in **UK South** with four
  active hosted agents, one analyst Bot Service, a populated contracts KB, and a
  terminal correlated assurance run. Run `30034540034` at commit `f9fc7bb` also
  proved the KB model split and grounded runtime evidence gate; an earlier
  unchanged rerun preserved stable resources and skipped unchanged agent
  versions. See the
  [end-to-end readiness assessment](e2e-readiness-assessment.md).
- An unchanged rerun completed successfully while reusing stable resources and
  skipping unchanged hosted-agent versions.
- The default runtime fleet is `invoice-analyst`,
  `assurance-orchestrator`, `contract-policy-expert`, and
  `waypoint-recorder`.
- The one-click launch package deploys only FoundryIQ evidence. WorkIQ, WebIQ,
  FabricIQ, and Fabric/OneLake are excluded from its inputs, stages, and
  resources.
- Deployment acceptance selects a live invoice from Waypoint, invokes the hosted
  orchestrator, and verifies a newly finalized, correlated run written through
  `waypoint-recorder`. It now also fails closed when trace telemetry or recorded
  runtime evidence lacks KB retrieval citations, or when the run shows FoundryIQ
  fallback.
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

- **Regional availability remains the main deployment risk.** UK South now has a
  one-click proof with grounded KB runtime evidence at commit `f9fc7bb`. Sweden
  Central still cannot provision hosted agents on newly-created Foundry accounts, so
  region choice remains subject to Azure platform health. See
  [platform and environmental blockers](deployment-troubleshooting.md#platform-and-environmental-blockers-encountered)
  and the [end-to-end readiness assessment](e2e-readiness-assessment.md).
- Runtime confidence scores are visible again as uncalibrated evidence scores;
  calibrated decision confidence remains future work that requires a reviewed
  calibration artifact.
- WorkIQ, WebIQ, FabricIQ, and Fabric/OneLake source modules remain in the
  repository for future development, outside the initial launch package.
- The agent quality workflow cannot be manually dispatched from this branch
  until its workflow file exists on the default branch.
- Microsoft 365 and Teams publishing remains manual and admin-gated.
- Optimization assets and plans are included, but live jobs require configured
  Foundry resources and reviewed promotion decisions.

## Public caveats

- This is a reference application, not a supported Microsoft product.
- Do not treat the demo configuration as production security guidance without
  an independent review.
