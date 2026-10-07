#!/usr/bin/env bash
# One-time setup for Waypoint web PR previews (.github/workflows/preview-web.yml).
#
# Creates, look-up-before-write (re-running is a no-op):
#   1. The isolated preview resource group.
#   2. A preview-only Entra SPA app ("waypoint-preview-web") with admin consent to
#      the production API's user_impersonation scope and basic Graph sign-in scopes.
#      Per-PR redirect URIs are added to THIS app, never to the production app.
#   3. A preview deployer app + service principal ("waypoint-preview-deployer") with
#      a GitHub OIDC federated credential for the `preview` environment.
#   4. Graph Application.ReadWrite.OwnedBy for the deployer, plus ownership of the
#      preview SPA app only, so it can manage that app's redirect URIs.
#   5. infra/preview/main.bicep: registry, pull identity, Container Apps environment,
#      and Contributor for the deployer on the preview resource group only.
#   6. The `preview` GitHub Environment and its variables.
#
# `--uninstall` removes all of it again: the GitHub environment, the preview
# resource group (with every PR preview in it), and both app registrations, which
# takes their service principals, OIDC credential, Graph grant, and consent with
# them. It only deletes what this script tagged, and without `--yes` it just
# prints the plan.
#
# Requires: az logged in as a tenant admin who can grant Graph app permissions and
# admin consent (Global Administrator or Privileged Role Administrator) and create
# role assignments on the subscription; gh with admin on the repository.
#
# Defaults are derived from the production `caldova` environment and `waypoint-rg`,
# so a plain `bash tools/deploy/scripts/preview_setup.sh` works for Caldova.
#
# Usage: preview_setup.sh [--repo owner/name] [--resource-group name] [--location region]
#          [--environment-location region] [--api-app-id id] [--api-url url] [--subject-prefix prefix]
#          [--prod-environment name] [--prod-resource-group name] [--dry-run]
#        preview_setup.sh --uninstall [--yes] [--repo owner/name] [--resource-group name]
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-caldova/waypoint}"
RESOURCE_GROUP="waypoint-preview-rg"
ENVIRONMENT="preview"
LOCATION=""
ENVIRONMENT_LOCATION=""
API_APP_ID=""
API_URL=""
SUBJECT_PREFIX=""
PROD_ENVIRONMENT="caldova"
PROD_RESOURCE_GROUP="waypoint-rg"
DRY_RUN="false"
UNINSTALL="false"
YES="false"
SPA_NAME="waypoint-preview-web"
DEPLOYER_NAME="waypoint-preview-deployer"
# Marks what this script owns; --uninstall deletes nothing without these tags.
APP_TAG="waypoint-preview-managed"
RG_TAG_VALUE="environment"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --resource-group) RESOURCE_GROUP="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --environment-location) ENVIRONMENT_LOCATION="$2"; shift 2 ;;
    --api-app-id) API_APP_ID="$2"; shift 2 ;;
    --api-url) API_URL="$2"; shift 2 ;;
    --subject-prefix) SUBJECT_PREFIX="$2"; shift 2 ;;
    --prod-environment) PROD_ENVIRONMENT="$2"; shift 2 ;;
    --prod-resource-group) PROD_RESOURCE_GROUP="$2"; shift 2 ;;
    --dry-run) DRY_RUN="true"; shift ;;
    --uninstall) UNINSTALL="true"; shift ;;
    --yes) YES="true"; shift ;;
    -h|--help) sed -n '2,39p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

GRAPH="https://graph.microsoft.com/v1.0"
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BICEP="${SCRIPT_DIR}/../../../infra/preview/main.bicep"

log() { echo "preview-setup: $*" >&2; }
prod_var() { gh variable get "$1" --env "$PROD_ENVIRONMENT" --repo "$REPO" 2>/dev/null || true; }

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"

