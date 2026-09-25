# contracts

`contracts` is the stub for Waypoint's Teams-first contract intake autopilot.
It is intentionally deployable before the new Waypoint Contracts API exists, so
the product name, protocols, and future tool contract can settle while the API
surface is built.

## Intended flow

1. A user emails a contract PDF to the Contracts inbox.
2. A Foundry routine wakes this hosted agent on a schedule.
3. The agent polls the inbox through a future Graph/WorkIQ connector.
4. New attachments are deduped and registered in Waypoint as contract artifacts.
5. Content Understanding extracts values.
6. Evidence tools gather FoundryIQ, WebIQ, WorkIQ, FabricIQ, and Waypoint
   evidence.
7. Teams users ask Contracts about the latest or prior contracts.
8. On request, Contracts generates a document, stores it in SharePoint, and
   shares it after user approval.

## Current behavior

The agent registers all three Castia protocols:

| Protocol | Purpose |
| --- | --- |
| `responses` | Routine/background work and direct Foundry runs. |
| `activity` | Teams-style conversational surface. |
| `invocations` | Agent-to-agent/tool use. |

The tools in `tools.py` are API-ready scaffolds. When `WAYPOINT_API_BASE_URL` is
unset, local fixture mode is enabled so the playground can exercise the flow
without the future API:

- `poll_contracts_inbox` seeds a mock Aster Ridge contract artifact.
- `get_last_contract` resolves that mock artifact.
- `draft_contract_report` writes a local Markdown report under
  `.contracts-state/reports/`.

When fixture mode is disabled, those tools return `not_implemented` with the
future Waypoint API call each behavior expects.

## Local development

```powershell
cd modules\agents\contracts
uv sync
uv run python main.py
```

Useful local prompts:

```text
What can Contracts do right now?
Check the Contracts inbox.
What was in the last contract I sent?
Draft a contract brief for the latest artifact.
```
