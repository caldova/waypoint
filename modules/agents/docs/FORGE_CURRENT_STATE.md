# Hosted agent current state

The agent source lives under `modules/agents` and deploys with the rest of the
Waypoint monorepo through `/.github/workflows/deploy.yml`.

The full default deployment and an unchanged rerun have been validated. The
acceptance gate inventories the selected hosted agents, invokes
`assurance-orchestrator` for one live Waypoint invoice, and verifies that
`waypoint-recorder` finalized a new correlated run.

## Default fleet

| Agent | Responsibility | Authority | Validated deployment role |
| --- | --- | --- | --- |
| `invoice-analyst` | Human-facing invoice Q&A and status. | Read-only | Deployed by default. |
| `assurance-orchestrator` | Code-owned, bounded invoice-assurance coordination and run lifecycle. | Reads Waypoint and invokes experts/recorder; does not persist governed results directly. | Deployed and driven by acceptance. |
| `contract-policy-expert` | FoundryIQ retrieval over `contracts-kb`. | Read-only evidence | Deployed and enabled by default. |
| `waypoint-recorder` | Validates and persists the final governed result. | Sole Waypoint agent writer | Deployed and verified by acceptance. |

## Optional evidence experts

| Agent | Lane | Current posture |
| --- | --- | --- |
| `collaboration-evidence-expert` | WorkIQ | Opt-in; requires tenant-specific Microsoft 365 access and a known-positive case. |
| `market-evidence-expert` | WebIQ | Opt-in while its connection and deployment path are completed. |
| `operations-data-expert` | FabricIQ | Opt-in only after a real Fabric Data Agent evidence source is configured. |

The root workflow builds the hosted-agent matrix from the lane inputs. It wires
only selected expert endpoints into the orchestrator.

## Run lifecycle

`assurance-orchestrator` owns the deterministic run harness:

1. Open or reuse the active invoice-scoped Waypoint run.
2. Gather deterministic and enabled expert evidence.
3. Normalize and synthesize the assurance decision.
4. Hand the final plan to `waypoint-recorder`.
5. Finalize success, timeout, or failure so the run does not remain orphaned.

Waypoint's stale-run reaper remains a process-death backstop. Its TTL must stay
above the orchestrator runtime limit plus safety margin.

## Deployment behavior

- The default matrix contains exactly four agents.
- FoundryIQ is on by default; WorkIQ, WebIQ, and FabricIQ are off.
- Shared Foundry infrastructure is reconciled before agent deploy.
- Each selected agent's source, runtime configuration, and relevant
  infrastructure values are fingerprinted.
- A matching active hosted-agent version is reused instead of redeployed.
- `waypoint-recorder` receives writer authority; readers and evidence experts do
  not.

The skip-on-unchanged behavior is the current selective deployment capability.
It does not imply batch assurance or a separate quality-operation runtime.

## Quality path

Agent quality work uses Foundry-native evaluation contracts and Agent Optimizer
with Caliber datasets, deterministic graders, calibration, telemetry harvesting,
and RFT/RLE planning. P2M is retired.

## Remaining external dependencies

- WorkIQ evidence requires tenant and user access.
- WebIQ remains optional until its deployment path is complete.
- FabricIQ remains optional until a real data-agent source is proven.
- Microsoft 365 and Teams publication is separate and admin-gated.

For deployment details, see [docs/deployment.md](../../../docs/deployment.md).