# ---- uninstall ---------------------------------------------------------------
if [[ "$UNINSTALL" == "true" ]]; then
  apply="false"
  [[ "$YES" == "true" && "$DRY_RUN" != "true" ]] && apply="true"
  step() { if [[ "$apply" == "true" ]]; then log "removing $*"; else log "would remove $*"; fi; }

  if gh api "repos/${REPO}/environments/${ENVIRONMENT}" --silent 2>/dev/null; then
    step "GitHub environment '${ENVIRONMENT}' and its variables (${REPO})"
    [[ "$apply" == "true" ]] && gh api -X DELETE "repos/${REPO}/environments/${ENVIRONMENT}" --silent
  fi

  if az group show -n "$RESOURCE_GROUP" -o none 2>/dev/null; then
    rg_tag="$(az group show -n "$RESOURCE_GROUP" --query 'tags."waypoint-preview"' -o tsv)"
    if [[ "$rg_tag" == "$RG_TAG_VALUE" ]]; then
      step "resource group ${RESOURCE_GROUP} and every PR preview in it"
      [[ "$apply" == "true" ]] && az group delete -n "$RESOURCE_GROUP" --yes
    else
      log "skipping resource group ${RESOURCE_GROUP}: not tagged waypoint-preview=${RG_TAG_VALUE}"
    fi
  fi

  for app_name in "$DEPLOYER_NAME" "$SPA_NAME"; do
    for app_id in $(az ad app list --filter "displayName eq '${app_name}'" \
      --query "[?tags && contains(tags, '${APP_TAG}')].appId" -o tsv); do
      step "app registration ${app_name} (${app_id}) with its service principal, credentials, and grants"
      [[ "$apply" == "true" ]] && az ad app delete --id "$app_id"
    done
    untagged="$(az ad app list --filter "displayName eq '${app_name}'" \
      --query "length([?!(tags && contains(tags, '${APP_TAG}'))])" -o tsv)"
    if [[ "$untagged" != "0" ]]; then
      log "skipping ${untagged} '${app_name}' app registration(s) without the ${APP_TAG} tag"
    fi
  done

  if [[ "$apply" == "true" ]]; then
    log "uninstall complete (deleted app registrations stay restorable in Entra for 30 days)"
  else
    log "plan only: rerun with --uninstall --yes to remove these"
  fi
  exit 0
fi

# ---- resolve defaults from production ---------------------------------------
if [[ -z "$LOCATION" ]]; then
  LOCATION="$(az group show -n "$RESOURCE_GROUP" --query location -o tsv 2>/dev/null \
    || az group show -n "$PROD_RESOURCE_GROUP" --query location -o tsv)"
fi
[[ -z "$API_APP_ID" ]] && API_APP_ID="$(prod_var WAYPOINT_MSAL_CLIENT_ID)"
if [[ -z "$API_URL" ]]; then
  API_URL="$(az containerapp show -g "$PROD_RESOURCE_GROUP" -n web \
    --query "properties.template.containers[0].env[?name=='API_ENDPOINT_HTTP'].value | [0]" -o tsv 2>/dev/null || true)"
fi
if [[ -z "$SUBJECT_PREFIX" ]]; then
  # Match the subject format GitHub issues for this repository (it can include
  # owner/repo IDs) by reusing the production deploy identity's subject.
  prod_client_id="$(prod_var AZURE_CLIENT_ID)"
  if [[ -n "$prod_client_id" ]]; then
    SUBJECT_PREFIX="$(az ad app federated-credential list --id "$prod_client_id" \
      --query "[?contains(subject, ':environment:')].subject | [0]" -o tsv 2>/dev/null | sed -E 's/:environment:.*$//' || true)"
  fi
  [[ -z "$SUBJECT_PREFIX" ]] && SUBJECT_PREFIX="repo:${REPO}"
fi
: "${LOCATION:?--location is required}" "${API_APP_ID:?--api-app-id is required}" "${API_URL:?--api-url is required}"
[[ -z "$ENVIRONMENT_LOCATION" ]] && ENVIRONMENT_LOCATION="$LOCATION"
API_SCOPE="api://${API_APP_ID}/user_impersonation"

log "repository:      $REPO (environment '$ENVIRONMENT')"
log "subscription:    $SUBSCRIPTION_ID (tenant $TENANT_ID)"
log "resource group:  $RESOURCE_GROUP ($LOCATION; Container Apps environment in $ENVIRONMENT_LOCATION)"
log "production API:  $API_URL (scope $API_SCOPE)"
log "OIDC subject:    ${SUBJECT_PREFIX}:environment:${ENVIRONMENT}"
if [[ "$DRY_RUN" == "true" ]]; then
  log "dry run: no changes made"
  exit 0
fi

