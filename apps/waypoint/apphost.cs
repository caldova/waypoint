#:sdk Aspire.AppHost.Sdk@13.4.5
#:package MessagePack@3.1.7
#:package Aspire.Hosting.Python@13.4.5
#:package Aspire.Hosting.JavaScript@13.4.5
#:package Aspire.Hosting.Azure@13.4.5
#:package Aspire.Hosting.Azure.AppContainers@13.4.5
#:package Aspire.Hosting.PostgreSQL@13.4.5

var builder = DistributedApplication.CreateBuilder(args);

// Configure Azure Container App Environment for deployment
var appContainer = builder.AddAzureContainerAppEnvironment("waypoint-env");

var msalEnabled = builder.Configuration["Waypoint:Msal:Enabled"]
    ?? (builder.ExecutionContext.IsRunMode ? "false" : "true");
var msalTenantId = builder.Configuration["Waypoint:Msal:TenantId"] ?? "";
var msalClientId = builder.Configuration["Waypoint:Msal:ClientId"] ?? "";
var msalApiScope = builder.Configuration["Waypoint:Msal:ApiScope"]
    ?? (string.IsNullOrWhiteSpace(msalClientId)
        ? ""
        : $"api://{msalClientId}/user_impersonation");
var msalRedirectUri = builder.Configuration["Waypoint:Msal:RedirectUri"] ?? "";
var msalApiValidationEnabled = builder.Configuration["Waypoint:Msal:ApiValidationEnabled"] ?? msalEnabled;
var msalApiValidationIsEnabled = IsEnabled(msalApiValidationEnabled);
var apiKeyAuthEnabled = bool.TryParse(
    builder.Configuration["Waypoint:ApiKeyAuth:Enabled"],
    out var parsedApiKeyAuthEnabled
) && parsedApiKeyAuthEnabled;
var apiKeyAuthEnabledValue = apiKeyAuthEnabled ? "true" : "false";
var allowedOrigins = builder.Configuration["Waypoint:Cors:AllowedOrigins"] ?? "http://localhost:5173";
var msalWriterAppRole = builder.Configuration["Waypoint:Msal:WriterAppRole"] ?? "Waypoint.Write";
var msalReaderAppRole = builder.Configuration["Waypoint:Msal:ReaderAppRole"] ?? "Waypoint.Read";
var msalAdminAppRole = builder.Configuration["Waypoint:Msal:AdminAppRole"] ?? "Waypoint.Admin";
var msalAllowedAppIds = builder.Configuration["Waypoint:Msal:AllowedAppIds"] ?? "";
var foundryEndpoint = builder.Configuration["Waypoint:Foundry:Endpoint"] ?? "";
var foundryProjectUrl = builder.Configuration["Waypoint:Foundry:ProjectUrl"] ?? "";
var appInsightsResourceId = builder.Configuration["Waypoint:AppInsights:ResourceId"] ?? "";
var configuredLedgerfieldSeedPath = builder.Configuration["Waypoint:Ledgerfield:SeedPath"] ?? "";
var ledgerfieldSeedUri = builder.Configuration["Waypoint:Ledgerfield:SeedUri"] ?? "";
var ledgerfieldSeedPath = builder.ExecutionContext.IsRunMode
    ? ResolveLocalLedgerfieldSeedPath(configuredLedgerfieldSeedPath)
    : configuredLedgerfieldSeedPath;
var defaultSeedEnabled = builder.ExecutionContext.IsRunMode
    && string.IsNullOrWhiteSpace(ledgerfieldSeedPath)
    && string.IsNullOrWhiteSpace(ledgerfieldSeedUri)
    ? "true"
    : "false";
var buildVersion = builder.Configuration["BUILD_VERSION"] ?? "local";

