#!/usr/bin/env bash
# Stage 0 (provision-keyvault): the secret store for the whole one-click deploy.
#
# ZERO manual config: instead of any user-set seed/secret, keystone PROVISIONS an Azure Key
# Vault (the deploy SP has Contributor + User Access Admin via OIDC) and GENERATES-ONCE-THEN-
# READS the shared x-api-keys (writer/reader/admin) and the Postgres app password as KV
# secrets. Generate-once = `az keyvault secret set` only when the secret is absent, so the
# values are STABLE across runs (idempotent) with no PAT, no self-written GitHub secrets, and
# no deterministic seed. Partial re-runs that skip this stage just read the same KV secrets.
#
# Consumed downstream:
#   forge  : WAYPOINT_WRITER_API_KEY / WAYPOINT_READER_API_KEY (azd env set at deploy)
#   waypoint: WAYPOINT_API_KEYS (composed) + POSTGRES_APP_PASSWORD (reusable-call secrets)
#   seed-import: admin key (x-api-key admin)
#
# Required env:
#   KV_NAME        Key Vault name (from discover; deterministic + globally unique)
#   STATE_RG       resource group to host the vault (from discover; dedicated rg-keystone)
#   AZURE_LOCATION region for the vault (default swedencentral)
# Optional env:
#   SP_OBJECT_ID   deploy SP object id (from discover) for the KV data-plane RBAC self-grant
#   AZURE_CLIENT_ID  fallback to resolve SP_OBJECT_ID if not provided
#   WAYPOINT_DEPLOY_SP_OBJECT_ID  waypoint-deploy SP object id also granted Secrets Officer so
#                  waypoint reads this vault with its OWN identity
#   FORGE_DIR      local forge checkout -> also `azd env set` the key vars (local path only)
#   AZD_ENV_NAME   azd env for the local forge path (default waypoint)
set -euo pipefail

kv="${KV_NAME:?KV_NAME required}"
rg="${STATE_RG:?STATE_RG required}"
loc="${AZURE_LOCATION:-swedencentral}"
sp_oid="${SP_OBJECT_ID:-}"
# waypoint-deploy SP: reads this vault (key_vault_name input) with its own identity, so it needs
# its own data-plane grant independent of who provisioned the vault.
wp_sp_oid="${WAYPOINT_DEPLOY_SP_OBJECT_ID:-}"
forge_dir="${FORGE_DIR:-/nonexistent}"
env_name="${AZD_ENV_NAME:-waypoint}"

log() { echo "keyvault: $*" >&2; }
mask() { printf '%s' "$1" | sed -E 's/.{4}$/****/; s/^(.{4}).*/\1…/'; }

# ---- ensure the resource group + vault (idempotent; recover if soft-deleted) ----
az group create --name "$rg" --location "$loc" -o none 2>/dev/null || true

if az keyvault show --name "$kv" -o none 2>/dev/null; then
  log "vault $kv exists"
elif az keyvault list-deleted --query "[?name=='${kv}'] | [0].name" -o tsv 2>/dev/null | grep -q .; then
  log "vault $kv is soft-deleted — recovering"
  az keyvault recover --name "$kv" -o none
else
  log "creating vault $kv in $rg ($loc) with RBAC authorization"
  az keyvault create --name "$kv" --resource-group "$rg" --location "$loc" \
    --enable-rbac-authorization true -o none
fi
vault_uri="$(az keyvault show --name "$kv" --query properties.vaultUri -o tsv)"

# ---- self-grant data-plane access (Key Vault Secrets Officer) to the deploy SP(s) ----
[[ -z "$sp_oid" && -n "${AZURE_CLIENT_ID:-}" ]] && sp_oid="$(az ad sp show --id "$AZURE_CLIENT_ID" --query id -o tsv 2>/dev/null || true)"
scope="$(az keyvault show --name "$kv" --query id -o tsv)"
grant_secrets_officer() { # grant_secrets_officer <object-id> <label>
  local oid="$1" label="$2"
  [[ -z "$oid" ]] && return 0
  if az role assignment list --assignee "$oid" --scope "$scope" \
        --query "[?roleDefinitionName=='Key Vault Secrets Officer'] | [0]" -o tsv 2>/dev/null | grep -q .; then
    log "$label $oid already has Key Vault Secrets Officer"
    return 0
  fi
  log "granting Key Vault Secrets Officer to $label $oid"
  az role assignment create --assignee-object-id "$oid" --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets Officer" --scope "$scope" -o none 2>/dev/null || \
    log "WARN: role assignment create for $label returned non-zero (may already exist or propagating)"
}
if [[ -n "$sp_oid" ]]; then
  grant_secrets_officer "$sp_oid" "deploy SP"