ensure_app() {
  local name="$1" app_id obj_id tags
  app_id="$(az ad app list --filter "displayName eq '${name}'" --query "[0].appId" -o tsv)"
  if [[ -z "$app_id" ]]; then
    log "creating app registration $name"
    app_id="$(az ad app create --display-name "$name" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
  fi
  obj_id="$(az ad app show --id "$app_id" --query id -o tsv)"
  tags="$(az ad app show --id "$app_id" --query tags -o json)"
  if [[ "$tags" != *"\"${APP_TAG}\""* ]]; then
    tags="$(python3 -c 'import json,sys;print(json.dumps({"tags":sorted(set(json.loads(sys.argv[1] or "[]") or [])|{sys.argv[2]})}))' "$tags" "$APP_TAG")"
    az rest --method PATCH --uri "${GRAPH}/applications/${obj_id}" --headers "Content-Type=application/json" --body "$tags" -o none
  fi
  az ad sp show --id "$app_id" -o none 2>/dev/null || az ad sp create --id "$app_id" -o none
  echo "$app_id"
}

sp_object_id() { az ad sp show --id "$1" --query id -o tsv; }
scope_id() { az ad sp show --id "$1" --query "oauth2PermissionScopes[?value=='$2'].id | [0]" -o tsv; }

ensure_consent() {
  local client_sp="$1" resource_sp="$2" scope="$3" grant
  grant="$(az rest --method GET \
    --uri "${GRAPH}/oauth2PermissionGrants?\$filter=clientId eq '${client_sp}' and resourceId eq '${resource_sp}' and consentType eq 'AllPrincipals'" \
    --query "value[0].{id:id, scope:scope}" -o json)"
  if [[ "$grant" == "null" || -z "$grant" ]]; then
    log "granting admin consent: $scope"
    az rest --method POST --uri "${GRAPH}/oauth2PermissionGrants" --headers "Content-Type=application/json" \
      --body "{\"clientId\":\"${client_sp}\",\"consentType\":\"AllPrincipals\",\"resourceId\":\"${resource_sp}\",\"scope\":\"${scope}\"}" -o none
  else
    local id existing merged
    id="$(echo "$grant" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
    existing="$(echo "$grant" | python3 -c 'import json,sys;print(json.load(sys.stdin)["scope"] or "")')"
    merged="$(python3 -c 'import sys;print(" ".join(sorted(set(sys.argv[1].split()) | set(sys.argv[2].split()))))' "$existing" "$scope")"
    if [[ "$merged" != "$(python3 -c 'import sys;print(" ".join(sorted(sys.argv[1].split())))' "$existing")" ]]; then
      log "updating admin consent: $merged"
      az rest --method PATCH --uri "${GRAPH}/oauth2PermissionGrants/${id}" --headers "Content-Type=application/json" \
        --body "{\"scope\":\"${merged}\"}" -o none
    fi
  fi
}

# ---- 1. resource group -------------------------------------------------------
az group show -n "$RESOURCE_GROUP" -o none 2>/dev/null \
  || az group create -n "$RESOURCE_GROUP" -l "$LOCATION" --tags "waypoint-preview=${RG_TAG_VALUE}" -o none

# ---- 2. preview-only sign-in app ---------------------------------------------
SPA_APP_ID="$(ensure_app "$SPA_NAME")"
SPA_OBJ_ID="$(az ad app show --id "$SPA_APP_ID" --query id -o tsv)"
SPA_SP_ID="$(sp_object_id "$SPA_APP_ID")"
API_SP_ID="$(sp_object_id "$API_APP_ID")"
GRAPH_SP_ID="$(sp_object_id "$GRAPH_APP_ID")"
API_SCOPE_ID="$(scope_id "$API_APP_ID" user_impersonation)"
access="$(python3 - "$API_APP_ID" "$API_SCOPE_ID" "$GRAPH_APP_ID" \
  "$(scope_id "$GRAPH_APP_ID" User.Read)" "$(scope_id "$GRAPH_APP_ID" openid)" \
  "$(scope_id "$GRAPH_APP_ID" profile)" "$(scope_id "$GRAPH_APP_ID" offline_access)" <<'PY'
import json, sys
api_app, api_scope, graph_app, *graph_scopes = sys.argv[1:]
print(json.dumps({"requiredResourceAccess": [
    {"resourceAppId": api_app, "resourceAccess": [{"id": api_scope, "type": "Scope"}]},
    {"resourceAppId": graph_app, "resourceAccess": [{"id": s, "type": "Scope"} for s in graph_scopes]},
]}))
PY
)"
az rest --method PATCH --uri "${GRAPH}/applications/${SPA_OBJ_ID}" --headers "Content-Type=application/json" --body "$access" -o none
ensure_consent "$SPA_SP_ID" "$API_SP_ID" "user_impersonation"
ensure_consent "$SPA_SP_ID" "$GRAPH_SP_ID" "User.Read openid profile offline_access"

