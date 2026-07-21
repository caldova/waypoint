#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------------------
# Azure OIDC bootstrap for GitHub Actions (keystone umbrella)
#
# Mirrors caldova/waypoint scripts/oidc.sh, adapted for the keystone orchestrator.
# Ensures the GitHub repo can `az login` with OIDC (no stored client secrets) so the
# one-click deploy workflow can provision Azure AND call the waypoint/forge/ledgerfield
# reusable workflows.
#
# It is idempotent: re-running never duplicates the app, SP, federated credentials, or
# role assignments. It LOOKS UP before it CREATES, so running it against the already
# configured shared app (forge-gha-oidc) is a no-op.
#
# What it ensures:
#   - An Entra app registration + service principal (default: the SHARED forge-gha-oidc
#     app, which already has Contributor + User Access Administrator on the subscription).
#   - Federated credential for the deploy branch (default: main).
#   - (optional, default ON) a `pull_request` federated credential so PR runs can reach
#     Azure for the read-only preflight what-if.
#   - Subscription role assignments (default: Contributor + User Access Administrator —
#     UAA is required because downstream infra bicep creates role assignments of its own).
#   - (default ON) Microsoft Graph grants so the deploy SP can ensure/update the waypoint
#     Entra app registration HEADLESSLY under least privilege: the Graph application
#     permission Application.ReadWrite.OwnedBy (appRole id resolved dynamically) PLUS
#     ownership of the `waypoint` app reg (created if missing). Opt out with --no-graph-grants.
#   - Writes AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID / AZURE_LOCATION
#     as GitHub repo BOTH variables AND secrets. keystone needs them as VARIABLES (the
#     `wire`/`preflight` jobs read vars.AZURE_*) AND as SECRETS (the waypoint reusable
#     call consumes them as required secrets). ON by default; opt out with
#     --no-set-repo-config. The values are always printed too.
#
# Requirements:
#   - az CLI logged in as a user able to create app/SP + role assignments
#     (Owner or Contributor + User Access Administrator on the subscription)
#   - jq
#   - gh, authenticated with repo admin (for the default variable/secret write)
#
# Usage (matches the already-configured keystone state — a no-op):
#   ./scripts/oidc.sh \
#     --owner caldova --repo keystone \
#     --subscription-id <SUB_ID> \
#     --app-name forge-gha-oidc \
#     --branch main \
#     --pull-request
#   # repo variables+secrets are written by default; add --no-set-repo-config to skip.
#   # Graph grants (Application.ReadWrite.OwnedBy + waypoint app ownership) are ON by
#   # default; add --no-graph-grants to skip. Override deploy config: --location <region>.
# ------------------------------------------------------------------------------

OWNER="caldova"
REPO="keystone"
SUBSCRIPTION_ID=""
APP_NAME="forge-gha-oidc"
BRANCH="main"
ENVIRONMENT=""
ROLES="Contributor,User Access Administrator"
LOCATION="swedencentral"
ADD_PULL_REQUEST="true"
# Repo variables + secrets are written by DEFAULT so the repo is fully configured
# after one run (one-click). Opt out with --no-set-repo-config.
SET_REPO_CONFIG="true"
# Microsoft Graph grants so the deploy SP can ensure/update the waypoint Entra app
# registration HEADLESSLY (app roles, identifier uri, post-deploy redirect URI) under least
# privilege. ON by default; opt out with --no-graph-grants.
GRANT_GRAPH="true"
WAYPOINT_APP_NAME="waypoint"
AZD_ENV_NAME="waypoint-agents"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --subscription-id) SUBSCRIPTION_ID="$2"; shift 2 ;;
    --app-name) APP_NAME="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --environment) ENVIRONMENT="$2"; shift 2 ;;
    --roles) ROLES="$2"; shift 2 ;;
    --location) LOCATION="$2"; shift 2 ;;
    --pull-request) ADD_PULL_REQUEST="true"; shift 1 ;;
    --no-pull-request) ADD_PULL_REQUEST="false"; shift 1 ;;
    --set-repo-config) SET_REPO_CONFIG="true"; shift 1 ;;
    --no-set-repo-config) SET_REPO_CONFIG="false"; shift 1 ;;
    --graph-grants) GRANT_GRAPH="true"; shift 1 ;;
    --no-graph-grants) GRANT_GRAPH="false"; shift 1 ;;
    --waypoint-app-name) WAYPOINT_APP_NAME="$2"; shift 2 ;;
    --azd-env-name) AZD_ENV_NAME="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,51p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$SUBSCRIPTION_ID" ]]; then
  echo "Missing required arg: --subscription-id" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required. Install jq and retry." >&2
  exit 1
