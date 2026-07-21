# Caldova Forge

A [Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry) multi-agent starter kit. Deploy hosted agents in containers, manage them from a single repo, and use CI/CD to auto-discover and redeploy on changes.

**Current agents**: assurance-orchestrator (coordinator), assurance-analyst (read-only Q&A/status), collaboration-evidence-expert, market-evidence-expert, contract-policy-expert, operations-data-expert, waypoint-recorder (Waypoint writer)

## Quick Start

### Try an agent locally (2 min)

```bash
cd agents/assurance-orchestrator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
az login
python main.py  # runs on http://localhost:8088/
```

### Create a new agent (1 min)

```bash
make new-agent my-agent
# Then edit: agents/my-agent/main.py, toolbox.py, agent.yaml
git add agents/my-agent azure.yaml
git commit -m "feat: add my-agent"
```

### Deploy to Azure (10 min)

```bash
az login && azd auth login
azd ext install azure.ai.agents
azd env new my-env --location eastus2
azd env set ENABLE_HOSTED_AGENTS true
azd provision
python scripts/create_toolbox.py --agent assurance-orchestrator
azd env set TOOLBOX_MCP_ENDPOINT "<endpoint from above>"
azd deploy assurance-orchestrator
```

## Prerequisites

- Python 3.12+
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Azure CLI (az)](https://learn.microsoft.com/cli/azure/install-azure-cli)
- Docker (for remote builds)
- Azure subscription with **Contributor + User Access Administrator**

## Repo structure

```
agents/
  _template/           # scaffold for new agents
  assurance-orchestrator/             # coordinator: fans out to experts, hands off to waypoint-recorder
  assurance-analyst/                  # read-only Q&A/status, including Teams activity surface
  collaboration-evidence-expert/       # single-plane evidence expert (others: webiq/foundryiq/fabriciq)
  waypoint-recorder/          # the only agent that writes findings to Waypoint
  ...
infra/                 # shared Bicep: Foundry project, ACR, App Insights
scripts/               # create_toolbox.py, discover_agents.py
.github/workflows/     # CI/CD: validate, deploy, evals
```

Each agent runs independently in its own container with its own toolbox. Shared infrastructure (Foundry project, registry) is managed once in `infra/`.

## Common tasks

### Configure the model

Default is `gpt-5-mini`. To change:

```bash
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME gpt-4o-mini
azd provision
azd deploy <agent>
```

### Edit an agent's tools

Open `agents/<name>/toolbox.py`, update the `TOOLBOX` list, and push. Tools update on the next session—no rebuild needed.

### VS Code debugging

1. **Run Task:** "Run <agent> with debugpy"
2. **Run and Debug:** "Attach to <agent>"
3. Open http://localhost:8088/api/messages to test

### Contributing

See [`.github/copilot-instructions.md`](.github/copilot-instructions.md) for detailed dev workflow, branch strategy, and agent architecture patterns.

## CI/CD

**On push to `main`:**
- Discover changed agents
- Build & deploy in parallel
- Run smoke tests

**Manual dispatch:** Use `workflow_dispatch` to target a single agent.

For PR validation (no deploy), see `.github/workflows/validate.yml`.

## More

- **Evals** — Foundry-native contracts live with each agent; reusable datasets,
  graders, and optimization tooling live under `modules/evals`.
- **Publishing to Teams/M365** — Run `make publish <agent>` (see copilot-instructions.md)
- **Advanced model setup** — See `infra/main.bicep`
- **GitHub Actions setup** — Required repo variables in [copilot-instructions.md](.github/copilot-instructions.md)
- **WaypointIQ** — Agent-facing toolbox boundary over Caldova Waypoint, documented in [docs/WAYPOINTIQ.md](docs/WAYPOINTIQ.md)

### Evaluation path

Hosted quality checks use Foundry-native eval contracts such as
`agents/contract-policy-expert/eval.yaml`. Committed golden cases remain under
`evals/cases/`; shared dataset generation, deterministic graders, output-item
export, optimizer planning, and RFT packaging live under `modules/evals`.

## Publishing a hosted agent to Microsoft 365 Copilot + Teams

Once an agent is running on Foundry (Playground chat works), you can surface it inside **Microsoft 365 Copilot** and **Microsoft Teams**. This is the most fragile part of the stack — it spans 4 different Azure/M365 services and several preview APIs. This section documents what's automated, what's manual, and *why* each manual step exists today.

### Prerequisites: Python deps for `make publish`

`make publish` shells out to `python3` directly (not a uv-managed venv), so the
scripts in [`scripts/`](scripts/) need to find `azure-identity`, `requests`,
and `pyyaml` on your interpreter. Run the following command:

```bash
python3 -m venv .venv-publish
source .venv-publish/bin/activate
pip install azure-identity requests pyyaml
# Now `python3` inside this shell is the venv's interpreter, so `make publish` works.
```

You only need to do this once per machine (or per venv).

### What `make publish <agent>` does (and what the CI workflow mirrors)

Running `make publish <agent>` (or the deploy workflow with `publish: true`) chains the following steps. Each one is idempotent and safe to re-run. After the last step it prints a **next-steps banner** with the three manual gates and the exact deep links you need to click — you can re-print it any time with `make next-steps <agent>`.

| # | Step | Script | What it does |
| --- | --- | --- | --- |
| 1 | Patch agent endpoint auth | [`scripts/patch_agent_endpoint.py`](scripts/patch_agent_endpoint.py) | Sets the agent's `activityprotocol` endpoint to `BotServiceRbac`-only auth. Without this, Teams users hit a Foundry login prompt before they can talk to the bot. |
| 2 | Ensure Bot Service + Teams channel | [`scripts/ensure_bot_service.py`](scripts/ensure_bot_service.py) | Creates an Azure Bot whose `msaAppId` is the agent's **`instance_identity` client id** (a ServiceIdentity SP Foundry can mint tokens for). Enables the `MsTeamsChannel`. |
| 3 | Register Foundry application resource | [`scripts/ensure_foundry_application.py`](scripts/ensure_foundry_application.py) | PUTs `Microsoft.CognitiveServices/accounts/projects/applications/<agent>`. This is the **third** ARM op the portal's Publish button does — without it the agent never shows up in the Teams "Built for your org" catalog. |
| 4 | Submit the M365 publish request | [`scripts/publish_agent.py`](scripts/publish_agent.py) | POSTs the undocumented `…/microsoft365/publish` endpoint with `useAgenticUserTemplate=true`, scope `Tenant`, and the agent's blueprint id. Creates a "pending request" in the M365 admin portal. |
| 5 | Grant OAuth2 admin consent on the blueprint SP | [`scripts/grant_blueprint_oauth2.py`](scripts/grant_blueprint_oauth2.py) | Pre-consents the blueprint SP for the APX Messaging Bot API (`AgentData.ReadWrite`) and Prod MCP (Agent Tools) scopes. Without these, the bridge fails to mint tokens when relaying user messages. |
| 6 | Print the next-steps banner | [`scripts/print_publish_next_steps.py`](scripts/print_publish_next_steps.py) | Final terminal output: 3-step banner with the admin-approval URL, the Teams Developer Portal blueprint URL (with the blueprint ID baked in), and the Teams `Apps → Agents for your team → Create instance` flow for end-user hiring. Re-runnable via `make next-steps <agent>`. |

### What still has to be done by hand (and why)

These steps are manual either because they're inherently admin-gated (require human approval) or because there's no API yet. **`make publish` prints all three URLs at the end as a banner**, and `make next-steps <agent>` re-prints it.

| # | Who | Step | Where | Why it's manual |
|---|---|---|---|---|
| 1 | Tenant admin | Approve the M365 publish request | <https://admin.cloud.microsoft/#/agents/all/requested> → *⋮* → **Approve request and activate** | Tenant-scoped publishes require a Global / M365 admin click. There is no admin-bypass API; this is by design. |
| 2 | Maker | Confirm Bot ID == Blueprint ID in the Teams Developer Portal | `https://dev.teams.microsoft.com/tools/agent-blueprint/<blueprint-id>` | The Bot Service is already wired up server-side by `make publish` step 2; this Dev Portal step is metadata confirmation so Teams routes conversations correctly. |
| 3 | End user | Hire the teammate (create an agent instance) | Microsoft Teams → **Apps → Agents for your team** → find the agent → **Create instance** | Hiring is a per-user gesture by design. There is no public Graph API to hire on a user's behalf. |

**AI teammate / Digital Worker activation** additionally requires the **Microsoft 365 Frontier / early access** program enabled on the tenant and per-user Copilot licensing. If your tenant doesn't have it, the teammate surface is hidden even after publish.

**Re-publishing after script changes**: bump `app_version` in `agents/<name>/publish.yaml`. The publish endpoint refuses duplicate-version submissions; `publish_agent.py` tolerates this with a notice but won't push a new revision without a version bump.

<details>
<summary><strong>Identity model — who is who</strong> (click to expand)</summary>

Three Entra identities are involved per agent. Mixing them up is the #1 cause of "agent works in Playground but won't reply in Teams."

| Identity | Where it comes from | What uses it |
| --- | --- | --- |
| **Blueprint SP** (`agent_identity_blueprint.client_id`) | Auto-created by Foundry when the agent is first deployed | The "user-facing" identity Copilot/Teams **sees**. Receives OAuth2 admin consent (step 5 above). Used as `AgentIdentityBlueprintId` in the publish payload. |
| **Instance identity** (`instance_identity.client_id`) | Auto-created per agent version | The Bot Service `msaAppId`. Foundry mints Bot Service Federated Identity Credentials for this SP so the platform can produce bot-tokens. **Immutable** on Bot Service — if you ever create the bot with the wrong msaAppId, you have to delete and wait 7 days for the soft-delete cooldown. |
| **Foundry account managed identity** | The `Microsoft.CognitiveServices/accounts` resource's system-assigned MI | Inbound auth on the agent's `/responses` endpoint. After step 1 above, only this MI (acting through BotServiceRbac) can call the endpoint. |

</details>

<details>
<summary><strong>OAuth2 permissions granted automatically</strong></summary>

[`scripts/grant_blueprint_oauth2.py`](scripts/grant_blueprint_oauth2.py) creates `oauth2PermissionGrants` on the **blueprint SP** for two resource SPs:

- **`f045a6fb-7542-45be-aeae-90e580b40935`** — *Messaging Bot API Application* (APX). Scope: `AgentData.ReadWrite`. Required for the bridge to read/write conversation state on behalf of the agent.
- **`ea29ff32-9494-48cf-830b-9e476cfed98b`** — *Agent Tools* (Prod MCP). Scopes: tool invocation surface used when the agent calls MCP tools through the platform.

All grants are `consentType: AllPrincipals` (admin-consent). The script is idempotent.

</details>

<details>
<summary><strong>Known platform gaps (May 2026)</strong></summary>

These items have no workaround in our code; they need a Microsoft fix.

| Issue | Symptom | Status |
| --- | --- | --- |
| **No streaming / typing indicator in Teams or Copilot chat** | Long silent pause, then the full message appears at once. Foundry Playground streams fine — the gap is in the channel bridge converting Responses SSE → Activity. | Platform-side; bridge does not relay `response.output_text.delta` events as typing/streaming activities. File feedback. |
| **`Publish response did not include a new title id` (UI error)** | Clicking "Publish to store" in the admin portal fails on agents already published via API at the same version. | Bump `app_version` in `publish.yaml` and re-run `make publish <agent>` before clicking the admin UI button. |
| **Soft-delete cooldown on bot names** | Re-creating an Azure Bot with the same name within 7 days of deletion returns a name-conflict error. | Use a different `botName` suffix in [`infra/core/publish/bot-channel.bicep`](infra/core/publish/bot-channel.bicep) or wait out the cooldown. `ensure_bot_service.py` always picks a fresh suffix. |
| **`microsoft365/publish` is undocumented** | Microsoft can change the request/response shape without notice. | Pin `api-version` in `scripts/publish_agent.py`. Watch for `NoRegisteredProviderFound`. |

</details>

<details>
<summary><strong>Verifying after publish</strong> (manual sanity-check commands)</summary>

```bash
# All three ARM resources exist and are Succeeded
az resource list -g $RG --resource-type Microsoft.BotService/botServices -o table
az rest --method get --url "https://management.azure.com/.../applications/<agent>?api-version=2026-01-15-preview"

# Agent records in the Foundry project
az rest --method get --url "https://management.azure.com/.../applications?api-version=2026-01-15-preview"

# OAuth2 grants on the blueprint SP
az ad sp show --id <blueprint_client_id> --query id -o tsv | \
  xargs -I{} az rest --method get \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/{}/oauth2PermissionGrants"
```

If all three of those look right, the agent will appear in Teams within ~30–60 min once a tenant admin clicks **Publish to store** and **Deploy** in the M365 admin center.

</details>