# ---- 3. preview deployer + OIDC ----------------------------------------------
DEPLOYER_APP_ID="$(ensure_app "$DEPLOYER_NAME")"
DEPLOYER_SP_ID="$(sp_object_id "$DEPLOYER_APP_ID")"
owner="${REPO%%/*}"; name="${REPO##*/}"
cred_name="github-${owner}-${name}-env-${ENVIRONMENT}"
subject="${SUBJECT_PREFIX}:environment:${ENVIRONMENT}"
current="$(az ad app federated-credential list --id "$DEPLOYER_APP_ID" --query "[?name=='${cred_name}'].subject | [0]" -o tsv)"
if [[ "$current" != "$subject" ]]; then
  [[ -n "$current" ]] && az ad app federated-credential delete --id "$DEPLOYER_APP_ID" --federated-credential-id "$cred_name"
  log "adding federated credential $subject"
  az ad app federated-credential create --id "$DEPLOYER_APP_ID" --parameters "{
    \"name\": \"${cred_name}\",
    \"issuer\": \"https://token.actions.githubusercontent.com\",
    \"subject\": \"${subject}\",
    \"audiences\": [\"api://AzureADTokenExchange\"],
    \"description\": \"Waypoint web PR previews for ${REPO}\"
  }" -o none
fi

# ---- 4. Graph: manage only the preview sign-in app ---------------------------
owned_by_role="$(az ad sp show --id "$GRAPH_APP_ID" --query "appRoles[?value=='Application.ReadWrite.OwnedBy'].id | [0]" -o tsv)"
has_role="$(az rest --method GET --uri "${GRAPH}/servicePrincipals/${DEPLOYER_SP_ID}/appRoleAssignments" \
  --query "length(value[?appRoleId=='${owned_by_role}'])" -o tsv)"
if [[ "$has_role" == "0" ]]; then
  log "granting Graph Application.ReadWrite.OwnedBy to the deployer"
  az rest --method POST --uri "${GRAPH}/servicePrincipals/${DEPLOYER_SP_ID}/appRoleAssignments" \
    --headers "Content-Type=application/json" \
    --body "{\"principalId\":\"${DEPLOYER_SP_ID}\",\"resourceId\":\"${GRAPH_SP_ID}\",\"appRoleId\":\"${owned_by_role}\"}" -o none
fi
if [[ "$(az ad app owner list --id "$SPA_APP_ID" --query "length([?id=='${DEPLOYER_SP_ID}'])" -o tsv)" == "0" ]]; then
  log "making the deployer an owner of $SPA_NAME"
  az ad app owner add --id "$SPA_APP_ID" --owner-object-id "$DEPLOYER_SP_ID"
fi

# ---- 5. preview infrastructure -----------------------------------------------
log "deploying infra/preview/main.bicep"
if ! deploy_output="$(az deployment group create -g "$RESOURCE_GROUP" -n waypoint-preview -f "$BICEP" \
  -p deployerPrincipalId="$DEPLOYER_SP_ID" location="$LOCATION" environmentLocation="$ENVIRONMENT_LOCATION" \
  -o none 2>&1)"; then
  echo "$deploy_output" >&2
  if [[ "$deploy_output" == *"CapacityHeavyUsage"* ]]; then
    echo "::error::$ENVIRONMENT_LOCATION has no Container Apps capacity right now. Rerun with --environment-location <region> (for example northeurope); the existing resources stay where they are." >&2
  fi
  exit 1
fi

# ---- 6. GitHub environment ---------------------------------------------------
gh api -X PUT "repos/${REPO}/environments/${ENVIRONMENT}" --silent
set_var() { gh variable set "$1" --env "$ENVIRONMENT" --repo "$REPO" --body "$2"; }
set_var AZURE_CLIENT_ID "$DEPLOYER_APP_ID"
set_var AZURE_TENANT_ID "$TENANT_ID"
set_var AZURE_SUBSCRIPTION_ID "$SUBSCRIPTION_ID"
set_var PREVIEW_RESOURCE_GROUP "$RESOURCE_GROUP"
set_var PREVIEW_MSAL_CLIENT_ID "$SPA_APP_ID"
set_var WAYPOINT_MSAL_TENANT_ID "$TENANT_ID"
set_var WAYPOINT_MSAL_API_SCOPE "$API_SCOPE"
set_var WAYPOINT_PREVIEW_API_URL "$API_URL"

log "done: PRs that change apps/waypoint/web now get a preview."
