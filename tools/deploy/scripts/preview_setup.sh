#!/usr/bin/env bash
# One-time setup for Waypoint web PR previews (.github/workflows/preview-web.yml).
#
# 1. Deploys infra/preview/main.bicep, which declares everything in Azure and
#    Entra: the isolated preview resource group and its resources, the
#    preview-only sign-in app with admin consent, and the OIDC deployer with
#    its Graph permission. Safe to rerun.
# 2. Creates the `preview` GitHub Environment and its variables, which Bicep
#    can't manage.
#
# Inputs are derived from production; this script's own logic is just that
# lookup, the GitHub environment, and --uninstall.
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

# ---- declarative setup ---------------------------------------------------------
# infra/preview/main.bicep declares the resource group, its resources, both app
# registrations, the OIDC credential, admin consent, and the Graph permission.
# The template states the sign-in app's full redirect URI list, so pass in the
# URIs of currently open previews to keep them.
existing_uris="$(az ad app list --filter "displayName eq '${SPA_NAME}'" \
  --query "[?tags && contains(tags, '${APP_TAG}')] | [0].spa.redirectUris" -o json 2>/dev/null || true)"
[[ -z "$existing_uris" || "$existing_uris" == "null" ]] && existing_uris="[]"

log "deploying infra/preview/main.bicep"
deploy_err="$(mktemp)"
if ! outputs="$(az deployment sub create -l "$LOCATION" -n waypoint-preview -f "$BICEP" \
  -p resourceGroupName="$RESOURCE_GROUP" location="$LOCATION" environmentLocation="$ENVIRONMENT_LOCATION" \
     apiAppId="$API_APP_ID" githubOidcSubject="${SUBJECT_PREFIX}:environment:${ENVIRONMENT}" \
     existingRedirectUris="$existing_uris" \
  --query properties.outputs -o json 2>"$deploy_err")"; then
  cat "$deploy_err" >&2
  if grep -q "CapacityHeavyUsage" "$deploy_err"; then
    echo "::error::$ENVIRONMENT_LOCATION has no Container Apps capacity right now. Rerun with --environment-location <region> (for example northeurope)." >&2
  fi
  rm -f "$deploy_err"
  exit 1
fi
rm -f "$deploy_err"
output() { python3 -c 'import json,sys;print(json.loads(sys.argv[1])[sys.argv[2]]["value"])' "$outputs" "$1"; }
DEPLOYER_APP_ID="$(output deployerClientId)"
SPA_APP_ID="$(output previewWebClientId)"

# ---- GitHub environment (Bicep can't manage it) ------------------------------
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
