#!/usr/bin/env bash
set -euo pipefail

azd_value() {
  local value
  value="$(azd env get-value "$1" 2>/dev/null || true)"
  case "$value" in
    ""|*"not found"*|ERROR*) return 1 ;;
    *) printf '%s' "$value" ;;
  esac
}

use_existing="$(azd_value USE_EXISTING_AI_PROJECT || true)"
if [[ "${use_existing,,}" == "true" ]]; then
  echo "Existing Foundry project selected; account bootstrap is not required."
  exit 0
fi

environment_name="${AZD_ENV_NAME:-$(azd_value AZURE_ENV_NAME || true)}"
subscription_id="${AZURE_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"
resource_group="${AZURE_RESOURCE_GROUP:-$(azd_value AZURE_RESOURCE_GROUP || true)}"
location="${AZURE_LOCATION:-$(azd_value AZURE_LOCATION || true)}"
principal_id="$(azd_value AZURE_PRINCIPAL_ID || true)"
if [[ -z "$principal_id" ]]; then
  principal_id="$(
    az account get-access-token \
      --resource https://management.azure.com/ \
      --query accessToken \
      --output tsv \
      | python -c 'import base64,json,sys; p=sys.stdin.read().strip().split(".")[1]; print(json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))["oid"])'
  )"
  azd env set AZURE_PRINCIPAL_ID "$principal_id"
fi

for variable in environment_name subscription_id resource_group location principal_id; do
  if [[ -z "${!variable}" ]]; then
    echo "Missing required bootstrap value: $variable" >&2
    exit 2
  fi
done

account_name="$(azd_value AZURE_AI_ACCOUNT_NAME || true)"
if [[ -z "$account_name" ]]; then
  safe_environment="$(printf '%s' "$environment_name" \
    | tr '[:upper:]_' '[:lower:]-' \
    | tr -cd '[:alnum:]-' \
    | sed -E 's/^-+//; s/-+$//' \
    | cut -c1-40)"
  if command -v sha256sum >/dev/null 2>&1; then
    suffix="$(printf '%s' "${environment_name}${subscription_id}" | sha256sum | cut -c1-8)"
  else
    suffix="$(printf '%s' "${environment_name}${subscription_id}" | shasum -a 256 | cut -c1-8)"
  fi
  account_name="ai-${safe_environment}-${suffix}"
  azd env set AZURE_AI_ACCOUNT_NAME "$account_name"
fi

project_name="$(azd_value AZURE_AI_PROJECT_NAME || true)"
if [[ -z "$project_name" ]]; then
  project_name="ai-project-${environment_name}"
  azd env set AZURE_AI_PROJECT_NAME "$project_name"
fi

echo "Bootstrapping Foundry parent account: ${resource_group}/${account_name}"
az group create \
  --name "$resource_group" \
  --location "$location" \
  --output none
az deployment group create \
  --name "foundry-account-bootstrap" \
  --resource-group "$resource_group" \
  --template-file infra/core/ai/bootstrap-account.bicep \
  --parameters \
    accountName="$account_name" \
    location="$location" \
    principalId="$principal_id" \
    tags="{\"azd-env-name\":\"${environment_name}\"}" \
  --output none

sleep 30

project_url="https://management.azure.com/subscriptions/${subscription_id}/resourceGroups/${resource_group}/providers/Microsoft.CognitiveServices/accounts/${account_name}/projects/${project_name}?api-version=2026-03-01"
if ! az rest --method get --url "$project_url" --output none 2>/dev/null; then
  echo "Creating Foundry project outside ARM template preflight: ${account_name}/${project_name}"
  project_body="$(
    jq -n \
      --arg location "$location" \
      --arg display_name "$project_name" \
      '{
        location: $location,
        kind: "AIServices",
        sku: {name: "S0"},
        identity: {type: "SystemAssigned"},
        properties: {displayName: $display_name}
      }'
  )"
  az rest \
    --method put \
    --url "$project_url" \
    --body "$project_body" \
    --output none
fi

for _ in {1..30}; do
  project_state="$(az rest --method get --url "$project_url" --query properties.provisioningState -o tsv 2>/dev/null || true)"
  if [[ "$project_state" == "Succeeded" ]]; then
    echo "Foundry account, project, and deployment-principal roles are ready for azd reconciliation."
    exit 0
  fi
  if [[ "$project_state" == "Failed" ]]; then
    echo "Foundry project bootstrap entered a failed provisioning state." >&2
    exit 1
  fi
  sleep 10
done

echo "Timed out waiting for Foundry project bootstrap to complete." >&2
exit 1
