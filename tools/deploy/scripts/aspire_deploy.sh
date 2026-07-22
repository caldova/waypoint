#!/usr/bin/env bash
set -uo pipefail

resource_group="${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP is required}"
max_attempts="${ASPIRE_DEPLOY_MAX_ATTEMPTS:-3}"
attempt_timeout="${ASPIRE_DEPLOY_ATTEMPT_TIMEOUT:-15m}"
retry_delay_seconds="${ASPIRE_DEPLOY_RETRY_DELAY_SECONDS:-20}"
capacity_pattern='ManagedEnvironmentCapacityHeavyUsageError|AKSCapacityHeavyUsage'
managed_identity_pull_pattern='unable to pull image using Managed identity'
transient_pattern="connect: connection refused|connection reset by peer|TLS handshake timeout|unexpected EOF|i/o timeout|temporarily unavailable|status code (429|5[0-9]{2})|${capacity_pattern}|${managed_identity_pull_pattern}"

ensure_acr_pull_assignment() {
  local registries
  local identities
  local registry_count
  local identity_count
  local registry_id
  local principal_id
  local environment_deployment
  local role_assignment_names
  local role_assignment_count
  local role_assignment_name

  registries="$(
    az acr list \
      --resource-group "$resource_group" \
      --query "[?tags.\"aspire-resource-name\" == 'starter-env-acr'].id" \
      --output tsv
  )" || return 1
  identities="$(
    az identity list \
      --resource-group "$resource_group" \
      --query "[?starts_with(name, 'starter_env_mi-')].principalId" \
      --output tsv
  )" || return 1
  registry_count="$(printf '%s\n' "$registries" | grep -c .)"
  identity_count="$(printf '%s\n' "$identities" | grep -c .)"
  if [ "$registry_count" != "1" ] || [ "$identity_count" != "1" ]; then
    echo "::error::Expected one Aspire registry and identity; found ${registry_count} registries and ${identity_count} identities."
    return 1
  fi
  registry_id="$registries"
  principal_id="$identities"
  environment_deployment="$(
    az deployment group list \
      --resource-group "$resource_group" \
      --query "sort_by([?starts_with(name, 'starter-env-')], &properties.timestamp)[-1].name" \
      --output tsv
  )" || return 1
  if [ -z "$environment_deployment" ]; then
    echo "::error::Could not find the Aspire environment deployment that declared AcrPull."
    return 1
  fi
  role_assignment_names="$(
    az deployment operation group list \
      --resource-group "$resource_group" \
      --name "$environment_deployment" \
      --query "[?properties.targetResource.resourceType == 'Microsoft.Authorization/roleAssignments'].properties.targetResource.resourceName" \
      --output tsv
  )" || return 1
  role_assignment_count="$(printf '%s\n' "$role_assignment_names" | grep -c .)"
  if [ "$role_assignment_count" != "1" ]; then
    echo "::error::Expected one Aspire AcrPull assignment declaration; found ${role_assignment_count}."
    return 1
  fi
  role_assignment_name="$role_assignment_names"

  echo "::warning::Reconciling AcrPull after managed-identity image-pull propagation failure."
  az role assignment create \
    --name "$role_assignment_name" \
    --assignee-object-id "$principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role AcrPull \
    --scope "$registry_id" \
    --output none || return 1
  sleep 30
}

capacity_failed_environment() {
  local environments
  if ! environments="$(az containerapp env list \
    --resource-group "$resource_group" \
    --query "[?properties.deploymentErrors != null && (contains(properties.deploymentErrors, 'ManagedEnvironmentCapacityHeavyUsageError') || contains(properties.deploymentErrors, 'AKSCapacityHeavyUsage')) && (properties.provisioningState == 'Failed' || properties.provisioningState == 'Updating')].name" \
    --output tsv)"; then
    echo "::error::Could not inspect Container Apps environments for capacity failures." >&2
    return 1
  fi
  if [ "$(printf '%s\n' "$environments" | grep -c .)" -gt 1 ]; then
    echo "::error::Multiple capacity-failed Container Apps environments found; refusing ambiguous cleanup." >&2
    return 1
  fi
  printf '%s\n' "$environments"
}

