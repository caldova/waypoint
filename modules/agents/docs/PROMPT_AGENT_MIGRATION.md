# Historical prompt-agent migration and hosted cutover

This document records the June 2026 prompt-agent experiment and the subsequent
hosted-agent cutover. It is historical context, not the current deployment
shape.

Current state: Caldova Forge treats the single-plane evidence experts as hosted
Foundry agents. Their `prompt.md` files remain the instruction source, but
`metadata.forge.deployment.prompt.enabled` is false and
`metadata.forge.deployment.hosted.enabled` is true.

## Split

| Agent | Deployment path | Why |
| --- | --- | --- |
| `collaboration-evidence-expert` | Hosted agent | Microsoft 365 evidence collection needs hosted request-context forwarding into the WorkIQ/UserEntraToken toolbox. |
| `market-evidence-expert` | Hosted agent | External web corroboration runs through hosted Foundry web-search tooling. |
| `contract-policy-expert` | Hosted agent | Contract/policy/finding retrieval runs through a hosted KB toolbox path. |
| `operations-data-expert` | Hosted agent | Current implementation is an honest no-Fabric-source-yet stub; hosting keeps the orchestrator transport consistent. |
| `assurance-orchestrator` | Hosted agent | Owns deterministic invoice-assurance orchestration, Content Understanding, and Waypoint read workflow. |
| `waypoint-recorder` | Hosted agent | Owns write-boundary behavior and Waypoint recommendation persistence. |
| `invoice-analyst` | Hosted agent | Owns the Teams/M365 status surface plus read-only analysis over Waypoint status, WaypointIQ operational facts, and FoundryIQ contract/policy grounding. |

## Source of truth

Each hosted expert still loads instructions from `agents/<name>/prompt.md`.

- Prompty top-level fields (`name`, `displayName`, `description`, `model`,
  `inputs`, `outputs`, `tools`) describe the prompt asset.
- `metadata.forge.deployment.hosted.enabled: true` marks the expert as a hosted
  `azd` deployment.
- `metadata.forge.deployment.prompt.enabled: false` keeps the historical
  prompt-agent deployment automation from recreating prompt agents.
- `metadata.forge.deployment.prompt.agentName` may remain as historical metadata
  but is not active while prompt deployment is disabled.
- The markdown body remains the runtime instructions and evidence contract.

## CI status

`Validate` installs Prompty and runs:

