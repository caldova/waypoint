#!/usr/bin/env bash
# Waypoint web PR previews (Azure Container Apps), in the spirit of Azure Static
# Web Apps / Netlify deploy previews.
#
# Each PR gets its own container app, `web-pr-<number>` (infra/preview/app.bicep),
# in the isolated preview resource group. Previews scale to zero, call the shared
# production API through the web server's /api proxy, and sign in with the
# preview-only Entra app. This script is the imperative glue around the Bicep:
# per-PR redirect URIs on that shared app, image cleanup, and the closed-PR sweep.
#
# Usage: preview_web.sh discover | deploy | destroy | sweep
#
# Required env (all):      PREVIEW_RESOURCE_GROUP
# Required env (deploy):   PR_NUMBER, IMAGE, API_URL,
#                          MSAL_CLIENT_ID, MSAL_TENANT_ID, MSAL_API_SCOPE
# Required env (destroy):  PR_NUMBER (MSAL_CLIENT_ID to also remove redirect URIs)
# Required env (sweep):    GITHUB_REPOSITORY, GH_TOKEN (closed PRs are destroyed)
# Optional env:            GITHUB_REPOSITORY (tags), PREVIEW_READY_TIMEOUT_SECONDS (300)
#
# Outputs (GITHUB_OUTPUT): discover → registry_name, registry_server, environment_domain
#                          deploy   → app_name, fqdn, url
set -euo pipefail

mode="${1:?usage: preview_web.sh discover|deploy|destroy|sweep}"
: "${PREVIEW_RESOURCE_GROUP:?PREVIEW_RESOURCE_GROUP required}"
rg="$PREVIEW_RESOURCE_GROUP"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
app_bicep="${script_dir}/../../../infra/preview/app.bicep"

IMAGE_REPOSITORY="waypoint-web"

log() { echo "preview: $*" >&2; }
emit() { log "$1=$2"; [[ -n "${GITHUB_OUTPUT:-}" ]] && echo "$1=$2" >> "$GITHUB_OUTPUT"; return 0; }

app_name_for() {
  local pr="$1"
  if [[ ! "$pr" =~ ^[0-9]+$ ]]; then
    echo "::error::PR number must be numeric, got '$pr'" >&2
    exit 2
  fi
  echo "web-pr-${pr}"
}

environment_field() {
  az containerapp env list -g "$rg" --query "[0].$1" -o tsv
}

registry_field() {
  az acr list -g "$rg" --query "[0].$1" -o tsv
}

discover() {
  local env_domain registry_name registry_server
  env_domain="$(environment_field properties.defaultDomain)"
  registry_name="$(registry_field name)"
  registry_server="$(registry_field loginServer)"
  if [[ -z "$env_domain" || -z "$registry_name" ]]; then
    echo "::error::Preview environment not found in '$rg'. Run tools/deploy/scripts/preview_setup.sh first." >&2
    exit 1
  fi
  emit registry_name "$registry_name"
  emit registry_server "$registry_server"
  emit environment_domain "$env_domain"
}

wait_until_ready() {
  local url="$1" timeout="${PREVIEW_READY_TIMEOUT_SECONDS:-300}" code="" waited=0
  # Scale-to-zero apps cold start on the first request; keep asking until it answers.
  while (( waited < timeout )); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$url" || true)"
    if [[ "$code" == "200" ]]; then
      log "ready: $url -> $code"
      return 0
    fi
    sleep 10
    waited=$((waited + 10))
  done
  echo "::error::$url did not return 200 within ${timeout}s (last status: ${code:-none})" >&2
  return 1
}