cancel_running_environment_deployments() {
  local environment_name="$1"
  local deployment
  local deployments
  local target_count
  if ! deployments="$(az deployment group list \
    --resource-group "$resource_group" \
    --query "[?properties.provisioningState == 'Running' && starts_with(name, 'starter-env-')].name" \
    --output tsv)"; then
    echo "::error::Could not inspect running Container Apps deployments." >&2
    return 1
  fi
  while IFS= read -r deployment; do
    [ -z "$deployment" ] && continue
    if ! target_count="$(az deployment operation group list \
        --resource-group "$resource_group" \
        --name "$deployment" \
        --query "[?properties.targetResource.resourceType == 'Microsoft.App/managedEnvironments' && properties.targetResource.resourceName == '${environment_name}'] | length(@)" \
        --output tsv)"; then
      echo "::error::Could not inspect deployment ${deployment}; refusing cancellation." >&2
      return 1
    fi
    [ "$target_count" = "0" ] && continue
    echo "::warning::Cancelling stalled Container Apps deployment ${deployment}."
    if ! az deployment group cancel \
      --resource-group "$resource_group" \
      --name "$deployment" \
      --output none; then
      echo "::warning::Azure did not accept cancellation for ${deployment}; cleanup will still verify deletion."
    fi
  done <<< "$deployments"
}

remove_capacity_failed_environment() {
  local environment_name="$1"
  local app_count
  if ! app_count="$(az containerapp list \
      --resource-group "$resource_group" \
      --query "[?properties.managedEnvironmentId != null && ends_with(properties.managedEnvironmentId, '/${environment_name}')] | length(@)" \
      --output tsv)"; then
    echo "::error::Could not verify whether ${environment_name} contains Container Apps." >&2
    return 1
  fi
  if [ "$app_count" != "0" ]; then
    echo "::error::Refusing to delete capacity-failed environment ${environment_name}; it contains ${app_count} Container App(s)."
    return 1
  fi

  cancel_running_environment_deployments "$environment_name" || return 1
  echo "::warning::Removing app-empty capacity-failed environment ${environment_name} before retry."
  if ! az containerapp env delete \
    --resource-group "$resource_group" \
    --name "$environment_name" \
    --yes \
    --no-wait; then
    echo "::error::Azure rejected deletion of capacity-failed environment ${environment_name}."
    return 1
  fi

  for check in $(seq 1 80); do
    if ! az containerapp env show \
      --resource-group "$resource_group" \
      --name "$environment_name" \
      --output none 2>/dev/null; then
      echo "Capacity-failed environment ${environment_name} was removed."
      return 0
    fi
    echo "Waiting for ${environment_name} deletion (${check}/80)."
    sleep 15
  done

  echo "::error::Timed out waiting for capacity-failed environment ${environment_name} to be deleted."
  return 1
}

for attempt in $(seq 1 "$max_attempts"); do
  if ! failed_environment="$(capacity_failed_environment)"; then
    exit 1
  fi
  if [ -n "$failed_environment" ]; then
    remove_capacity_failed_environment "$failed_environment" || exit 1
  fi

  echo "::group::aspire deploy attempt ${attempt} / ${max_attempts}"
  timeout --signal=TERM --kill-after=30s "$attempt_timeout" \
    aspire deploy --non-interactive 2>&1 | tee aspire-deploy.log
  deploy_exit=${PIPESTATUS[0]}
  echo "::endgroup::"
  if [ "$deploy_exit" -eq 0 ]; then
    exit 0
  fi

  recovered_capacity_failure=false
  if ! failed_environment="$(capacity_failed_environment)"; then
    exit 1
  fi
  if [ -n "$failed_environment" ]; then
    remove_capacity_failed_environment "$failed_environment" || exit 1
    recovered_capacity_failure=true
  elif [ "$deploy_exit" -eq 124 ]; then
    echo "::error::Aspire deploy exceeded ${attempt_timeout} without a recognized capacity failure."
    exit "$deploy_exit"
  fi

  if [ "$attempt" -eq "$max_attempts" ]; then
    exit "$deploy_exit"
  fi
  if grep -Eqi "$managed_identity_pull_pattern" aspire-deploy.log; then
    ensure_acr_pull_assignment || exit 1
  fi
  if [ "$recovered_capacity_failure" != "true" ] \
    && ! grep -Eqi "$transient_pattern" aspire-deploy.log; then
    exit "$deploy_exit"
  fi
  echo "::warning::Transient Azure/registry failure; retrying idempotent Aspire deploy."
  sleep $((retry_delay_seconds * attempt))
done
