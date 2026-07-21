# Agent catalog

This catalog lists the hosted agents declared by `modules/agents/azure.yaml`.
The root deployment selects a four-agent default fleet and adds optional
evidence experts only when their IQ lane is enabled.

| Agent | Default | Role | Tools and evidence | Authority |
| --- | --- | --- | --- | --- |
| `invoice-analyst` | Yes | Human-facing invoice Q&A and run/case status. | Waypoint status, WaypointIQ reads, FoundryIQ grounding, Responses and Microsoft 365 activity surfaces. | Read-only. |
| `assurance-orchestrator` | Yes | Deterministic coordinator for one invoice-assurance run. | Waypoint reads, deterministic checks, selected hosted expert endpoints, Content Understanding, recorder endpoint. | Coordinates only; no direct governed-result writes. |
| `contract-policy-expert` | Yes | Contract and policy evidence lane. | FoundryIQ `contracts-kb` through the knowledge-base MCP connection. | Read-only evidence. |
| `waypoint-recorder` | Yes | Final validation and persistence boundary. | Waypoint write client and policy checks. | Sole agent writer. |
| `collaboration-evidence-expert` | No | Collaboration and workplace evidence. | WorkIQ Microsoft 365 tools under user context. | Read-only evidence. |
| `market-evidence-expert` | No | External market corroboration. | WebIQ / Foundry web grounding. | Read-only evidence. |
| `operations-data-expert` | No | Structured operational evidence. | FabricIQ when a real Fabric Data Agent source is configured. | Read-only evidence. |

## Deployment rules

- Default agents:
  `invoice-analyst`, `assurance-orchestrator`,
  `contract-policy-expert`, and `waypoint-recorder`.
- Optional lane flags:
  `workiq_enabled`, `webiq_enabled`, and `fabriciq_enabled`.
- FoundryIQ is enabled by default.
- Agent names come from `azure.yaml` and must match the deployment manifest and
  orchestrator endpoint wiring.
- `waypoint-recorder` is the only agent that receives writer authority.
- Historical names such as `assurance-analyst`, `status-concierge`,
  `aggregator`, `foundryiq-expert`, `workiq-expert`, `webiq-expert`, and
  `fabriciq-expert` are not active fleet members.

## Evaluation and optimization

The current quality target is `contract-policy-expert`, because it is the
default grounded evidence lane and has a Foundry-native evaluation contract.
Use:

1. Foundry-native rubric generation and baseline evaluation.
2. Foundry Agent Optimizer for reviewed instruction and configuration
   candidates.
3. Caliber datasets, deterministic graders, and calibration for repeatable
   quality gates.
4. Caliber RFT/RLE planning when a cheaper model should preserve an approved
   quality target.

Do not treat optimization plans or historical run artifacts as proof of a
promoted runtime version.