fi

echo "Setting Azure subscription..."
az account set --subscription "$SUBSCRIPTION_ID"

TENANT_ID="$(az account show --query tenantId -o tsv)"
SCOPE="/subscriptions/${SUBSCRIPTION_ID}"
SUBJECT_PREFIX="repo:${OWNER}/${REPO}"
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  IMMUTABLE_PREFIX="$(
    gh api "repos/${OWNER}/${REPO}/actions/oidc/customization/sub" \
      --jq '.sub_claim_prefix // empty' 2>/dev/null || true
  )"
  if [[ -n "$IMMUTABLE_PREFIX" ]]; then
    SUBJECT_PREFIX="$IMMUTABLE_PREFIX"
  fi
fi

echo "Looking up app registration: ${APP_NAME}"
APP_JSON="$(az ad app list --filter "displayName eq '${APP_NAME}'" --query '[0]' -o json)"
APP_ID="$(echo "$APP_JSON" | jq -r '.appId // empty')"
APP_OBJECT_ID="$(echo "$APP_JSON" | jq -r '.id // empty')"

if [[ -z "$APP_ID" ]]; then
  echo "Creating app registration: ${APP_NAME}"
  CREATED_APP="$(az ad app create --display-name "$APP_NAME" -o json)"
  APP_ID="$(echo "$CREATED_APP" | jq -r '.appId')"
  APP_OBJECT_ID="$(echo "$CREATED_APP" | jq -r '.id')"
else
  echo "Reusing existing app registration: ${APP_NAME} (${APP_ID})"
fi

echo "Ensuring service principal exists..."
SP_OBJECT_ID="$(az ad sp list --filter "appId eq '$APP_ID'" --query '[0].id' -o tsv)"
if [[ -z "$SP_OBJECT_ID" ]]; then
  az ad sp create --id "$APP_ID" >/dev/null
  for i in {1..10}; do
    SP_OBJECT_ID="$(az ad sp list --filter "appId eq '$APP_ID'" --query '[0].id' -o tsv || true)"
    [[ -n "$SP_OBJECT_ID" ]] && break
    sleep 2
  done
fi

if [[ -z "$SP_OBJECT_ID" ]]; then
  echo "Failed to resolve service principal for appId ${APP_ID}" >&2
  exit 1
fi

echo "Service principal object id: ${SP_OBJECT_ID}"

# ---- federated credential helper --------------------------------------------
# ensure_fed_cred_subject NAME SUBJECT DESCRIPTION
ensure_fed_cred_subject() {
  local name="$1" subject="$2" desc="$3"
  echo "Ensuring federated credential: ${name}  (subject: ${subject})"
  local current_subject
  current_subject="$(
    az ad app federated-credential list --id "$APP_OBJECT_ID" \
      --query "[?name=='${name}'] | [0].subject" -o tsv
  )"
  if [[ "$current_subject" == "$subject" ]]; then
    echo "  already exists"
    return 0
  fi
  local tmp; tmp="$(mktemp)"
  cat > "$tmp" <<EOF
{
  "name": "${name}",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "${subject}",
  "audiences": ["api://AzureADTokenExchange"],
  "description": "${desc}"
}
EOF
  if [[ -n "$current_subject" ]]; then
    az ad app federated-credential update \
      --id "$APP_OBJECT_ID" \
      --federated-credential-id "$name" \
      --parameters "$tmp" >/dev/null
    echo "  updated"
  else
    az ad app federated-credential create --id "$APP_OBJECT_ID" --parameters "$tmp" >/dev/null
    echo "  created"
  fi
  rm -f "$tmp"
}
# -----------------------------------------------------------------------------

