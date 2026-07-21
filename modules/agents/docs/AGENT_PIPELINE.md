# Invoice assurance agent pipeline

This document describes the Caldova Forge multi-agent invoice-assurance
pipeline that turns Ledgerfield demo corpus + live evidence planes into
governed Caldova Waypoint data.

For a role-by-role matrix of every current agent, deployment shape, tool/IQ
surface, and Caliber/RFT relevance, see [`AGENT_CATALOG.md`](AGENT_CATALOG.md).
For the current implementation status, deployment paths, shared resources, and
Jess handoff checklist, see [`FORGE_CURRENT_STATE.md`](FORGE_CURRENT_STATE.md).

## Topology

```text
assurance-orchestrator (workflow agent)
  ├─ fan-out ─► collaboration-evidence-expert    (expert with Microsoft 365 / WorkIQ tools) ─┐
  ├─ fan-out ─► market-evidence-expert     (expert with WebIQ tools)                  ├─► expert
  ├─ fan-out ─► contract-policy-expert (expert with FoundryIQ / KB tools)          │   evidence
  ├─ fan-out ─► operations-data-expert  (expert with FabricIQ tools or stub)        ┘
  └─ hand-off ─► waypoint-recorder ──► final policy check ──► WaypointIQ write tools
                                                              │
assurance-analyst (Q&A/status + Teams) ◄── Waypoint status/read tools
assurance-analyst (Q&A/status + Teams) ─► WaypointIQ read tools + FoundryIQ KB
```

WaypointIQ is the agent-facing OpenAPI toolbox boundary over Caldova Waypoint.
The current hosted agents still use direct Waypoint clients, but the target
shape is one toolbox named `waypoint-iq`. Read, write, and admin authority are
represented through operation metadata, agent binding policy, and Waypoint
authorization rather than separate toolbox names. See [`WAYPOINTIQ.md`](WAYPOINTIQ.md).

- **assurance-orchestrator** — workflow agent. It owns deterministic invoice-assurance
  orchestration: gather inputs, fan out to experts, normalize/repair their
  evidence into canonical validator results, draft the write plan, and decide
  whether the workflow can proceed. Assurance Orchestrator may use a
  bounded model step for summarization or adjudication, but it should not
  rediscover facts already delegated to experts. The current proof path keeps
  Waypoint writes outside Assurance Orchestrator until WaypointIQ write authority is proven;
  later Assurance Orchestrator may write through that governed surface. When
  `ASSURANCE_ORCHESTRATOR_RUN_JOURNAL_DIR` is set, Assurance Orchestrator writes redacted JSON checkpoints as
  it works so a partial run can be inspected if the process is interrupted.
- **domain experts** — small, single-purpose hosted agents. Each expert reasons
  over one evidence plane and may have IQ tools attached through Foundry
  toolboxes or native Foundry tools. WorkIQ uses a Foundry toolbox backed by
  Microsoft 365 UserEntraToken RemoteTool connections so calls run as the
  current user. Each expert returns repairable **expert evidence** rather than
  final Waypoint/write JSON. Keeping each expert narrow makes it cheap to
  fine-tune and easy to unit-test.
- **waypoint-recorder** — consumes Assurance Orchestrator's approved write-plan preview, validates the
  final Waypoint payload, runs the final policy check against Ledgerfield
  policies, and **writes** the result through WaypointIQ write tools (run anchor,
  assurance case, recommendation, draft). Owns the write path and the
  managed-identity auth.
- **assurance-analyst** — hosted read-only Q&A and status agent. Reads live
  run/case status through direct Waypoint status tools, operational facts from
  the durable `waypoint-iq` toolbox, and contract/policy grounding from the
  FoundryIQ knowledge-base toolbox. It serves both the Foundry Responses surface
  and the Microsoft 365 `activity_protocol` surface; it does not replace
  Assurance Orchestrator orchestration or waypoint-recorder writes.

Planned extension: `waypoint-operations-expert` is the intended future prompt
agent for operational interpretation, action selection, and write-plan review
over `waypoint-iq`. It is not part of the current active fleet until an
`agents/waypoint-operations-expert/` source folder, prompt metadata, evals, and
deployment wiring exist.

