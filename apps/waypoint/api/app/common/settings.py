"""Application settings using Pydantic BaseSettings.

Environment variables are loaded with the APP_ prefix.
Example: APP_DATABASE_CONNECTION -> settings.database_connection
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    All settings use the APP_ prefix. For example:
    - APP_DATABASE_CONNECTION -> database_connection
    - APP_STORAGE_CONNECTION -> storage_connection

    Extend this class to add more configuration options as needed.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    # Database settings. Local Aspire uses PostgreSQL as the HorizonDB-compatible stand-in.
    database_connection: str = Field(
        default="",
        description="PostgreSQL/HorizonDB-compatible connection string",
    )
    database_bootstrap_connection: str = Field(
        default="",
        description=(
            "Privileged PostgreSQL/HorizonDB connection string used only for startup bootstrap"
        ),
    )
    database_name: str = Field(
        default="StarterDB",
        description="Database name",
    )
    database_pool_min_size: int = Field(
        default=1,
        description="Minimum PostgreSQL connection pool size per API process",
    )
    database_pool_max_size: int = Field(
        default=10,
        description="Maximum PostgreSQL connection pool size per API process",
    )
    ledgerfield_seed_path: str = Field(
        default="",
        description="Optional local path to Ledgerfield's generated Waypoint seed JSON",
    )
    default_seed_enabled: bool = Field(
        default=False,
        description="Load the built-in demo seed when no external seed path is configured",
    )

    # Storage settings (legacy Azure Blob; superseded by OneLake corpus settings below)
    storage_connection: str = Field(
        default="",
        description="Storage connection string (e.g., Azure Blob Storage)",
    )
    storage_container: str = Field(
        default="",
        description="Storage container name",
    )

    # OneLake (Microsoft Fabric) corpus lake settings. When configured, the API resolves
    # contract/policy/invoice document content from the Lakehouse Files area and can load the
    # Ledgerfield seed from the lake. All reads use DefaultAzureCredential (container-app MI).
    onelake_account_url: str = Field(
        default="https://onelake.dfs.fabric.microsoft.com",
        description="OneLake ADLS Gen2 DFS endpoint",
    )
    onelake_workspace: str = Field(
        default="",
        description="Fabric workspace name or GUID (acts as the OneLake filesystem)",
    )
    onelake_lakehouse: str = Field(
        default="",
        description="Fabric lakehouse name (without the .Lakehouse suffix)",
    )
    onelake_corpus_prefix: str = Field(
        default="Files/corpus",
        description="Path prefix under the lakehouse for the demo corpus documents",
    )

    # Fabric Mirroring settings. When enabled, the API's privileged startup bootstrap also
    # provisions the dedicated PostgreSQL mirroring role (login/createdb/createrole/replication,
    # azure_cdc_admin, ownership of the mirrored tables) so the deploy pipeline never needs an
    # admin connection or psql on the runner. The single mirror credential is generated once and
    # stored in the keystone Key Vault, then shared by the API (here) and the Fabric connection
    # created by the deploy step, keeping the whole flow idempotent and keystone-repeatable.
    fabric_mirror_enabled: bool = Field(
        default=False,
        description="Bootstrap the Fabric Mirroring PostgreSQL role during startup bootstrap",
    )
    fabric_mirror_user: str = Field(
        default="fabric_user",
        description="Login role Fabric Mirroring uses to connect to the source PostgreSQL server",
    )
    fabric_mirror_password: str = Field(
        default="",
        description=(
            "Password for the Fabric Mirroring role. Generated once and stored in the keystone "
            "Key Vault; shared by the API bootstrap and the deploy-time Fabric connection."
        ),
    )
    fabric_mirror_tables: str = Field(
        default="suppliers,invoices,invoice_lines,reconciliation_findings",
        description="Comma-separated tables whose ownership transfers to the mirroring role",
    )

    # AI settings
    foundry_endpoint: str = Field(
        default="",
        description="Azure AI Foundry project endpoint",
    )
    foundry_orchestrator_agent_name: str = Field(
        default="assurance-orchestrator",
        description="Server-owned hosted agent used for invoice assurance triggers",
    )
    foundry_responses_api_version: str = Field(
        default="2025-11-15-preview",
        description="Foundry hosted-agent Responses API version",
    )
    foundry_start_timeout_seconds: float = Field(
        default=60,
        gt=0,
        le=120,
        description="Timeout for starting a Foundry background response",
    )
    azure_openai_endpoint: str = Field(
        default="",
        description="Azure OpenAI endpoint for AI features",
    )

    # Agent-run lifecycle reaper. Runs are execution telemetry (not durable business state),
    # so a run stuck in 'running' past a TTL is auto-failed to keep the Runs/Activity views
    # honest. All values are defaulted, so enabling the reaper requires no deploy or Keystone
    # input; override per environment only if needed.
    #
    # Scope + TTL rationale:
    # - Only 'running' runs are reaped (see REAPABLE_STATUSES). 'pending' runs are queued
    #   batch-enrollment placeholders that have not started yet (Activity "in-flight"); in a large
    #   batch, later invoices sit 'pending' for many minutes before flipping to 'running', so
    #   reaping them would kill legitimately-queued work. Pending reaping is therefore opt-in (see
    #   the pending TTL below, default 0 = disabled) with a deliberately long lease.
    # - The reaper is a PROCESS-DEATH BACKSTOP, not a heartbeat enforcer. The Forge orchestrator
    #   bounds its own runtime (max_runtime_minutes, default 30m) and GUARANTEES finalize in a
    #   `finally` block (success -> completed/partial, timeout/exception -> failed); it does NOT
    #   heartbeat. So the default TTL (2100s / 35m) sits ABOVE that 30m self-bound: a run still
    #   'running' past ~35m means the orchestrator process died before its own finally could run
    #   (container restart/OOM) -- a genuine orphan -- while a run under the TTL is treated as
    #   legitimately progressing even though updated_at has not moved (no heartbeat). A shorter TTL
    #   would false-positive and kill live runs. Keep configurable to tune if the bound changes.
    run_reaper_enabled: bool = Field(
        default=True,
        description="Run the background sweep that auto-fails stale running agent runs",
    )
    run_reaper_ttl_seconds: int = Field(
        default=2100,
        description=(
            "Age (based on updated_at) after which a 'running' agent run is treated as an orphan "
            "and transitioned to failed. Defaults to 35m -- a process-death backstop above the "
            "orchestrator's 30m self-bound (the harness finalizes in a `finally`, no heartbeat)."
        ),
    )
    run_reaper_pending_ttl_seconds: int = Field(
        default=0,
        description=(
            "Optional separate TTL for reaping 'pending' (queued, not-yet-started) runs. 0 "
            "disables pending reaping (the safe default, since batch queue waits can be long); "
            "set to a long value (e.g. 7200 for 2h) to also backstop pending runs orphaned by a "
            "dead batch."
        ),
    )
    run_reaper_sweep_interval_seconds: int = Field(
        default=60,
        description="Seconds between background stale-run sweeps",
    )

    # HTTP/CORS settings
    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated browser origins allowed to call the API",
    )
    api_docs_enabled: bool = Field(
        default=False,
        description="Expose FastAPI docs, ReDoc, and OpenAPI schema endpoints",
    )

    # Authentication settings
    msal_bearer_validation_enabled: bool = Field(
        default=False,
        description="Validate browser-sent MSAL bearer tokens for the Waypoint API",
    )
    local_auth_enabled: bool = Field(
        default=False,
        description="Allow loopback-only local development requests without a bearer token",
    )
    api_key_auth_enabled: bool = Field(
        default=False,
        description="Allow scoped X-API-Key fallback authentication",
    )
    api_keys: str = Field(
        default="",
        description="Semicolon-separated API keys as label:key:role,role",
    )
    msal_tenant_id: str = Field(
        default="",
        description="Tenant ID expected on browser-sent MSAL bearer tokens",
    )
    msal_client_id: str = Field(
        default="",
        description="Client ID expected as the audience on browser-sent MSAL bearer tokens",
    )
    msal_required_scope: str = Field(
        default="user_impersonation",
        description="Delegated scope required on browser-sent MSAL bearer tokens",
    )
    msal_jwks_cache_ttl_seconds: int = Field(
        default=3600,
        description="Seconds to cache Microsoft Entra signing keys for MSAL bearer validation",
    )
    msal_reader_app_role: str = Field(
        default="Waypoint.Read",
        description="App role granting reader access to app-only (managed identity) tokens",
    )
    msal_writer_app_role: str = Field(
        default="Waypoint.Write",
        description="App role granting writer access to app-only (managed identity) tokens",
    )
    msal_admin_app_role: str = Field(
        default="Waypoint.Admin",
        description="App role granting admin access to app-only (managed identity) tokens",
    )
    msal_allowed_app_ids: str = Field(
        default="",
        description=(
            "Optional comma-separated allow-list of client/app IDs accepted on app-only tokens"
        ),
    )

    # AI/telemetry drill-down configuration surfaced to authenticated UI deep-links
    app_insights_resource_id: str = Field(
        default="",
        description="Azure Monitor / App Insights resource ID used for portal deep-links",
    )
    foundry_project_url: str = Field(
        default="",
        description="Azure AI Foundry project URL used for agent/run deep-links",
    )

    # Ledgerfield seed delivery
    ledgerfield_seed_uri: str = Field(
        default="",
        description=(
            "Optional Azure Blob URL for the Ledgerfield seed JSON, fetched via managed identity"
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


if __name__ == "__main__":
    # Quick test to print current settings
    settings = Settings()
    print(settings.model_dump())
