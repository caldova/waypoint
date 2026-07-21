# Compatibility names

Waypoint uses monorepo paths such as `apps/waypoint`, `modules/corpus`,
`modules/agents`, `modules/evals`, and `modules/optimization`.

Some code-level names remain because they are package names, CLI entry points,
or persisted contracts:

| Compatibility name | Current use | Monorepo path |
| --- | --- | --- |
| `ledgerfield` | Corpus Python package and CLI | `modules/corpus` |
| `caliber` | Evaluation Python package and CLI | `modules/evals` |
| `Forge` | Foundry-facing identity for the hosted agent module | `modules/agents` |

These names do not represent external source boundaries. Public guidance should
use the module role first and mention a compatibility name only when a command,
import, or historical artifact requires it.
