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

On Microsoft 365 Activity turns, the agent also offers Castia's agentic-user
Microsoft Graph tools. Those tools receive the original Teams/Agent 365 Activity
so Castia can mint the agentic-user token and act as the hired agent's own
mailbox/OneDrive identity:

- `read_inbox` reads recent messages from the agent mailbox.
- `send_email` sends a new message from the agent mailbox.
- `reply_email` replies in-thread to a message read from that mailbox.
- `create_document` creates a Markdown/text document in the agent's OneDrive and
  shares it with the requester.

The Graph tools are intentionally not exposed on plain Responses or Invocations
turns because those surfaces do not carry the Agent 365 `agenticUser` Activity
identity required for mailbox/OneDrive actions.

The Activity surface registers lightweight Castia commands that bypass the model
and return runtime state directly:

- `/version` shows Foundry agent version, Microsoft 365 app version, model, and
  hosted identity metadata.
- `/state` shows configured Contracts surfaces and feature flags.
- `/whoami` shows the Teams/Agent 365 Activity identity shape.
- `/tools` lists the tools exposed on Responses versus Activity turns.
- `/health` checks protocol/model/agentic-user readiness.
- `/trace` prints Activity and conversation IDs for telemetry lookup.

The Activity chat surface is intentionally mode-aware:

- Capability/help prompts return a transparent summary of what is live, what is
  stubbed, and what to try next.
- Latest-invoice prompts return fixture invoice summaries with review status and
  suggested follow-up actions.
- Slash/debug commands bypass the model and return concise runtime diagnostics.

## Package layout

The hosted entrypoint stays tiny in `main.py`; behavior lives under
`agent/`:

| Path | Purpose |
| --- | --- |
| `agent/domain/` | Shared business behavior, fixtures, modes, and diagnostics. |
| `agent/protocols/activity/` | Teams / Agent 365 Activity commands, cards, and handlers. |
| `agent/protocols/responses/` | Responses protocol adapter. |
| `agent/protocols/invocations/` | Invocations protocol adapter. |
| `agent/integrations/` | External identity/API helpers such as Activity identity. |
| `agent/tools/` | Castia model-callable tool definitions. |
| `agent/toolsets.py` | Protocol-specific model and toolset composition. |

## Microsoft 365 activation permissions

The autopilot publish metadata requests Microsoft Graph delegated permission
scopes for the agentic-user mailbox and OneDrive access used by Castia's
Graph helpers:

- `Mail.Read` for reading the agent's mailbox.
- `Mail.Send` for sending and replying from the agent's mailbox.
- `Files.ReadWrite` for creating documents in the agent's OneDrive and sharing
  them with the requester.

The Microsoft 365 admin center shows these permissions during the **Pending
activate** approval wizard. They define the agent user's allowed M365 surface;
the Contracts-specific intake/report tools still stay in local fixture / future
API mode until the Waypoint Contracts intake and report APIs are implemented.

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

## Remaining work before `v2`

This branch is a good baseline for merging the Contracts agent into `v2`, but
the production story still has a few explicit gaps:

- Replace fixture-mode inbox/artifact/report behavior with the Waypoint
  Contracts API once that surface exists.
- Confirm Agent 365 Activity payloads include `recipient.role=agenticUser` and
  the agentic-user identifier needed by Castia Graph tools in Teams.
- Keep `/version` as the primary field diagnostic and verify it reports the live
  Foundry version after each deploy, not just the configured environment value.
- Continue validating Teams typing/streaming behavior with real Teams turns; the
  agent starts status immediately and does not delay the final response just to
  show typing.
- Wire production telemetry dashboards around Activity turns, tool calls, slash
  diagnostics, and error rates once the Teams path is stable.