// Microsoft Fabric / OneLake corpus lake configuration. The Fabric capacity is provisioned via
// Bicep (infra/fabric-capacity.bicep); the workspace + lakehouse are created by the azd
// postprovision hook (infra/scripts/provision-fabric.sh) because they are not ARM/Bicep types.
// All Fabric provisioning is gated behind Waypoint:Fabric:ProvisionEnabled so a local `aspire run`
// never provisions and the API degrades to URI-only document metadata.
var fabricProvisionEnabled = bool.TryParse(
    builder.Configuration["Waypoint:Fabric:ProvisionEnabled"],
    out var parsedFabricProvisionEnabled
) && parsedFabricProvisionEnabled;
// CI passes Waypoint:Fabric:* as empty strings when the matching repo variables/inputs are unset.
// The null-coalescing operator only falls back on null, so an empty string would otherwise blank
// out these settings and publish empty APP_ONELAKE_* env on the API. Treat empty/whitespace as
// "unset" so the defaults (and the explicit overrides) always win.
static string? Coalesce(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
var fabricCapacityName = Coalesce(builder.Configuration["Waypoint:Fabric:CapacityName"]) ?? "waypointcorpus";
var fabricSkuName = Coalesce(builder.Configuration["Waypoint:Fabric:SkuName"]) ?? "F64";
var fabricLakehouseName = Coalesce(builder.Configuration["Waypoint:Fabric:LakehouseName"]) ?? "corpus";
var fabricCorpusPrefix = Coalesce(builder.Configuration["Waypoint:Fabric:CorpusPrefix"]) ?? "Files/corpus";
var fabricAccountUrl = Coalesce(builder.Configuration["Waypoint:Fabric:AccountUrl"])
    ?? "https://onelake.dfs.fabric.microsoft.com";
var fabricAdminMembersJson = Coalesce(builder.Configuration["Waypoint:Fabric:AdministratorMembersJson"]) ?? "[]";
// The workspace id is only known after the postprovision hook runs; it publishes the value via
// `azd env set APP_ONELAKE_WORKSPACE`, which is read here on the next deploy. Falls back to an
// explicit Waypoint:Fabric:Workspace override (e.g. the WAYPOINT_FABRIC_WORKSPACE repo variable).
var onelakeWorkspace = Coalesce(builder.Configuration["APP_ONELAKE_WORKSPACE"])
    ?? Coalesce(builder.Configuration["Waypoint:Fabric:Workspace"])
    ?? "";
var onelakeLakehouse = Coalesce(builder.Configuration["APP_ONELAKE_LAKEHOUSE"]) ?? fabricLakehouseName;

// Fabric IQ = the AI layer for operational analytics: a Direct Lake semantic model plus a published
// Fabric Data Agent. By default it grounds on the mirrored operational Postgres financial core
// (suppliers, invoices, invoice_lines, reconciliation_findings); the legacy keystone-corpus lakehouse
// source is still selectable via WAYPOINT_FABRIC_IQ_SOURCE=lakehouse. Like the workspace/lakehouse
// these are not ARM/Bicep types, so they are created by an idempotent, notebook-free REST script
// (infra/scripts/provision-fabric-iq.sh) run from the azd postprovision hook / deploy workflow, gated
// behind Waypoint:Fabric:IqEnabled. The names are surfaced to the API so /config can deep-link the
// agent; empty when IQ is not provisioned.
var fabricIqEnabled = bool.TryParse(
    builder.Configuration["Waypoint:Fabric:IqEnabled"],
    out var parsedFabricIqEnabled
) && parsedFabricIqEnabled;
var fabricSemanticModelName = Coalesce(builder.Configuration["Waypoint:Fabric:SemanticModelName"]) ?? "CaldovaIQ";
var fabricDataAgentName = Coalesce(builder.Configuration["Waypoint:Fabric:DataAgentName"]) ?? "WaypointDataAgent";

if (!builder.ExecutionContext.IsRunMode)
{
    if (msalApiValidationIsEnabled)
    {
        if (string.IsNullOrWhiteSpace(msalTenantId) || string.IsNullOrWhiteSpace(msalClientId))
        {
            throw new InvalidOperationException(
                "Published Waypoint API deployments require Waypoint:Msal:TenantId and Waypoint:Msal:ClientId when MSAL API validation is enabled."
            );
        }
    }
    else if (!apiKeyAuthEnabled)
    {
        throw new InvalidOperationException(
            "Published Waypoint API deployments must enable MSAL API validation or scoped API-key authentication."
        );
    }
}

// Python FastAPI Backend
var api = builder.AddUvicornApp("api", "./api", "app.main:app")
    .WithUv()
    .WithEnvironment("APP_CORS_ALLOWED_ORIGINS", allowedOrigins)
    .WithEnvironment("APP_MSAL_BEARER_VALIDATION_ENABLED", msalApiValidationEnabled)
    .WithEnvironment("APP_MSAL_TENANT_ID", msalTenantId)
    .WithEnvironment("APP_MSAL_CLIENT_ID", msalClientId)
    .WithEnvironment("APP_MSAL_REQUIRED_SCOPE", "user_impersonation")
    .WithEnvironment("APP_MSAL_WRITER_APP_ROLE", msalWriterAppRole)
    .WithEnvironment("APP_MSAL_READER_APP_ROLE", msalReaderAppRole)
    .WithEnvironment("APP_MSAL_ADMIN_APP_ROLE", msalAdminAppRole)
    .WithEnvironment("APP_MSAL_ALLOWED_APP_IDS", msalAllowedAppIds)
    .WithEnvironment("APP_FOUNDRY_ENDPOINT", foundryEndpoint)
    .WithEnvironment("APP_FOUNDRY_PROJECT_URL", foundryProjectUrl)
    .WithEnvironment("APP_APP_INSIGHTS_RESOURCE_ID", appInsightsResourceId)
    .WithEnvironment("APP_API_KEY_AUTH_ENABLED", apiKeyAuthEnabledValue)
    .WithEnvironment("APP_API_DOCS_ENABLED", builder.ExecutionContext.IsRunMode ? "true" : "false")
    .WithEnvironment("APP_LEDGERFIELD_SEED_PATH", ledgerfieldSeedPath)
    .WithEnvironment("APP_LEDGERFIELD_SEED_URI", ledgerfieldSeedUri)
    .WithEnvironment("APP_DEFAULT_SEED_ENABLED", defaultSeedEnabled)
    .WithEnvironment("APP_ONELAKE_ACCOUNT_URL", fabricAccountUrl)
    .WithEnvironment("APP_ONELAKE_WORKSPACE", onelakeWorkspace)
    .WithEnvironment("APP_ONELAKE_LAKEHOUSE", onelakeLakehouse)
    .WithEnvironment("APP_ONELAKE_CORPUS_PREFIX", fabricCorpusPrefix)
    .WithEnvironment("APP_FABRIC_IQ_SEMANTIC_MODEL", fabricIqEnabled ? fabricSemanticModelName : "")
    .WithEnvironment("APP_FABRIC_IQ_DATA_AGENT", fabricIqEnabled ? fabricDataAgentName : "")
    .WithHttpHealthCheck("/health")
    .WithExternalHttpEndpoints()
    .PublishAsAzureContainerApp((infra, app) =>
    {
        var container = app.Template.Containers[0].Value!;
        container.Resources.Cpu = 1;
        container.Resources.Memory = "2Gi";
    });

if (builder.ExecutionContext.IsRunMode && !msalApiValidationIsEnabled)
{
    api.WithEnvironment("APP_LOCAL_AUTH_ENABLED", "true");
}

if (apiKeyAuthEnabled)
{
    var apiKeys = builder.AddParameter("api-keys", secret: true)
        .WithDescription("Semicolon-separated production API keys in label:key:role,role format. Prefer MSAL; use this only for scoped bootstrap or non-MSAL consumers.");
    api.WithEnvironment("APP_API_KEYS", apiKeys);
}

// Provision the Microsoft Fabric capacity that backs the OneLake corpus lake. The workspace and
// lakehouse are created by the azd postprovision hook (infra/scripts/provision-fabric.sh).
if (!builder.ExecutionContext.IsRunMode && fabricProvisionEnabled)
{
    builder.AddBicepTemplate("fabric-capacity", "./infra/fabric-capacity.bicep")
        .WithParameter("capacityName", fabricCapacityName)
        .WithParameter("skuName", fabricSkuName)
        .WithParameter("administratorMembersJson", fabricAdminMembersJson);
}

if (builder.ExecutionContext.IsRunMode)
{
    // Local PostgreSQL-compatible posture. Deployments use Azure PostgreSQL
    // by default, with Azure HorizonDB available as an explicit opt-in.
    var postgres = builder.AddPostgres("postgres");
    var horizonDb = postgres.AddDatabase("horizondb");

    api.WaitFor(horizonDb)
        .WithEnvironment("APP_DATABASE_CONNECTION", horizonDb.Resource.ConnectionStringExpression);
}
else
{
    var databaseProvider = builder.Configuration["Waypoint:Database:Provider"] ?? "azure-postgres";
    var postgresProvisionEnabled = bool.TryParse(
        builder.Configuration["Waypoint:Postgres:ProvisionEnabled"],
        out var parsedPostgresProvisionEnabled
    ) && parsedPostgresProvisionEnabled;
    var postgresServerName = builder.Configuration["Waypoint:Postgres:ServerName"] ?? "waypoint-postgres";
    var postgresAdminLogin = builder.Configuration["Waypoint:Postgres:AdminLogin"] ?? "waypointadmin";
    var postgresAppUser = builder.Configuration["Waypoint:Postgres:AppUser"] ?? "waypoint_app";
    var postgresDatabaseName = builder.Configuration["Waypoint:Postgres:DatabaseName"] ?? "waypoint";
    var postgresSkuName = builder.Configuration["Waypoint:Postgres:SkuName"] ?? "Standard_D2ds_v5";
    var postgresSkuTier = builder.Configuration["Waypoint:Postgres:SkuTier"] ?? "GeneralPurpose";
    var postgresStorageSizeGB = int.Parse(builder.Configuration["Waypoint:Postgres:StorageSizeGB"] ?? "32");
    var postgresBackupRetentionDays = int.Parse(builder.Configuration["Waypoint:Postgres:BackupRetentionDays"] ?? "7");
    var postgresFirewallRulesJson = builder.Configuration["Waypoint:Postgres:FirewallRulesJson"] ?? "[]";
    // FabricIQ grounds on a zero-ETL mirror of the operational Postgres. Mirroring does NOT
    // support the Burstable tier, so enabling it keeps the server on GeneralPurpose (above) and
    // provisions the source prerequisites (SAMI + logical WAL + azure_cdc) in the bicep template.
    var postgresFabricMirroringEnabled = bool.TryParse(
        builder.Configuration["Waypoint:Fabric:MirrorEnabled"],
        out var parsedPostgresFabricMirroringEnabled
    ) && parsedPostgresFabricMirroringEnabled;
    var postgresMirroredDatabaseCount = int.Parse(
        builder.Configuration["Waypoint:Fabric:MirroredDatabaseCount"] ?? "1"
    );
    var horizonDbProvisionEnabled = bool.TryParse(
        builder.Configuration["Waypoint:HorizonDB:ProvisionEnabled"],
        out var parsedHorizonDbProvisionEnabled
    ) && parsedHorizonDbProvisionEnabled;
    var horizonDbClusterName = builder.Configuration["Waypoint:HorizonDB:ClusterName"] ?? "waypoint-horizondb";
    var horizonDbAdminLogin = builder.Configuration["Waypoint:HorizonDB:AdminLogin"] ?? "waypointadmin";
    var horizonDbAppUser = builder.Configuration["Waypoint:HorizonDB:AppUser"] ?? "waypoint_app";
    var horizonDbDatabaseName = builder.Configuration["Waypoint:HorizonDB:DatabaseName"] ?? "waypoint";
    var horizonDbVCores = int.Parse(builder.Configuration["Waypoint:HorizonDB:VCores"] ?? "2");
    var horizonDbReplicaCount = int.Parse(builder.Configuration["Waypoint:HorizonDB:ReplicaCount"] ?? "1");
    var horizonDbZonePlacementPolicy = builder.Configuration["Waypoint:HorizonDB:ZonePlacementPolicy"] ?? "BestEffort";
    var horizonDbFirewallRulesJson = builder.Configuration["Waypoint:HorizonDB:FirewallRulesJson"] ?? "[]";

    if (databaseProvider == "azure-postgres")
    {
        var postgresAppPassword = builder.AddParameter("postgres-app-password", secret: true)
            .WithDescription("Password for the least-privilege Azure PostgreSQL role used by the Waypoint API.");
        var postgresEndpoint = $"{postgresServerName}.postgres.database.azure.com";

        // The admin bootstrap connection is needed in two cases: (1) Aspire provisions the server,
        // or (2) Fabric Mirroring is enabled on a pre-existing server AND the keystone Key Vault
        // supplied the admin password (Waypoint:Fabric:AdminBootstrapEnabled, set by deploy.yml only
        // when it could read the postgres-admin-password secret). In case (2) the API startup
        // bootstrap uses this connection to create the dedicated fabric_user mirroring role with no
        // psql on the runner. When the admin secret is absent we skip it gracefully — the parameter
        // is never declared (so aspire deploy does not demand it) and mirroring still works if
        // fabric_user was already created out-of-band.
        var postgresAdminBootstrapEnabled = bool.TryParse(
            builder.Configuration["Waypoint:Fabric:AdminBootstrapEnabled"],
            out var parsedPostgresAdminBootstrapEnabled
        ) && parsedPostgresAdminBootstrapEnabled;
        var postgresBootstrapEnabled =
            postgresProvisionEnabled || (postgresFabricMirroringEnabled && postgresAdminBootstrapEnabled);

        if (postgresBootstrapEnabled)
        {
            var postgresAdminPassword = builder.AddParameter("postgres-admin-password", secret: true)
                .WithDescription("Administrator password used to provision Azure PostgreSQL and/or bootstrap the least-privilege Waypoint and Fabric Mirroring database roles.");

            if (postgresProvisionEnabled)
            {
                builder.AddBicepTemplate("postgres-flexible", "./infra/postgres-flexible.bicep")
                    .WithParameter("serverName", postgresServerName)
                    .WithParameter("administratorLogin", postgresAdminLogin)
                    .WithParameter("administratorLoginPassword", postgresAdminPassword)
                    .WithParameter("applicationUserName", postgresAppUser)
                    .WithParameter("databaseName", postgresDatabaseName)
                    .WithParameter("skuName", postgresSkuName)
                    .WithParameter("skuTier", postgresSkuTier)
                    .WithParameter("storageSizeGB", postgresStorageSizeGB)
                    .WithParameter("backupRetentionDays", postgresBackupRetentionDays)
                    .WithParameter("firewallRulesJson", postgresFirewallRulesJson)
                    .WithParameter("enableFabricMirroring", postgresFabricMirroringEnabled)
                    .WithParameter("mirroredDatabaseCount", postgresMirroredDatabaseCount);
            }

            api.WithEnvironment(
                "APP_DATABASE_BOOTSTRAP_CONNECTION",
                $"Host={postgresEndpoint};Port=5432;Database=postgres;Username={postgresAdminLogin};Password={postgresAdminPassword};SSL Mode=require"
            );
        }

        api.WithEnvironment(
            "APP_DATABASE_CONNECTION",
            $"Host={postgresEndpoint};Port=5432;Database={postgresDatabaseName};Username={postgresAppUser};Password={postgresAppPassword};SSL Mode=require"
        );

        // Fabric Mirroring role bootstrap. When mirroring is enabled the API's privileged startup
        // bootstrap (which already holds APP_DATABASE_BOOTSTRAP_CONNECTION) also provisions the
        // dedicated fabric_user mirroring role and transfers ownership of the mirrored tables to
        // it. This keeps the deploy pipeline free of any admin connection string or psql: the only
        // mirror secret is fabric-mirror-password, generated once into the keystone Key Vault and
        // shared by this API bootstrap and the deploy-time Fabric connection.
        if (postgresFabricMirroringEnabled)
        {
            var fabricMirrorPassword = builder.AddParameter("fabric-mirror-password", secret: true)
                .WithDescription("Password for the Fabric Mirroring PostgreSQL role. Generated once and stored in the keystone Key Vault, then shared by the API bootstrap and the deploy-time Fabric connection.");
            var fabricMirrorUser = builder.Configuration["Waypoint:Fabric:MirrorUser"] ?? "fabric_user";
            api.WithEnvironment("APP_FABRIC_MIRROR_ENABLED", "true")
                .WithEnvironment("APP_FABRIC_MIRROR_USER", fabricMirrorUser)
                .WithEnvironment("APP_FABRIC_MIRROR_PASSWORD", fabricMirrorPassword);
        }
    }
    else if (databaseProvider == "horizondb" && horizonDbProvisionEnabled)
    {
        var horizonDbAdminPassword = builder.AddParameter("horizondb-admin-password", secret: true)
            .WithDescription("Administrator password used only to provision the HorizonDB cluster and bootstrap the least-privilege Waypoint database role.");
        var horizonDbAppPassword = builder.AddParameter("horizondb-app-password", secret: true)
            .WithDescription("Password for the least-privilege HorizonDB role used by the Waypoint API.");
        var horizonDb = builder.AddBicepTemplate("horizondb", "./infra/horizondb.bicep")
            .WithParameter("clusterName", horizonDbClusterName)
            .WithParameter("administratorLogin", horizonDbAdminLogin)
            .WithParameter("administratorLoginPassword", horizonDbAdminPassword)
            .WithParameter("applicationUserName", horizonDbAppUser)
            .WithParameter("databaseName", horizonDbDatabaseName)
            .WithParameter("vCores", horizonDbVCores)
            .WithParameter("replicaCount", horizonDbReplicaCount)
            .WithParameter("zonePlacementPolicy", horizonDbZonePlacementPolicy)
            .WithParameter("firewallRulesJson", horizonDbFirewallRulesJson);

        var horizonDbEndpoint = horizonDb.GetOutput("primaryEndpoint");
        api.WithEnvironment(
                "APP_DATABASE_BOOTSTRAP_CONNECTION",
                $"Host={horizonDbEndpoint};Port=5432;Database=postgres;Username={horizonDbAdminLogin};Password={horizonDbAdminPassword};SSL Mode=require"
            )
            .WithEnvironment(
                "APP_DATABASE_CONNECTION",
                $"Host={horizonDbEndpoint};Port=5432;Database={horizonDbDatabaseName};Username={horizonDbAppUser};Password={horizonDbAppPassword};SSL Mode=require"
            );
    }
}

// React/Vite Frontend
var web = builder.AddViteApp("web", "./web")
    .WithReference(api, "API_ENDPOINT")
    .WaitFor(api)
    .WithEnvironment("WAYPOINT_MSAL_ENABLED", msalEnabled)
    .WithEnvironment("WAYPOINT_MSAL_TENANT_ID", msalTenantId)
    .WithEnvironment("WAYPOINT_MSAL_CLIENT_ID", msalClientId)
    .WithEnvironment("WAYPOINT_MSAL_API_SCOPE", msalApiScope)
    .WithEnvironment("WAYPOINT_MSAL_REDIRECT_URI", msalRedirectUri)
    .WithEnvironment("BUILD_VERSION", buildVersion)
    .WithExternalHttpEndpoints()
    .PublishAsAzureContainerApp((infra, app) =>
    {
        var container = app.Template.Containers[0].Value!;
        container.Resources.Cpu = 1;
        container.Resources.Memory = "2Gi";
    });

// Force HTTPS for the API URL at deploy time
if (builder.ExecutionContext.IsPublishMode)
{
    api.WithEndpoint("http", e => e.UriScheme = "https");
}

builder.Build().Run();

static string ResolveLocalLedgerfieldSeedPath(string configuredPath)
{
    if (!string.IsNullOrWhiteSpace(configuredPath))
    {
        return configuredPath;
    }

    var userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
    var roots = new[]
    {
        Path.Combine(userProfile, ".copilot", "copilot-worktrees", "ledgerfield"),
        Path.Combine(userProfile, ".copilot", "repos", "ledgerfield"),
    };

    return roots
        .Where(Directory.Exists)
        .SelectMany(root => Directory.EnumerateFiles(root, "waypoint-seed.json", SearchOption.AllDirectories))
        .OrderBy(path => path)
        .FirstOrDefault() ?? "";
}

static bool IsEnabled(string value)
{
    return value.Trim().ToLowerInvariant() switch
    {
        "1" or "true" or "yes" or "y" or "on" => true,
        _ => false,
    };
}