# Primary subject: a branch ref, or a GitHub Environment.
if [[ -n "$ENVIRONMENT" ]]; then
  ensure_fed_cred_subject \
    "github-${OWNER}-${REPO}-env-${ENVIRONMENT}" \
    "${SUBJECT_PREFIX}:environment:${ENVIRONMENT}" \
    "GitHub Actions OIDC for ${OWNER}/${REPO} (env ${ENVIRONMENT})"
else
  ensure_fed_cred_subject \
    "github-${OWNER}-${REPO}-branch-${BRANCH}" \
    "${SUBJECT_PREFIX}:ref:refs/heads/${BRANCH}" \
    "GitHub Actions OIDC for ${OWNER}/${REPO} (branch ${BRANCH})"
fi

# Optional: pull_request subject (PR runs reaching Azure for the read-only preflight).
if [[ "$ADD_PULL_REQUEST" == "true" ]]; then
  ensure_fed_cred_subject \
    "github-${OWNER}-${REPO}-pull-request" \
    "${SUBJECT_PREFIX}:pull_request" \
    "GitHub Actions OIDC for ${OWNER}/${REPO} (pull_request)"
fi

# ---- role assignments --------------------------------------------------------
IFS=',' read -r -a ROLE_ARRAY <<< "$ROLES"
for ROLE in "${ROLE_ARRAY[@]}"; do
  ROLE_TRIMMED="$(echo "$ROLE" | xargs)"
  [[ -z "$ROLE_TRIMMED" ]] && continue
  echo "Ensuring role assignment: ${ROLE_TRIMMED} on ${SCOPE}"
  RA_COUNT="$(az role assignment list \
    --assignee "$SP_OBJECT_ID" \
    --scope "$SCOPE" \
    --role "$ROLE_TRIMMED" \
    --query 'length(@)' -o tsv)"
  if [[ "$RA_COUNT" == "0" ]]; then
    az role assignment create \
      --assignee "$SP_OBJECT_ID" \
      --role "$ROLE_TRIMMED" \
      --scope "$SCOPE" >/dev/null
    echo "  Assigned ${ROLE_TRIMMED}"
  else
    echo "  Already assigned ${ROLE_TRIMMED}"
  fi
done