````bash
python scripts/prompt_agent_plan.py --check
```

That check loads prompt-enabled `agents/*/prompt.md` files with Prompty. In the
current fleet it should report zero prompt-agent deployments.

The hosted deploy workflow still uses:

```bash
python scripts/discover_agents.py
```

That script includes the four evidence experts because their `prompt.md` files
set `metadata.forge.deployment.hosted.enabled: true`.

## Historical manual replacement procedure

This was the prompt-agent procedure used during the experiment. Do not use it
for the current hosted evidence experts unless a future change explicitly
re-enables `metadata.forge.deployment.prompt.enabled`.

1. Resolve the Forge project endpoint and model deployment from the active azd
   environment or GitHub Actions variables.
2. Load `agents/<name>/prompt.md` with Prompty.
3. Use the Foundry prompt-agent update path to create/update agent `<name>` with:
    - `kind: prompt`
    - `model`: `prompt.model.id`
    - `instructions`: `prompt.instructions`
    - `temperature`: `prompt.model.options.temperature`
    - supported tool bindings from `prompt.tools`
4. Invoke the updated agent with the smoke invoice from
   `metadata.forge.smoke.invoiceId`.
5. Validate the response against the shared IQ evidence contract.
6. Only after all four prompt agents smoke-test, wire Assurance Orchestrator to those prompt
   agent endpoints and leave the prior hosted versions as rollback until the
   next confidence review.

## Live Forge project findings

2026-06-27 live inspection of the `rg-forge` / `ai-project-forge` project found
the earlier IQ-surface-named expert agents still active as hosted rollback
agents:

| Hosted rollback agent | Latest live kind | Latest live version | Replacement prompt-agent name |
| --- | --- | --- | --- |
| `fabriciq-expert` | `hosted` | `11` | `operations-data-expert` |
| `foundryiq-expert` | `hosted` | `11` | `contract-policy-expert` |
| `webiq-expert` | `hosted` | `12` | `market-evidence-expert` |
| `workiq-expert` | `hosted` | `12` | `collaboration-evidence-expert` |

The current `azure-ai-projects` prompt-agent update path creates a new version
with `client.agents.create_version(agent_name, definition=PromptAgentDefinition(...))`.
That API rejects replacing an existing hosted agent with a prompt agent in place:

```text
bad_request: Agent kind mismatch for '<agent>'. Existing: hosted, New: prompt.
```

The responsibility-based prompt-agent names avoid this hosted-to-prompt kind
conversion problem. Keep the earlier hosted names as rollback until the new
prompt agents and deployed Assurance Orchestrator routing are proven end to end.

Live project tool-binding findings for Jess' automation:

| Prompt agent | `prompt.md` tools | Live binding status |
| --- | --- | --- |
| `market-evidence-expert` | `web_iq` | Target binding is the direct WebIQ MCP server (`https://api.microsoft.ai/v3/mcp`) with a `CustomKeys` project connection named `web-iq`, matching Brightline's `GridOps` pattern. |
| `contract-policy-expert` | `knowledge_base`, `gather_foundry_evidence` | Project has `kb-mcp-connection` targeting `contracts-kb` MCP, so `knowledge_base` can bind as an MCP tool with `allowed_tools=[knowledge_base_retrieve]` and `require_approval=never`. `gather_foundry_evidence` is a local/client-side hosted fallback and has no executable prompt-agent function implementation yet. |
| `collaboration-evidence-expert` | `workiq_email`, `workiq_teams`, `workiq_sharepoint` | Brightline's `GridOps` pattern works when the project has catalog MCP `UserEntraToken` connections `WorkIQCopilot`, `WorkIQTeams`, and `WorkIQSharePoint` with Agent 365 audience `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1`. |
| `operations-data-expert` | none | No tool binding needed while FabricIQ remains an honest stub. Brightline has a separate `BrightlineSemanticModel` Fabric IQ RemoteTool connection, but Forge has no equivalent Fabric semantic-model connection yet. |

Automation gap: the deployment job needs a preflight that lists existing agent
kinds before calling the prompt update API. If an existing agent has a different
kind, fail with the kind-mismatch guidance above instead of deleting, recreating,
or creating a differently named prompt agent without explicit approval.

### Responsibility-named prompt-agent results

2026-06-27 follow-up created the responsibility-named prompt agents with
`scripts/deploy_prompt_agents.py`, which loads each `agents/<name>/prompt.md`
with Prompty, preflights existing agent kind, creates a prompt-agent version with
`client.agents.create_version(..., definition=PromptAgentDefinition(...))`, and
smokes through the Foundry project `/openai/v1/responses` `agent_reference`
path.

| Prompt agent | Live version | Binding result | Smoke result |
| --- | --- | --- | --- |
| `collaboration-evidence-expert` | `1` | Bound WorkIQ catalog MCP connections `WorkIQCopilot`, `WorkIQTeams`, and `WorkIQSharePoint`. | Passed. Returned a valid `workiq` evidence contract with no evidence for the smoke invoice. |
| `market-evidence-expert` | `1` | Bound direct WebIQ MCP connection `web-iq` with allowed tools `web` and `browse`. | Initial smoke timed out server-side; retry passed with a valid `webiq` evidence contract and no relevant public evidence. |
| `contract-policy-expert` | `1` | Bound `kb-mcp-connection` for `knowledge_base_retrieve`; skipped local fallback function `gather_foundry_evidence` because prompt agents have no executable implementation for it yet. | Passed. Returned grounded `foundryiq` evidence from `contracts-kb`. |
| `operations-data-expert` | `1` | No tool binding; FabricIQ remains an honest stub. | Passed. Returned a valid `fabriciq` stub contract. |

Assurance Orchestrator was then smoked locally against the four responsibility-named prompt
agents with `ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE=prompt`. All validator lanes
completed through `foundry_prompt_agent`, used the new
`*.agent_reference` tool names, and the workflow remained read-only with
`side_effects_performed: false`.

### Prompt-agent canary results

To avoid deleting the hosted rollback agents first, temporary prompt-agent
canaries were created under the earlier `*-prompt-canary` names. The original
hosted agents were left untouched. These canaries proved the bindings before the
responsibility-based prompt-agent names were created.

| Previous source agent | Canary agent | Latest canary version | Result |
| --- | --- | --- | --- |
| `fabriciq-expert` | `fabriciq-expert-prompt-canary` | `2` | Prompt canary active; smoke test passed the shared IQ evidence contract with the expected empty FabricIQ stub evidence. |
| `foundryiq-expert` | `foundryiq-expert-prompt-canary` | `2` | Prompt canary active; `knowledge_base` MCP binding smoked successfully against `contracts-kb`; `gather_foundry_evidence` remains a local fallback with no prompt-agent function implementation. |
| `webiq-expert` | `webiq-expert-prompt-canary` | `5` | Prompt canary active; Brightline-style direct WebIQ MCP binding smoked successfully against the shared evidence contract. |
| `workiq-expert` | `workiq-expert-prompt-canary` | `5` | Prompt canary active; Brightline-style WorkIQ catalog MCP connections with Agent 365 audience smoked successfully against the shared evidence contract. |

Additional live API findings:

- Prompt invocation must use `extra_body.agent_reference` with
  `{"type": "agent_reference", "name": "<agent-name>"}`. The older
  `extra_body.agent` shape is rejected as deprecated.
- `gpt-5.5` rejected `temperature` at invocation time, so canary versions `2+`
  omit `prompt.md` `model.options.temperature`. Automation should either omit
  unsupported sampling parameters for models that reject them or fail with a
  clear model-parameter gap.
- The first WebIQ canary used Bing grounding only to prove prompt-agent
  connectivity. Brightline's `GridOps` agent uses a direct WebIQ MCP connection:
  `server_url=https://api.microsoft.ai/v3/mcp`, `server_label=web-iq`,
  `project_connection_id=web-iq`, `allowed_tools=[web,browse]`, and
  `require_approval=never`. Forge automation should create or reference the
  same secret-backed `CustomKeys` project connection shape; do not use
  `webiq-bing` for the final market/WebIQ evidence-lane cutover.
- WorkIQ catalog MCP connections must include Agent 365 audience
  `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1`. Without it, invocation fails with
  `Missing required query parameter: audience`.
- The calling app registration also matters for app-integrated WorkIQ flows.
  Brightline's `brightline-app` (`<sample-app-client-id>`)
  requests delegated **Agent Tools** permissions on resource app
  `ea9ffc3e-8a23-4a7d-836d-234d7c7565c1`:
  `McpServers.CopilotMCP.All` and `McpServers.OneDriveSharepoint.All`.
  Forge needs the equivalent API permissions and tenant admin consent on
  whichever app registration supplies the signed-in user's token to Foundry.
  If Forge calls direct Teams or Mail MCP servers rather than routing through
  Copilot/SharePoint, also review the Agent Tools scopes
  `McpServers.Teams.All` and `McpServers.Mail.All` before cutover.
- Brightline's FoundryIQ binding adds `headers.x-ms-query-source-authorization =
  {{user_token}}` for app-provided delegated Search authorization. Forge's
  `contract-policy-expert` can smoke without that header for the current
  `contracts-kb` ProjectManagedIdentity connection, but Jess should preserve the
  structured-input/header option if a user-delegated retrieval path is added.
- Brightline's FabricIQ signal is a separate `BrightlineSemanticModel`
  `RemoteTool` connection to
  `https://api.fabric.microsoft.com/v1/mcp/fabricaihub/integrations/m365` with
  `UserEntraToken` credentials and `fabric_iq_preview` metadata. Forge has no
  equivalent Fabric workspace/artifact connection yet, so `operations-data-expert`
  should remain a stub until those values exist.
- Portal inspection confirmed the migrated prompt agents show their expected
  tools: collaboration has the three Microsoft 365 tools, market has WebIQ,
  contract-policy has the knowledge base, and operations-data is intentionally
  empty until a Fabric connection exists.

## Evidence normalization and RFT boundary

The four prompt experts are now expected to be fine-tuning-friendly evidence
extractors, not final canonical JSON authors. Their prompts prefer a repairable
`expert_evidence` object with claims/snippets, source refs, confidence,
classification/provenance, and explicit `unsupported`/unknown items. They should
not invent global schema defaults just to satisfy a downstream write contract.

Assurance Orchestrator is the deterministic normalization boundary. It accepts either legacy
`evidence` or new `expert_evidence`, derives canonical validator findings and
evidence IDs, carries unsupported items, and marks expert output quality as
`valid`, `partial`, `malformed`, or `no_evidence`. This is the right place for
schema repair, conflict reconciliation, and `write_plan.future_payloads[]`
preview generation.

Waypoint Recorder remains the final Waypoint write boundary. It should receive
Assurance Orchestrator-approved write-plan payloads, validate the final operational JSON, and
persist through `waypoint_record_assurance`; it should not interpret raw expert
outputs. Caliber owns future expert RFT datasets/graders focused on correct tool
use, evidence fidelity, source coverage, unsupported-claim penalties, and
repairable structure.

Live confidence pass on 2026-06-27 (historical prompt-agent experiment):

- `scripts/deploy_prompt_agents.py` updated all four in-place prompt-agent
  replacements to version `2` in the Forge Foundry project and smoke-tested each
  with the relaxed expert-evidence contract.
- Smoke results matched the intended live-tool posture: WorkIQ and WebIQ returned
  valid no-evidence/unsupported summaries for the bare invoice-id prompt,
  contract-policy returned grounded knowledge-base evidence, and operations-data
  remained the expected FabricIQ stub.
- A local Assurance Orchestrator run with `ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE=prompt` completed
  through `foundry_prompt_agent` fan-out, produced one read-only
  `write_plan.future_payloads[]` preview, and performed no Waypoint side effects.

## Current hosted cutover confidence

2026-06-30 hosted cutover:

- The four prompt agents were deleted from the Forge Foundry project because
  Foundry cannot convert an existing prompt agent to hosted in place.
- Hosted replacements were deployed under the canonical names:
  `collaboration-evidence-expert`, `market-evidence-expert`,
  `contract-policy-expert`, and `operations-data-expert`.
- `assurance-orchestrator` version 6 was redeployed with hosted expert endpoint
  wiring and `ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE=responses`.
- Deployed diagnostic fan-out completed end to end. WorkIQ executed through the
  hosted collaboration expert and `collaboration-evidence-tools` toolbox, but
  found no invoice-specific Microsoft 365 matches for `INV-2026-08034`.

Current CI should deploy the evidence experts through the hosted `azd deploy`
matrix and run only drift reconciliation afterward. It should not recreate the
four retired prompt agents.

## WaypointIQ follow-up

The prompt-agent canary pipeline run proved Assurance Orchestrator's read-only
workflow could consume prompt-agent evidence when its expert client invoked
canaries with `agent_reference`. That is no longer the active path. The current
deployed path uses hosted downstream `/agents/<name>/endpoint/...` Responses
URLs.

WaypointIQ is the preferred long-term Waypoint capability boundary for this
pipeline. It is a tool surface, not an agent. A future `waypoint-operations-expert` prompt
agent should reason over Caldova/Waypoint operational state with WaypointIQ tools
attached, while Assurance Orchestrator remains a workflow agent that orchestrates experts and
deterministic gates.

WaypointIQ should expose Caldova Waypoint read/write operations as one governed
OpenAPI toolbox named `waypoint-iq`. Read, write, and admin authority should be
represented through operation metadata, agent binding policy, and Waypoint
authorization instead of separate toolbox names.

2026-06-27 toolbox bridge smoke: a temporary Foundry toolbox
`prompt-toolbox-smoke-20260627` with `toolbox_search_preview` and `web_search`
was created in the Forge project. Direct MCP calls to the toolbox endpoint
passed: `initialize` and `tools/list` returned `tool_search` and `call_tool`.
A disposable prompt agent using that toolbox endpoint as an MCP tool did reach
the endpoint, but failed auth. Without a project connection the toolbox returned
401. With a `RemoteTool` project connection and full connection ARM ID, both
`user-entra-token` and `project-managed-identity` attempts failed in the
prompt-agent runtime with `ARA OBO token request failed`. The temporary agent,
connection, and toolbox were deleted. Current finding: hosted agents can consume
toolboxes through `TOOLBOX_ENDPOINT`; prompt agents should bind supported tools
directly unless/until Foundry supports toolbox MCP auth as a prompt-agent MCP
tool.

WaypointIQ managed identity should be enabled by granting Waypoint API app roles
to the Foundry project/toolbox identity instead of storing a secret. The target
shape is `auth.type: managed_identity` with
`security_scheme.audience: api://<waypoint-api-client-id>`, plus Entra app-role
assignments for `Waypoint.Read`, `Waypoint.Write`, and only if needed `Waypoint.Admin`.
`Waypoint.Write` should remain limited to explicitly approved write-capable
surfaces until the WaypointIQ write path is proven. If a Waypoint operation
requires delegated user context, managed identity is not sufficient and that
operation needs a delegated-token bridge instead.

2026-06-27 hosted Waypoint MI smoke passed after granting `Waypoint.Read` to
both Forge Foundry managed identities that may be used by toolboxes: the project
MI `ai-account-wi2egf4sh4hfq/projects/ai-project-forge`
(`<foundry-project-resource-id>`) and the parent account MI
`ai-account-wi2egf4sh4hfq` (`<foundry-account-resource-id>`). Hosted
Waypoint `APP_MSAL_ALLOWED_APP_IDS` was updated to include both app IDs. A
temporary toolbox `waypoint-iq-mi-smoke-20260627` successfully called hosted
Waypoint `/api/work` via managed identity and was then deleted; the app-role and
allow-list changes were intentionally left in place.

2026-06-27 durable toolbox creation passed: `waypoint-iq` version 1 now exists
in the Forge Foundry project, created by
`iqs/waypoint-iq/scripts/deploy_toolbox.py` from the curated OpenAPI contract
with the hosted Waypoint server override. The script is idempotent; a second run
reported the toolbox was already up to date. The durable MCP endpoint passed
`initialize`, `tools/list`, `tool_search`, and `call_tool` for
`waypoint_iq___waypointiq_get_work` against hosted Waypoint.

Forge-agent-fleet branch notes:

- The branch carries the source contract and deployment automation for
  `waypoint-iq`; the live Foundry toolbox was created by an explicit data-plane
  script run, not by GitHub Actions or `azd deploy`.
- The deploy script rewrites the OpenAPI server URL at deploy time with
  `--waypoint-endpoint`, so the checked-in `openapi.json` can remain a
  docs-enabled local export while the live toolbox targets hosted Waypoint.
- Keep Assurance Orchestrator and waypoint-recorder hosted. The current safe binding path is hosted
  agent `TOOLBOX_ENDPOINT`; prompt agents should not be wired to the toolbox MCP
  endpoint until the prompt-agent MCP auth gap is resolved.
- Do not grant `Waypoint.Write` broadly. The durable v1 smoke proved read
  authority only; write operations still need a separate governed proof before
  Assurance Orchestrator or waypoint-recorder moves off existing write boundaries.

The same expert naming pattern applies across both the historical prompt-agent
experiment and the current hosted path: experts may have IQ tools attached, but
do not model or name them as "IQ agents" in automation. In the current path,
Assurance Orchestrator calls hosted expert Responses endpoints and consumes the
shared evidence contract.

Assurance Orchestrator still has a historical opt-in prompt-agent expert client:
`ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE=prompt` routes workflow fan-out through the
Foundry project `/openai/v1/responses` API with `agent_reference`. The client
loads `agents/<expert>/prompt.md` with Prompty to resolve the default
`metadata.forge.deployment.prompt.agentName`, and supports
`COLLABORATION_EVIDENCE_EXPERT_AGENT_NAME`, `MARKET_EVIDENCE_EXPERT_AGENT_NAME`,
`CONTRACT_POLICY_EXPERT_AGENT_NAME`, and `OPERATIONS_DATA_EXPERT_AGENT_NAME` overrides for
canary names before same-name cutover.

2026-06-27 canary smoke: Assurance Orchestrator's workflow was run locally with
`ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE=prompt` and the four `*-prompt-canary` agent
name overrides. All four validator lanes completed through
`foundry_prompt_agent`, and the workflow remained read-only with
`side_effects_performed: false`.

2026-06-27 responsibility-name smoke: Assurance Orchestrator's workflow was run locally with
the default responsibility-named prompt agents. All four validator lanes
completed through `foundry_prompt_agent`; `market-evidence-expert`,
`operations-data-expert`, `collaboration-evidence-expert`, and
`contract-policy-expert` were invoked via `agent_reference`. The workflow
remained read-only with `side_effects_performed: false`.

See [`WAYPOINTIQ.md`](WAYPOINTIQ.md) for the proposed tool split and rollout.
````