FoundryIQ knowledge-base provisioning is documented in
[`FOUNDRY_KNOWLEDGE_BASE.md`](FOUNDRY_KNOWLEDGE_BASE.md), including the
`contracts-kb` resource name, embedding deployment requirement, and automation
handoff notes.

Invoice PDF extraction with Content Understanding is documented in
[`CONTENT_UNDERSTANDING.md`](CONTENT_UNDERSTANDING.md), including the account
endpoint, model-default, RBAC, and Assurance Orchestrator integration requirements.

Each expert agent owns a single `agents/<name>/prompt.md` file with
Prompty-compatible YAML frontmatter plus Forge-specific metadata under
`metadata.forge`. The four domain experts deploy as hosted agents in Foundry:
their `metadata.forge.deployment.hosted.enabled` flag is true and their
`metadata.forge.deployment.prompt.enabled` flag is false. Hosted wrappers load
the same `prompt.md` with the Prompty Python loader so the instructions stay in
one place.

## Why split this way

Each agent does one narrow job so we can:

1. **Fine-tune cheaply** — small single-purpose prompts + small models per task.
2. **Evaluate** — each current active agent should have golden cases in
   `evals/cases/<agent>_golden.jsonl` and a reviewed Foundry-native evaluation
   contract. The golden sets double as future SFT seed data. Historical eval
   assets without a matching active agent folder are not part of the current
   fleet.
3. **Govern the write boundary** — write-capable agents use explicit WaypointIQ
   write bindings behind one app role.

## Expert evidence contract

Every expert should return a single JSON object on this repairable shape.
`expert_evidence` is optimized for tool-grounded extraction and future RFT:
claims/snippets, stable source refs, provenance, confidence, and explicit
unsupported/unknown items. Assurance Orchestrator, not the expert, owns canonical schema
normalization, conflict reconciliation, and write-plan preview generation.

```json
{
  "agent": "collaboration-evidence-expert",
  "plane": "workiq",
  "invoice_id": "INV-2026-08034",
  "output_type": "expert_evidence",
  "expert_evidence": [
    {
      "claim": "Short statement of what this evidence shows.",
      "supports": "approve | recover | escalate | review | unknown",
      "source_ref": "Stable locator: doc id, url, table/row, batch id, etc.",
      "classification": "standard | confidential | ip_sensitive | restricted",
      "confidence": 0.0
    }
  ],
  "summary": "1-3 sentence plane-level summary.",
  "unsupported": ["Important unanswered questions or unavailable sources."],
  "correlation": {
    "waypoint_run_id": null,
    "waypoint_invoice_id": "INV-2026-08034"
  }
}
```

Rules for experts:

- Prefer a JSON object with this shape, but prioritize grounded claims and source
  refs over guessing canonical defaults.
- `plane` is one of `workiq`, `webiq`, `foundryiq`, `fabriciq`.
- Never place `ip_sensitive` or `restricted` raw content in `claim`/`summary`; describe
  it and point to `source_ref` instead. Classification gates what enters telemetry.
- Use `unknown` + low confidence rather than guessing when the plane has no signal.
- Assurance Orchestrator marks outputs as `valid`, `partial`, `malformed`, or `no_evidence` and
  carries unsupported items forward for deterministic handling.

## Waypoint Recorder output → Waypoint

The waypoint-recorder emits one assurance decision per invoice and writes it through
governed WaypointIQ write tools backed by the Waypoint API:

1. `POST /api/runs` — open a run anchor (carries `foundry_agent_name`,
   `app_insights_operation_id`); capture `waypoint_run_id`.
2. `POST /api/cases` — open/locate the assurance case for the invoice.
3. `POST /api/cases/{id}/recommendations` — recommendation with decision
   (`approve|recover|escalate|review`), rationale, confidence, evidence refs.
4. `POST /api/cases/{id}/drafts` — optional supplier dispute / escalation draft.
5. Update the run with a business summary and final status.