# ---- Microsoft Graph grants for HEADLESS MSAL app-reg management -------------
# The one-click deploy must ensure/update the waypoint Entra app registration (app roles,
# identifier uri, and the post-deploy SPA redirect URI) with NO human in the loop. Under
# least privilege that requires two grants, both idempotent (lookup-before-create):
#   (a) the deploy SP holds the Graph application permission Application.ReadWrite.OwnedBy
#   (b) the deploy SP is an OWNER of the waypoint app reg (OwnedBy scopes writes to owned apps)
# Resolve the appRole id DYNAMICALLY (well-known ids differ per tenant — do not hardcode).
if [[ "$GRANT_GRAPH" == "true" ]]; then
  GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
  echo "Ensuring Microsoft Graph app permission Application.ReadWrite.OwnedBy on the deploy SP..."
  GRAPH_SP_ID="$(az ad sp show --id "$GRAPH_APP_ID" --query id -o tsv 2>/dev/null || true)"
  [[ -z "$GRAPH_SP_ID" ]] && GRAPH_SP_ID="$(az ad sp list --filter "appId eq '$GRAPH_APP_ID'" --query '[0].id' -o tsv 2>/dev/null || true)"
  if [[ -z "$GRAPH_SP_ID" ]]; then
    echo "::warning:: could not resolve the Microsoft Graph service principal; skipping Graph grant." >&2
  else
    APPROLE_ID="$(az ad sp show --id "$GRAPH_SP_ID" \
      --query "appRoles[?value=='Application.ReadWrite.OwnedBy'].id | [0]" -o tsv 2>/dev/null || true)"
    if [[ -z "$APPROLE_ID" ]]; then
      echo "::warning:: Application.ReadWrite.OwnedBy appRole not found on the Graph SP; skipping." >&2
    else
      EXISTING="$(az rest --method GET \
        --url "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_OBJECT_ID}/appRoleAssignments" \
        --query "length(value[?appRoleId=='${APPROLE_ID}' && resourceId=='${GRAPH_SP_ID}'])" -o tsv 2>/dev/null || echo 0)"
      if [[ -z "$EXISTING" || "$EXISTING" == "0" ]]; then
        az rest --method POST \
          --url "https://graph.microsoft.com/v1.0/servicePrincipals/${SP_OBJECT_ID}/appRoleAssignments" \
          --headers "Content-Type=application/json" \
          --body "{\"principalId\":\"${SP_OBJECT_ID}\",\"resourceId\":\"${GRAPH_SP_ID}\",\"appRoleId\":\"${APPROLE_ID}\"}" >/dev/null
        echo "  granted Application.ReadWrite.OwnedBy (appRole ${APPROLE_ID})"
      else
        echo "  already granted"
      fi
    fi
  fi

  # Ensure the waypoint app reg exists, then make the deploy SP an owner of it.
  echo "Ensuring waypoint app registration + deploy-SP ownership: ${WAYPOINT_APP_NAME}"
  WP_JSON="$(az ad app list --filter "displayName eq '${WAYPOINT_APP_NAME}'" --query '[0]' -o json)"
  WP_APP_ID="$(echo "$WP_JSON" | jq -r '.appId // empty')"
  WP_OBJ_ID="$(echo "$WP_JSON" | jq -r '.id // empty')"
  if [[ -z "$WP_APP_ID" ]]; then
    echo "  creating app registration: ${WAYPOINT_APP_NAME}"
    WP_CREATED="$(az ad app create --display-name "$WAYPOINT_APP_NAME" -o json)"
    WP_APP_ID="$(echo "$WP_CREATED" | jq -r '.appId')"
    WP_OBJ_ID="$(echo "$WP_CREATED" | jq -r '.id')"
  else
    echo "  reusing app registration: ${WAYPOINT_APP_NAME} (${WP_APP_ID})"
  fi
  if [[ -n "$WP_OBJ_ID" ]]; then
    OWNS="$(az ad app owner list --id "$WP_OBJ_ID" --query "length([?id=='${SP_OBJECT_ID}'])" -o tsv 2>/dev/null || echo 0)"
    if [[ -z "$OWNS" || "$OWNS" == "0" ]]; then
      az ad app owner add --id "$WP_OBJ_ID" --owner-object-id "$SP_OBJECT_ID" >/dev/null
      echo "  added deploy SP as owner of ${WAYPOINT_APP_NAME}"
    else
      echo "  deploy SP already owns ${WAYPOINT_APP_NAME}"
    fi
    WP_EXISTING_TAGS="$(az ad app show --id "$WP_APP_ID" --query tags -o json 2>/dev/null || echo '[]')"
    WP_TAG_BODY="$(AZD_ENV_NAME="$AZD_ENV_NAME" REPOSITORY="${OWNER}/${REPO}" python3 - "$WP_EXISTING_TAGS" <<'PY'
import json, os, sys
tags = set(json.loads(sys.argv[1] or "[]"))
tags.update({
    "waypoint-managed",
    f"waypoint-environment={os.environ['AZD_ENV_NAME']}",
    f"waypoint-repository={os.environ['REPOSITORY']}",
})
print(json.dumps({"tags": sorted(tags)}))
PY
)"
    az rest --method PATCH \
      --url "https://graph.microsoft.com/v1.0/applications/${WP_OBJ_ID}" \
      --headers "Content-Type=application/json" \
      --body "$WP_TAG_BODY" >/dev/null
    echo "  tagged ${WAYPOINT_APP_NAME} for environment-scoped teardown"
  fi
fi

