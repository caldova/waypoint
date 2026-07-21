---
name: waypoint-setup-deploy
description: "Open the guided Waypoint admin preflight and one-click setup/deploy canvas. Use when the user says 'preflight this environment', 'check admin readiness', 'run admin preflight', 'guided setup and deploy', 'bootstrap Waypoint', 'set up Waypoint on a new subscription/tenant', or asks to deploy Waypoint end to end without hand-typing az/gh commands."
license: MIT
metadata:
  author: Caldova
  version: "1.0.0"
---

# Waypoint guided setup + deploy

Open the committed canvas with exactly four inputs — everything else (resource
group, Key Vault, Postgres server, Fabric capacity/workspace/lakehouse, azd env
name, etc.) is derived deterministically from them:

- `canvasId`: `waypoint-setup-deploy`
- `instanceId`: pick a stable per-attempt handle (e.g. `waypoint-setup-<repo>`)
- `input`:
  ```json
  {
    "subscriptionId": "<Azure subscription GUID>",
    "tenantId": "<Entra tenant GUID>",
    "region": "<Azure region, e.g. swedencentral>",
    "targetRepo": "<owner/name of the GitHub repo to deploy>"
  }
  ```

If the canvas is not registered, call `extensions_reload`, confirm
`project:waypoint-setup-deploy` is ready, and open it again.

## What it does

The canvas has four actions. `preflight` and `refresh` are read-only.
`bootstrap` and `deploy` mutate real infrastructure/GitHub state and always
require an explicit `confirm: true` — enforced at the JSON-schema level
(`{ "confirm": { "const": true } }`) so a missing or wrong-typed confirmation
is rejected before the handler ever runs, and again inside the underlying
Python helper. There is no way to trigger a mutating action without an
explicit confirmation step in the UI or an explicit `confirm: true` in the
action call.

1. **preflight** — runs `tools/deploy/scripts/admin_preflight.py`, a read-only
   check covering:
   - Azure CLI and GitHub CLI authentication
   - signed-in tenant/subscription match against the requested ones
   - repository admin access and OIDC/repo-variable write access
   - required Azure resource providers registered
   - ability to create RBAC role assignments
   - Microsoft Graph admin-consent boundary (can the signed-in principal grant
     consent, or does someone else need to?)
   - Foundry model availability/quota in the target region
   - Fabric capacity/permissions

   Every check reports `pass`, `warn`, or `fail` with a specific remediation
   string when it isn't a clean pass.

2. **bootstrap** (mutating, needs `confirm: true`) — runs the existing
   idempotent `tools/deploy/scripts/oidc.sh` to establish Azure OIDC trust and
   set the GitHub repo variables/secrets `deploy.yml` needs. Safe to re-run.

3. **deploy** (mutating, needs `confirm: true`) — dispatches
   `.github/workflows/deploy.yml` with the derived deterministic names and
   locates the newly created run (bounded polling, does not wait for
   completion).

4. **refresh** (read-only) — polls the dispatched run's status and re-reads
   the app/API links that the deploy workflow records as resource-group tags.

## Safety model

- Every external command (`az`, `gh`, `bash tools/deploy/scripts/oidc.sh`) is
  built as an argument array and executed via `execFile`/`subprocess` — never
  a shell string, so there is no shell-injection surface even with hostile
  input in a single field.
- No secrets or tokens are ever returned to the canvas or displayed; only
  status booleans, resource names, and public URLs.
- Durable state (config, derived names, last preflight/bootstrap/deploy/links)
  is stored in the session workspace (or a repo-independent user location as a
  fallback), keyed by a hash of subscription+tenant+region+repo — never by the
  transient canvas `instanceId` — so reopening the canvas for the same target
  rehydrates the same state.

## When NOT to use this

Do not hand-run `az`/`gh`/`oidc.sh` yourself when this canvas is available —
it exists specifically so admin/OIDC bootstrapping and deploy dispatch happen
through one auditable, confirmation-gated surface. Do not bypass a `fail`
preflight check by guessing a workaround; surface the remediation text to the
user and let them resolve it (or explicitly accept the risk) before running
`bootstrap` or `deploy`.
