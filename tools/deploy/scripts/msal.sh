#!/usr/bin/env bash
# MSAL / Entra app-registration ensure for the keystone one-click deploy (ZERO manual config).
#
# Two passes (the web FQDN is only known AFTER waypoint-deploy):
#   ensure   — create-if-missing the "waypoint" API app reg (read-if-exists), ensure the
#              identifier uri + the three app roles Waypoint.Read/Write/Admin (live discovery
#              showed appRoles EMPTY in caldova, so this adds them), and emit the MSAL
#              identity values for the waypoint-deploy inputs.
#   redirect — union the deployed web FQDN into the app's SPA redirect URIs (idempotent).
#
# Everything is look-up-before-write so a re-run against an already-correct app is a no-op.
# Uses Microsoft Graph via `az rest` for the app-roles / SPA-redirect patches.
#
# Usage: msal.sh ensure | msal.sh redirect
# Required env (ensure):   AZURE_TENANT_ID
# Optional env (ensure):   MSAL_CLIENT_ID (from discover; else looked up / created),
#                          MSAL_DISPLAY_NAME (default "waypoint"),
#                          MSAL_ALLOWED_APP_IDS (default "")
# Required env (redirect): MSAL_CLIENT_ID, WEB_FQDN
set -euo pipefail

mode="${1:?usage: msal.sh ensure|redirect}"
display_name="${MSAL_DISPLAY_NAME:-waypoint}"
graph="https://graph.microsoft.com/v1.0"
retry_delay_seconds="${MSAL_GRAPH_RETRY_DELAY_SECONDS:-5}"

log() { echo "msal: $*" >&2; }
emit() { log "$1=$2"; [[ -n "${GITHUB_OUTPUT:-}" ]] && echo "$1=$2" >> "$GITHUB_OUTPUT"; return 0; }

graph_patch() {
  local uri="$1"
  local body="$2"
  local output=""
  for attempt in {1..12}; do
    if output="$(az rest --method PATCH --uri "$uri" \
      --headers "Content-Type=application/json" --body "$body" -o none 2>&1)"; then
      return 0
    fi
    if [[ "$output" != *"Request_ResourceNotFound"* \
      && "$output" != *"does not exist or one of its queried reference-property objects are not present"* \
      || "$attempt" -eq 12 ]]; then
      echo "$output" >&2
      return 1
    fi
    log "Graph application is not yet writable (attempt $attempt/12); retrying"
    sleep "$retry_delay_seconds"
  done
}

# Resolve the app's appId (client id) + objectId, creating the app if absent (ensure mode).
resolve_app() {
  local app_id="${MSAL_CLIENT_ID:-}"
  if [[ -z "$app_id" ]]; then
    app_id="$(az ad app list --filter "displayName eq '${display_name}'" --query "[0].appId" -o tsv 2>/dev/null || true)"
  fi
  if [[ -z "$app_id" || "$app_id" == "None" ]]; then
    if [[ "$mode" == "ensure" ]]; then
      log "no '$display_name' app found — creating"
      app_id="$(az ad app create --display-name "$display_name" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
    else
      echo "::error::MSAL app '$display_name' not found (run ensure first)" >&2; exit 1
    fi
  fi
  APP_ID="$app_id"
  OBJ_ID=""
  for attempt in {1..12}; do
    OBJ_ID="$(az ad app show --id "$app_id" --query id -o tsv 2>/dev/null || true)"
    if [[ -n "$OBJ_ID" && "$OBJ_ID" != "None" ]]; then
      break
    fi
    if [[ "$attempt" -eq 12 ]]; then
      echo "::error::MSAL app '$display_name' did not become readable after creation" >&2
      exit 1
    fi
    sleep 5
  done
}

if [[ "$mode" == "ensure" ]]; then
  : "${AZURE_TENANT_ID:?AZURE_TENANT_ID required}"
  resolve_app
  log "app '$display_name' appId=$APP_ID objId=$OBJ_ID"

  # Establish teardown ownership before any later create-time operation can
  # fail, so an interrupted clean start never leaves an unowned orphan.
  ownership_app="$(
    az rest \
      --method GET \
      --uri "${graph}/applications/${OBJ_ID}" \
      --query '{tags:tags}' \
      --output json 2>/dev/null || echo '{}'
  )"
  managed_tags="$(AZD_ENV="${AZD_ENV_NAME:-contract-agents}" REPO="${GITHUB_REPOSITORY:-}" python3 - "$ownership_app" <<'PY'
