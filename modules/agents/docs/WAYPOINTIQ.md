# WaypointIQ toolbox boundary

WaypointIQ is the curated agent-facing tool surface over the Waypoint API.
Waypoint remains the system of record; WaypointIQ is a capability contract, not
an agent.

## Responsibilities

| Layer | Responsibility |
| --- | --- |
| Waypoint API | Owns invoices, work, findings, evidence, cases, recommendations, runs, approvals, and audit. |
| `waypoint-iq` | Exposes selected API operations as a versioned Foundry toolbox. |
| Hosted agents | Reason over tool results within their assigned authority. |

## Capability groups

| Group | Operations | Runtime consumers |
| --- | --- | --- |
| Read | Work, invoices, findings, evidence, contracts, policies, runs, and cases. | `invoice-analyst`, `assurance-orchestrator`, and approved read-only agents. |
| Write | Run, case, recommendation, draft, and finalization operations. | `waypoint-recorder` only. |
| Admin | Seed import, authorization, and administrative operations. | Deployment or human admin automation only. |

The toolbox may contain multiple capability groups, but Waypoint-side
authorization remains authoritative. A tool appearing in OpenAPI does not grant
an agent permission to call it.

## Current runtime use

Hosted agents still use a mix of curated toolbox operations and direct Waypoint
clients. The governance rule is the same for both:

- `invoice-analyst` is read-only.
- `assurance-orchestrator` reads context and coordinates lifecycle.
- `contract-policy-expert` is read-only.
- `waypoint-recorder` is the sole writer.

The root deployment supplies the current Waypoint endpoint and scoped
credentials. Do not hardcode deployment-specific app IDs, object IDs, endpoints,
or toolbox versions in documentation.

## Source

The checked contract lives under `modules/agents/iqs/waypoint-iq/`:

- `openapi.json` - curated Waypoint operations
- `toolbox.yaml` - toolbox source configuration
- `scripts/export_openapi.py` - endpoint-aware OpenAPI export
- `scripts/deploy_toolbox.py` - idempotent toolbox create/update
- `tests/` - local contract and smoke coverage

Production Waypoint can disable public API docs, so deployment uses the curated
checked contract rather than exposing the unrestricted runtime OpenAPI document.

## Safety requirements

- Read tools require reader authority.
- Write tools require writer authority and are bound only to
  `waypoint-recorder`.
- Admin tools are absent from normal agent bindings.
- Write results report whether side effects occurred and include Waypoint
  correlation IDs.
- Failed writes surface errors; callers must not receive success-shaped fallback
  results.
- Sensitive content follows Waypoint classification and redaction rules.

## Deployment

The root workflow deploys or updates the toolbox as part of the selected hosted
agent path and wires the app and agents from current deployment outputs. See
[docs/deployment.md](../../../docs/deployment.md).