All writes carry the Waypoint correlation IDs (`waypoint_run_id`, `waypoint_case_id`)
so business decisions link to Foundry / App Insights telemetry without timestamp
matching. See `waypoint/docs/agent-api-control-plane-plan.md` for the control-plane
contract and the writer app-role requirement.

## Auth

- Local dev: `AzureCliCredential` against the Waypoint API scope.
- Deployed: the waypoint-recorder's per-instance **managed identity**, granted the Waypoint
  **writer** app role. Experts and `assurance-analyst` need only reader access (and the
  experts mostly call their own evidence planes, not Waypoint).
- Concrete Waypoint app roles (see `waypoint/docs/agent-api-control-plane-plan.md`):
  - `Waypoint.Write` — granted to the **waypoint-recorder** MI (write path: runs, cases,
    recommendations, drafts, proposed actions).
  - `Waypoint.Read` — granted to the **assurance-analyst** MI (read-only run/case status).
  - `Waypoint.Admin` — delegated admin only (approvals, authorize, seed); no agent uses it.
- `WAYPOINT_API_SCOPE` is the app-only scope `api://<waypoint-api-client-id>/.default`.
  App-only (managed-identity) tokens are validated against these app roles, not a
  delegated `scp` claim. The umbrella deploy grants the roles using Waypoint's
  `deploy.yml` outputs (`api_app_id_uri`, `api_default_scope`, `api_fqdn`, `web_fqdn`).

The same authority split carries into WaypointIQ: read operations map to
Waypoint reader authority, write operations map to Waypoint writer authority,
and admin operations stay out of agent runtime bindings by default. WaypointIQ is
a tool surface, not the reasoning layer. A future Waypoint operations expert can
interpret and apply those tools once it is added to the fleet.

## Fan-out wiring

`assurance-orchestrator` reaches the hosted evidence experts through
OpenAI-Responses-compatible endpoints supplied by environment variables. The
deploy workflow computes these from the current Foundry project endpoint using
the canonical agent names before deploying `assurance-orchestrator`:

| Env var | Target |
| --- | --- |
| `WORKIQ_EXPERT_ENDPOINT` | collaboration-evidence-expert Responses endpoint |
| `WEBIQ_EXPERT_ENDPOINT` | market-evidence-expert Responses endpoint |
| `FOUNDRYIQ_EXPERT_ENDPOINT` | contract-policy-expert Responses endpoint |
| `FABRICIQ_EXPERT_ENDPOINT` | operations-data-expert Responses endpoint |
| `WAYPOINT_RECORDER_ENDPOINT` | waypoint-recorder Responses endpoint |
| `EXPERT_AGENT_SCOPE` | token scope for the calls (default `https://ai.azure.com/.default`) |

Hosted expert fan-out is selected with
`ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE=responses`. When an endpoint is
unset (e.g. local dev before the pipeline is wired), Assurance Orchestrator's
corresponding chat fan-out tool stays disabled and Assurance Orchestrator
operates in its current read-only scout posture. Historical prompt-agent
migration notes live in [`PROMPT_AGENT_MIGRATION.md`](PROMPT_AGENT_MIGRATION.md).
`assurance-analyst` is wired with `WAYPOINT_API_BASE_URL` /
`WAYPOINT_API_SCOPE` for its read-only run/case status surface in Teams.

## Run journal

Assurance Orchestrator's workflow returns a final JSON payload by default. For longer-running
local or deployed runs, set `ASSURANCE_ORCHESTRATOR_RUN_JOURNAL_DIR` to enable a per-run JSON
journal:

```text
<ASSURANCE_ORCHESTRATOR_RUN_JOURNAL_DIR>/
  assurance-orchestrator-<timestamp>-<id>/
    01-request_normalized.json
    02-work_discovered.json
    ...
    latest.json
```

The journal records each major workflow checkpoint: request normalization, work
discovery, run preparation, document resolution, Waypoint context, deterministic
checks, expert validation, judgement synthesis, write-plan preparation, and
completion. Journal files redact raw base64 fields such as inline PDFs; they are
for recovery and debugging, not for storing source documents.