import json, os, sys
app = json.loads(sys.argv[1] or "{}")
tags = set(app.get("tags") or [])
tags.update({"waypoint-managed", f"waypoint-environment={os.environ['AZD_ENV']}"})
if os.environ["REPO"]:
    tags.add(f"waypoint-repository={os.environ['REPO']}")
print(json.dumps({"tags": sorted(tags)}))
PY
)"
  log "ensuring teardown ownership tags for ${AZD_ENV_NAME:-contract-agents}"
  graph_patch "${graph}/applications/${OBJ_ID}" "$managed_tags"

  # `az ad app create` creates only the application object. A clean tenant also
  # needs its service principal before the SPA can authenticate.
  if ! az ad sp show --id "$APP_ID" -o none 2>/dev/null; then
    service_principal_ready=false
    for attempt in {1..12}; do
      if output="$(az ad sp create --id "$APP_ID" -o none 2>&1)"; then
        service_principal_ready=true
        break
      fi
      if [[ "$output" != *"Request_ResourceNotFound"* || "$attempt" -eq 12 ]]; then
        echo "$output" >&2
        exit 1
      fi
      log "Graph application is not yet ready for service-principal creation (attempt $attempt/12); retrying"
      sleep "$retry_delay_seconds"
    done
    if [[ "$service_principal_ready" != "true" ]]; then
      echo "::error::MSAL service principal did not become creatable after app registration" >&2
      exit 1
    fi
  fi

  # Ensure the identifier uri api://<appId>.
  id_uri="api://${APP_ID}"
  current_uris="$(az ad app show --id "$APP_ID" --query "identifierUris" -o json 2>/dev/null || echo '[]')"
  if ! echo "$current_uris" | grep -q "$id_uri"; then
    log "setting identifier uri $id_uri"
    identifier_body="$(python3 - "$id_uri" <<'PY'
import json, sys
print(json.dumps({"identifierUris": [sys.argv[1]]}))
PY
)"
    graph_patch "${graph}/applications/${OBJ_ID}" "$identifier_body"
  fi

  # Ensure delegated API scopes before app roles. A newly created app has no
  # oauth2PermissionScopes, so the SPA cannot request its access token until
  # these are explicitly exposed.
  existing_app="$(az rest --method GET --uri "${graph}/applications/${OBJ_ID}" --query '{appRoles:appRoles, scopes:api.oauth2PermissionScopes, tags:tags}' -o json 2>/dev/null || echo '{}')"
  merged_scopes="$(python3 - "$existing_app" <<'PY'
import json, sys, uuid

app = json.loads(sys.argv[1] or "{}")
existing = app.get("scopes") or []
have = {scope.get("value") for scope in existing}
role_values = {role.get("value") for role in (app.get("appRoles") or [])}
want = [
    (
        "user_impersonation",
        "Access Waypoint as the signed-in user",
        "Allow the application to access Waypoint on your behalf.",
    ),
]
for value, display_name, description in want:
    if value in have or value in role_values:
        continue
    existing.append({
        "adminConsentDescription": description,
        "adminConsentDisplayName": display_name,
        "id": str(uuid.uuid4()),
        "isEnabled": True,
        "type": "User",
        "userConsentDescription": description,
        "userConsentDisplayName": display_name,
        "value": value,
    })
    have.add(value)
