# waypoint-iq

`waypoint-iq` is the agent-facing tool contract for Caldova Waypoint. It is not
an agent. It is the stable IQ capability surface that Forge agents can consume
locally and publish as an actual Foundry toolbox resource.

The contract is endpoint-parameterized so the same surface can target local
Waypoint during confidence runs and hosted Waypoint in Foundry:

```powershell
$env:WAYPOINT_IQ_ENDPOINT = "https://localhost:62595"
```

## Current shape

| File | Purpose |
| --- | --- |
| `openapi.json` | Curated WaypointIQ OpenAPI contract exported from a docs-enabled Waypoint API. |
| `toolbox.yaml` | Draft source payload for an actual Foundry toolbox named `waypoint-iq`; this file is not itself the live toolbox. |
| `scripts/export_openapi.py` | Fetches Waypoint `/openapi.json`, keeps the curated read/write/admin operations, rewrites operation IDs, and pins the target server URL. |
| `scripts/deploy_toolbox.py` | Idempotently creates the real Foundry `waypoint-iq` toolbox, or publishes a new default version only when the desired payload changes. |
| `tests/smoke_local.py` | Local smoke that verifies the selected endpoint exposes the generated contract and representative read paths. |

## Export from local Waypoint

When Waypoint Aspire is running locally with API docs enabled:

```powershell
python waypoint-iq\scripts\export_openapi.py `
  --endpoint $env:WAYPOINT_IQ_ENDPOINT `
  --allow-insecure-localhost
```

The exporter writes `waypoint-iq/openapi.json`.

## Local smoke

```powershell
python waypoint-iq\tests\smoke_local.py `
  --endpoint $env:WAYPOINT_IQ_ENDPOINT `
  --allow-insecure-localhost
```

The local smoke intentionally exercises read paths only. Write and admin
operations are present in the contract so the complete WaypointIQ shape can be
reviewed, but write execution should remain behind explicit workflow tests and
Waypoint-side authorization.

## Foundry toolbox construct

Foundry toolboxes are real project resources with immutable versions and an MCP
endpoint:

```text
{project_endpoint}/toolboxes/{toolbox_name}/mcp?api-version=v1
```

For hosted agents, the runtime should receive that endpoint through
`TOOLBOX_ENDPOINT`. The `toolbox.yaml` in this folder is only the declarative
source we can use to create or update the real toolbox through Foundry Toolkit,
Foundry Portal, or `azd` toolbox resources once the target Waypoint endpoint is
reachable from Foundry. Do not publish the localhost server URL as a hosted
toolbox target.

## Auth posture

Waypoint accepts Entra tokens, but the important distinction is token type:

- delegated user tokens are required when Waypoint must act as a signed-in user;
- managed identity/app-only tokens can work only if Waypoint grants app roles to
  that service principal;
- local development can use loopback local auth or explicit dev headers.

Do not assume Foundry managed identity is sufficient until Waypoint app-role
authorization is proven for the target environment.

## Deploy the Foundry toolbox

After the hosted Waypoint endpoint is reachable from Foundry and the Forge
managed identities have Waypoint app roles:

```powershell
python waypoint-iq\scripts\deploy_toolbox.py `
  --project-endpoint $env:AZURE_AI_PROJECT_ENDPOINT `
  --waypoint-endpoint https://api.grayflower-2758f17b.swedencentral.azurecontainerapps.io
```

The script is idempotent: it creates `waypoint-iq` if missing, prints no-op when
the current default version already matches, and publishes a new immutable
version only when the desired payload changes. Use `--dry-run` to compare
without writing.

Live Forge status: `waypoint-iq` version 1 exists in the Forge Foundry project
and targets hosted Waypoint. Its MCP endpoint is:

```text
https://ai-account-wi2egf4sh4hfq.services.ai.azure.com/api/projects/ai-project-forge/toolboxes/waypoint-iq/versions/1/mcp?api-version=v1
```