deploy() {
  : "${PR_NUMBER:?PR_NUMBER required}" "${IMAGE:?IMAGE required}" "${API_URL:?API_URL required}"
  : "${MSAL_CLIENT_ID:?MSAL_CLIENT_ID required}" "${MSAL_TENANT_ID:?MSAL_TENANT_ID required}"
  : "${MSAL_API_SCOPE:?MSAL_API_SCOPE required}"
  local name env_domain env_location fqdn url
  name="$(app_name_for "$PR_NUMBER")"
  env_domain="$(environment_field properties.defaultDomain)"
  env_location="$(environment_field location)"
  fqdn="${name}.${env_domain}"
  url="https://${fqdn}"

  # Register sign-in URLs first so the preview works as soon as it answers.
  MSAL_CLIENT_ID="$MSAL_CLIENT_ID" WEB_FQDN="$fqdn" bash "${script_dir}/msal.sh" redirect

  log "deploying $name -> $IMAGE"
  az deployment group create -g "$rg" -n "preview-${name}" -f "$app_bicep" \
    -p prNumber="$PR_NUMBER" image="$IMAGE" registryName="$(registry_field name)" \
       location="$env_location" apiUrl="$API_URL" msalClientId="$MSAL_CLIENT_ID" \
       msalTenantId="$MSAL_TENANT_ID" msalApiScope="$MSAL_API_SCOPE" \
       repository="${GITHUB_REPOSITORY:-}" \
    -o none

  wait_until_ready "${url}/login"
  emit app_name "$name"
  emit fqdn "$fqdn"
  emit url "$url"
}

destroy_pr() {
  local pr="$1" name env_domain registry_name tags_to_delete
  name="$(app_name_for "$pr")"
  env_domain="$(environment_field properties.defaultDomain)"

  if az containerapp show -g "$rg" -n "$name" -o none 2>/dev/null; then
    log "deleting container app $name"
    az containerapp delete -g "$rg" -n "$name" --yes -o none
  else
    log "container app $name not found (already removed)"
  fi

  if [[ -n "${MSAL_CLIENT_ID:-}" && -n "$env_domain" ]]; then
    MSAL_CLIENT_ID="$MSAL_CLIENT_ID" WEB_FQDN="${name}.${env_domain}" bash "${script_dir}/msal.sh" unredirect
  fi

  registry_name="$(registry_field name)"
  if [[ -n "$registry_name" ]]; then
    tags_to_delete="$(az acr repository show-tags -n "$registry_name" --repository "$IMAGE_REPOSITORY" -o tsv 2>/dev/null \
      | grep -E "^pr-${pr}-" || true)"
    for tag in $tags_to_delete; do
      log "deleting image ${IMAGE_REPOSITORY}:${tag}"
      az acr repository delete -n "$registry_name" --image "${IMAGE_REPOSITORY}:${tag}" --yes -o none
    done
  fi
}

sweep() {
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY required}"
  local registry_name pr state prs
  registry_name="$(registry_field name)"
  # Every PR that still has an app or an image, so half-cleaned previews are caught too.
  prs="$(
    {
      az containerapp list -g "$rg" --query "[?tags.\"waypoint-preview\"=='pr'].tags.\"waypoint-pr\"" -o tsv
      if [[ -n "$registry_name" ]]; then
        az acr repository show-tags -n "$registry_name" --repository "$IMAGE_REPOSITORY" -o tsv 2>/dev/null \
          | sed -nE 's/^pr-([0-9]+)-.*/\1/p'
      fi
    } | sort -un
  )"
  for pr in $prs; do
    state="$(gh pr view "$pr" --repo "$GITHUB_REPOSITORY" --json state -q .state 2>/dev/null || echo UNKNOWN)"
    if [[ "$state" == "OPEN" ]]; then
      log "PR #$pr is open; keeping its preview"
    elif [[ "$state" == "UNKNOWN" ]]; then
      log "PR #$pr state unavailable; keeping its preview"
    else
      log "PR #$pr is $state; removing its preview"
      destroy_pr "$pr"
    fi
  done
}

case "$mode" in
  discover) discover ;;
  deploy) deploy ;;
  destroy) destroy_pr "${PR_NUMBER:?PR_NUMBER required}" ;;
  sweep) sweep ;;
  *) echo "::error::unknown mode '$mode' (use discover|deploy|destroy|sweep)" >&2; exit 2 ;;
esac