print(json.dumps({
    "api": {
        "oauth2PermissionScopes": existing,
        "requestedAccessTokenVersion": 2,
    }
}))
PY
)"
  log "ensuring delegated scope (user_impersonation)"
  graph_patch "${graph}/applications/${OBJ_ID}" "$merged_scopes"
  scope_ready=false
  for attempt in {1..12}; do
    scope_count="$(
      az rest \
        --method GET \
        --uri "${graph}/applications/${OBJ_ID}" \
        --query "length(api.oauth2PermissionScopes[?value == 'user_impersonation'])" \
        --output tsv 2>/dev/null || true
    )"
    if [[ "$scope_count" == "1" ]]; then
      scope_ready=true
      break
    fi
    [[ "$attempt" -lt 12 ]] && sleep "$retry_delay_seconds"
  done
  if [[ "$scope_ready" != "true" ]]; then
    echo "::error::MSAL delegated scope user_impersonation did not persist after Graph update" >&2
    exit 1
  fi

  # Ensure the three app roles (merge: keep existing by value, append any missing).
  writer_role="${MSAL_WRITER_APP_ROLE:-Waypoint.Write}"
  reader_role="${MSAL_READER_APP_ROLE:-Waypoint.Read}"
  admin_role="${MSAL_ADMIN_APP_ROLE:-Waypoint.Admin}"
  existing_app="$(az rest --method GET --uri "${graph}/applications/${OBJ_ID}" --query '{appRoles:appRoles, scopes:api.oauth2PermissionScopes, tags:tags}' -o json 2>/dev/null || echo '{}')"
  merged_roles="$(MSAL_W="$writer_role" MSAL_R="$reader_role" MSAL_A="$admin_role" python3 - "$existing_app" <<'PY'
import json, os, sys, uuid
app = json.loads(sys.argv[1] or "{}")
existing = app.get("appRoles") or []
# Microsoft Graph forbids an appRole `value` that collides with an oauth2PermissionScope
# `value` on the SAME app (DuplicateValue). The waypoint app already exposes a
# `Waypoint.Admin` delegated scope, so that role is skipped here and stays a scope-only
# path (agents use x-api-key; the app-only admin role is unused in the demo).
scope_values = {s.get("value") for s in (app.get("scopes") or [])}
have = {r.get("value") for r in existing}
want = [(os.environ["MSAL_W"], "Write access for Waypoint agents/users"),
        (os.environ["MSAL_R"], "Read access for Waypoint agents/users"),
        (os.environ["MSAL_A"], "Admin access for Waypoint seed/import")]
for value, desc in want:
    if value in have or value in scope_values:
        continue
    existing.append({
        "allowedMemberTypes": ["User", "Application"],
        "description": desc,
        "displayName": value,
        "id": str(uuid.uuid4()),
        "isEnabled": True,
        "value": value,
    })
    have.add(value)
print(json.dumps({"appRoles": existing}))
PY
)"
  added="$(echo "$merged_roles" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["appRoles"]))')"
  log "ensuring app roles ($writer_role/$reader_role/$admin_role); total roles now=$added"
  graph_patch "${graph}/applications/${OBJ_ID}" "$merged_roles"

  emit msal_tenant_id "$AZURE_TENANT_ID"
  emit msal_client_id "$APP_ID"
  emit msal_writer_app_role "$writer_role"
  emit msal_reader_app_role "$reader_role"
  emit msal_admin_app_role "$admin_role"
  emit msal_allowed_app_ids "${MSAL_ALLOWED_APP_IDS:-}"
  emit api_app_id_uri "$id_uri"
  emit api_default_scope "${id_uri}/.default"
  log "ensure complete"

elif [[ "$mode" == "redirect" ]]; then
  : "${WEB_FQDN:?WEB_FQDN required}"
  resolve_app
  cb="https://${WEB_FQDN}/auth/msal/callback"
  login="https://${WEB_FQDN}/login"
  existing_spa="$(az rest --method GET --uri "${graph}/applications/${OBJ_ID}" --query "spa.redirectUris" -o json 2>/dev/null || echo '[]')"
  body="$(CB="$cb" LOGIN="$login" python3 - "$existing_spa" <<'PY'
import json, os, sys
uris = set(json.loads(sys.argv[1] or "[]"))
before = set(uris)
uris.add(os.environ["CB"]); uris.add(os.environ["LOGIN"])
print(json.dumps({"spa": {"redirectUris": sorted(uris)}, "_changed": uris != before}))
PY
)"
  changed="$(echo "$body" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("_changed"))')"
  patch="$(echo "$body" | python3 -c 'import json,sys;d=json.load(sys.stdin);d.pop("_changed",None);print(json.dumps(d))')"
  if [[ "$changed" == "True" ]]; then
    log "adding SPA redirect URIs for web FQDN $WEB_FQDN"
    graph_patch "${graph}/applications/${OBJ_ID}" "$patch"
  else
    log "SPA redirect URIs already include $WEB_FQDN (no-op)"
  fi
  emit msal_redirect_uri "$cb"
  log "redirect complete"
else
  echo "::error::unknown mode '$mode' (use ensure|redirect)" >&2; exit 2
fi
