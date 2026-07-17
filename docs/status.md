# Project status

Waypoint is being prepared as a public reference application for the fictional Caldova company. We are making the repository available as soon as possible so readers can explore the architecture, code, and demo assets while final deployment validation continues.

## Working locally

The consolidated CI workflow now enforces the imported source layout with non-deploy checks:

- Waypoint API tests.
- Waypoint web typecheck and production build.
- Corpus seed generation.
- Agent and Waypoint integration static compile checks.
- Evaluation tooling lint and telemetry backfill planning command.
- Deployment shell-script syntax checks.
- Deployment manifest validation and acceptance-probe unit tests.
- Local Gitleaks scan with no leaks found.
- Clean-copy validation from a fresh copied tree.
- Targeted scans for old org/user references and environment-specific IDs.

## Still in progress

- End-to-end cloud deployment should be treated as advanced and is the next validation milestone.
- A root GitHub Actions deployment path now targets the Waypoint app plus the full hosted agent suite. Assurance Orchestrator deploys with WebIQ and FoundryIQ fan-out enabled by default; WorkIQ and FabricIQ fan-out remain off until their tenant-specific data connections are ready.
- Some package names, CLIs, historical docs, and compatibility paths may still use pre-public internal names.
- The deployment tooling preserves existing behavior first; public naming and resource cleanup will happen after compatibility is proven.
- Agent integrations that require live Microsoft 365, Fabric, Foundry, Azure AI Search, or tenant-specific permissions need environment-specific setup.
- The optimization lane currently includes planning and reference artifacts; live optimization jobs require configured Foundry resources.

## Public caveats

- Caldova is a fictional demo company.
- Suppliers, invoices, contracts, policies, findings, and evidence are synthetic demo data.
- This is a reference application, not a supported Microsoft product.
- Do not use the included demo configuration as production security guidance without review.
