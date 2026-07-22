# Deployment tooling

This directory contains the lower-level scripts, manifest, tests, and historical
workflow assets used by Waypoint's monorepo deployment.

> [!IMPORTANT]
> The canonical entry point is the root
> [Deploy Azure workflow](../../.github/workflows/deploy.yml), and the canonical
> operator guide is [docs/deployment.md](../../docs/deployment.md). Do not run
> the workflow under `tools/deploy/.github/` as the current deployment path.

## Current deployment shape

The validated default deployment provisions the Waypoint app, corpus seed,
Fabric/OneLake storage, Foundry project and knowledge base, and four hosted
agents:

- `invoice-analyst`
- `assurance-orchestrator`
- `contract-policy-expert`
- `waypoint-recorder`

FoundryIQ is the only evidence lane enabled by default. WorkIQ, WebIQ, and
FabricIQ are optional and add their expert only when selected.

`waypoint-recorder` is the sole agent writer. The app's assurance operation and
deployment acceptance both run one invoice through `assurance-orchestrator`,
then verify that the recorder finalized the governed Waypoint run.

## Directory map

| Path | Purpose |
| --- | --- |
| `deployment.manifest.json` | Canonical source roots, default lanes, expected components, and HTTP probes. |
| `scripts/oidc.sh` | One-time GitHub-to-Azure OIDC bootstrap. |
| `scripts/keyvault.sh` | Idempotent Key Vault and generated-secret helpers. |
| `scripts/msal.sh` | Waypoint Entra application reconciliation. |
| `scripts/verify_deployment.py` | Versioned HTTP acceptance probes. |
| `scripts/verify_terminal_run.py` | Verifies a newly finalized assurance run. |
| `tests/` | Deployment contract and probe tests. |
| `.github/workflows/deploy.yml` | Historical pre-consolidation workflow retained for reference. |

Some scripts preserve compatibility names internally. The root workflow supplies
the monorepo paths and current resource values; public guidance should use
Waypoint terminology and the root workflow.

## Local checks

From the repository root:

```bash
bash -n tools/deploy/scripts/*.sh
python -m unittest discover -s tools/deploy/tests -p "test_*.py"
```

These checks do not prove cloud deployment.

## Recovery and drift evidence

`scripts/verify_recovery_drift.py` compares sanitized baseline, interrupted,
and rerun inventory snapshots without contacting Azure. It verifies recovered
stages, managed-state convergence, duplicate-free resource inventories, and
the bounded drift scenarios used by the hermetic recovery harness.

See [Recovery and drift verification](docs/RECOVERY_DRIFT.md) for the snapshot
contract, safety boundaries, and parity-environment commands.

Deployment confidence comes from the root workflow's acceptance job and uploaded
evidence artifact.

## Rerun behavior

The full default deployment and an unchanged rerun have been validated. Stable
secrets and resource identities are reused, and hosted-agent versions are
skipped when their source, configuration, and relevant infrastructure inputs
match the active version.

This agent-level skip is the current selective deployment behavior. Batch
assurance and separate quality-operation triggers are not implemented by these
tools.