else
  log "WARN: no SP object id — assuming the caller already has KV data-plane access"
fi
# Also grant the waypoint-deploy SP so waypoint reads this vault with its own identity (repeatable).
if [[ -n "$wp_sp_oid" ]]; then
  grant_secrets_officer "$wp_sp_oid" "waypoint-deploy SP"
else
  log "WARN: no WAYPOINT_DEPLOY_SP_OBJECT_ID — skipping waypoint-deploy KV grant"
fi

# ---- generate-once-then-read each secret ----
# Wait out RBAC propagation for the first read/write after a fresh grant.
secret_get() { az keyvault secret show --vault-name "$kv" --name "$1" --query value -o tsv 2>/dev/null || true; }
secret_ensure() { # secret_ensure <name> <generator-cmd...>
  local name="$1"; shift
  local val; val="$(secret_get "$name")"
  if [[ -z "$val" ]]; then
    local i
    for i in 1 2 3 4 5 6; do
      val="$("$@")"
      if az keyvault secret set --vault-name "$kv" --name "$name" --value "$val" -o none 2>/dev/null; then
        log "generated secret $name"
        break
      fi
      log "set $name failed (attempt $i) — RBAC may be propagating; retrying in ${i}0s"
      sleep "${i}0"
      val=""
    done
    [[ -z "$val" ]] && { echo "::error::could not write KV secret $name (RBAC?)" >&2; exit 1; }
  else
    log "secret $name already present (reused)"
  fi
  printf '%s' "$val"
}
gen_key() { openssl rand -hex 32; }
# Postgres flexible-server policy: >=3 of 4 char classes. Prefix guarantees upper+lower+digit+special.
gen_pgpw() { printf 'Aa1!%s' "$(openssl rand -hex 24)"; }

writer_key="$(secret_ensure waypoint-writer-key gen_key)"
reader_key="$(secret_ensure waypoint-reader-key gen_key)"
admin_key="$(secret_ensure waypoint-admin-key gen_key)"
pg_password="$(secret_ensure postgres-app-password gen_pgpw)"
# Admin password for the Postgres flexible server (provisioning path). Generate-once + vault-store
# so waypoint feeds it to the `postgres-admin-password` Aspire parameter and its API startup
# bootstrap creates the fabric_user role. Same policy-safe generator (never contains 'waypointadmin').
pg_admin_password="$(secret_ensure postgres-admin-password gen_pgpw)"

# Composed api-keys string waypoint consumes (label:key:role; writer role expands to reader).
api_keys="aggregator:${writer_key}:writer;concierge:${reader_key}:reader;seed:${admin_key}:admin"

# Store the composed string in KV too, so the waypoint reusable deploy can read it directly
# (GitHub Actions refuses to pass masked secret values through job outputs, so the value
# cannot be handed across jobs — the Key Vault is the system of record).
current_api_keys="$(secret_get waypoint-api-keys)"
if [[ "$current_api_keys" == "$api_keys" ]]; then
  log "secret waypoint-api-keys already current (reused)"
elif az keyvault secret set --vault-name "$kv" --name waypoint-api-keys --value "$api_keys" -o none 2>/dev/null; then
  log "reconciled secret waypoint-api-keys"
else
  echo "::error::could not reconcile KV secret waypoint-api-keys" >&2
  exit 1
fi

log "vault $kv ready ($vault_uri) — writer=$(mask "$writer_key") reader=$(mask "$reader_key") admin=$(mask "$admin_key") pg=$(mask "$pg_password") pg-admin=$(mask "$pg_admin_password")"

# ---- local forge path: seed the two key vars into the forge azd env ----
if [[ -d "$forge_dir" ]]; then
  forge_env="${FORGE_ENV_NAME:-forge}"
  azd env set WAYPOINT_WRITER_API_KEY "$writer_key" --cwd "$forge_dir" --environment "$forge_env" 2>/dev/null || true
  azd env set WAYPOINT_READER_API_KEY "$reader_key" --cwd "$forge_dir" --environment "$forge_env" 2>/dev/null || true
  log "forge azd env ($forge_env) seeded with writer/reader keys"
fi

# ---- emit masked job outputs ----
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  for v in "$writer_key" "$reader_key" "$admin_key" "$pg_password" "$pg_admin_password" "$api_keys"; do echo "::add-mask::$v"; done
  {
    echo "writer_api_key=${writer_key}"
    echo "reader_api_key=${reader_key}"
    echo "admin_api_key=${admin_key}"
    echo "postgres_app_password=${pg_password}"
    echo "postgres_admin_password=${pg_admin_password}"
    echo "api_keys=${api_keys}"
    echo "kv_name=${kv}"
  } >> "$GITHUB_OUTPUT"
fi
log "complete (secret values never printed in full)"
