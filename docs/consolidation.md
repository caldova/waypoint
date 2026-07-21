# Historical consolidation notes

> [!WARNING]
> This document records the completed source consolidation. It is not an
> architecture or deployment guide. Use the root [README](../README.md),
> [architecture](architecture.md), and [deployment guide](deployment.md) for the
> current system.

Waypoint now contains the application, corpus, agents, evaluations,
optimization assets, deployment tooling, Copilot skills, and canvases in one
monorepo.

| Current path | Responsibility |
| --- | --- |
| `apps/waypoint/` | Application runtime |
| `modules/corpus/` | Synthetic data and document generation |
| `modules/agents/` | Hosted Foundry agents and toolboxes |
| `modules/evals/` | Caliber evaluation tooling |
| `modules/optimization/` | Optimization and RFT/RLE assets |
| `tools/deploy/` | Monorepo deployment helpers |

Compatibility package and CLI names remain only where changing them would break
imports, commands, or persisted contracts. They do not imply separate
repositories or a separate deployment orchestrator.