# ---- write repo variables AND secrets (on by default) -----------------------
# keystone reads Azure creds as VARIABLES (preflight/wire jobs) AND passes them as
# SECRETS to the waypoint reusable workflow, so we set both.
if [[ "$SET_REPO_CONFIG" == "true" ]]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "::error:: gh CLI not found — cannot auto-set repo variables/secrets." >&2
    SET_REPO_CONFIG="failed"
  elif ! gh auth status >/dev/null 2>&1; then
    echo "::error:: gh is not authenticated — run 'gh auth login' and re-run." >&2
    SET_REPO_CONFIG="failed"
  else
    echo "Setting GitHub repository variables + secrets on ${OWNER}/${REPO}..."
    set_var() {
      local name="$1" value="$2"
      if gh variable set "$name" --repo "${OWNER}/${REPO}" --body "$value" >/dev/null 2>&1; then
        echo "  ✓ var ${name}=${value}"
      else
        echo "::error:: failed to set variable ${name} on ${OWNER}/${REPO} (needs repo admin / 'repo' scope)." >&2
        SET_REPO_CONFIG="failed"
      fi
    }
    set_secret() {
      local name="$1" value="$2"
      if gh secret set "$name" --repo "${OWNER}/${REPO}" --body "$value" >/dev/null 2>&1; then
        echo "  ✓ secret ${name}=***"
      else
        echo "::error:: failed to set secret ${name} on ${OWNER}/${REPO} (needs repo admin / 'repo' scope)." >&2
        SET_REPO_CONFIG="failed"
      fi
    }
    for cfg in \
      "AZURE_CLIENT_ID:${APP_ID}" \
      "AZURE_TENANT_ID:${TENANT_ID}" \
      "AZURE_SUBSCRIPTION_ID:${SUBSCRIPTION_ID}" \
      "AZURE_LOCATION:${LOCATION}"; do
      name="${cfg%%:*}"; value="${cfg#*:}"
      set_var "$name" "$value"
      set_secret "$name" "$value"
    done
  fi
fi

if [[ "$SET_REPO_CONFIG" == "failed" ]]; then
  cat >&2 <<EOF

Repo config was NOT fully set. Run these manually with a gh token that has repo admin:
  for n in AZURE_CLIENT_ID AZURE_TENANT_ID AZURE_SUBSCRIPTION_ID AZURE_LOCATION; do :; done
  gh variable set AZURE_CLIENT_ID       --repo ${OWNER}/${REPO} --body ${APP_ID}
  gh variable set AZURE_TENANT_ID       --repo ${OWNER}/${REPO} --body ${TENANT_ID}
  gh variable set AZURE_SUBSCRIPTION_ID --repo ${OWNER}/${REPO} --body ${SUBSCRIPTION_ID}
  gh variable set AZURE_LOCATION        --repo ${OWNER}/${REPO} --body ${LOCATION}
  gh secret   set AZURE_CLIENT_ID       --repo ${OWNER}/${REPO} --body ${APP_ID}
  gh secret   set AZURE_TENANT_ID       --repo ${OWNER}/${REPO} --body ${TENANT_ID}
  gh secret   set AZURE_SUBSCRIPTION_ID --repo ${OWNER}/${REPO} --body ${SUBSCRIPTION_ID}
  gh secret   set AZURE_LOCATION        --repo ${OWNER}/${REPO} --body ${LOCATION}
EOF
fi

cat <<EOF

Done.

GitHub repository config for ${OWNER}/${REPO} (set as BOTH variables and secrets):
- AZURE_CLIENT_ID=${APP_ID}
- AZURE_TENANT_ID=${TENANT_ID}
- AZURE_SUBSCRIPTION_ID=${SUBSCRIPTION_ID}
- AZURE_LOCATION=${LOCATION}

Service principal object id (for Fabric AdministratorMembersJson / assignToCapacity):
- ${SP_OBJECT_ID}

Microsoft Graph grants for headless MSAL app-reg management: $([[ "$GRANT_GRAPH" == "true" ]] && echo "ensured (Application.ReadWrite.OwnedBy + owner of '${WAYPOINT_APP_NAME}')" || echo "SKIPPED (--no-graph-grants)")

ZERO manual configuration remains. The deploy provisions a Key Vault (API keys + Postgres
password), ensures the MSAL app reg, and discovers/derives every other value at runtime —
there is NO WAYPOINT_* / WAYPOINT_FABRIC_* matrix, NO KEYSTONE_KEY_SEED, and NO
AZURE_RESOURCE_GROUP / POSTGRES_APP_PASSWORD secret to set. The only app-specific secret is
GH_MCP_PAT (forge's toolbox MCP PAT), passed straight through to forge's reusable workflow.
EOF
