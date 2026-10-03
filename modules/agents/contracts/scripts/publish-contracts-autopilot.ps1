param(
    [string]$AgentName = "contracts",
    [string]$AppVersion = "1.0.7",
    [string]$DisplayName = "Contracts",
    [string]$BlueprintClientId = $env:CONTRACTS_AGENT_IDENTITY_BLUEPRINT_CLIENT_ID,
    [string]$ColorIconPath = "assets\caldova-color-icon.png",
    [string]$OutlineIconPath = "assets\caldova-outline-icon.png"
)

$ErrorActionPreference = "Stop"

function Get-RequiredEnv {
    param([Parameter(Mandatory)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required environment variable '$Name'. Run 'azd env get-values' and set it for this shell, or run this script from an azd hook."
    }
    return $value.Trim()
}

$projectEndpoint = Get-RequiredEnv -Name "AZURE_AI_PROJECT_ENDPOINT"
$tenantId = Get-RequiredEnv -Name "AZURE_TENANT_ID"
if ([string]::IsNullOrWhiteSpace($BlueprintClientId)) {
    throw "Missing -BlueprintClientId. Get it from the deployed agent's identity blueprint/client id, then rerun this script."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentRoot = Resolve-Path (Join-Path $scriptRoot "..")
$resolvedColorIconPath = Resolve-Path (Join-Path $agentRoot $ColorIconPath)
$resolvedOutlineIconPath = Resolve-Path (Join-Path $agentRoot $OutlineIconPath)

$publishUrl = "$($projectEndpoint.TrimEnd('/'))/agents/$AgentName/microsoft365/publish?api-version=2025-11-15-preview"

$body = @{
    agentDisplayName = $DisplayName
    publishAsAutopilot = $true
    publishScope = "Tenant"
    appVersion = $AppVersion
    canRespondWithoutMention = $true
    shortDescription = "Contract intake autopilot for mailbox-driven contract review."
    fullDescription = "Contracts monitors the contracts inbox, registers contract artifacts, drafts review briefs, and writes approved reports to SharePoint for Caldova contract operations."
    developerName = "Caldova"
    developerWebsiteUrl = "https://github.com/caldova/waypoint"
    privacyUrl = "https://github.com/caldova/waypoint/blob/main/SECURITY.md"
    termsOfUseUrl = "https://github.com/caldova/waypoint/blob/main/LICENSE"
    colorIconBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($resolvedColorIconPath))
    outlineIconBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($resolvedOutlineIconPath))
    optionalPermissionScopes = @(
        @{
            resourceAppId = "00000003-0000-0000-c000-000000000000"
            scopes = @(
                "Mail.Read",
                "Mail.Send",
                "Files.ReadWrite"
            )
        }
    )
    useAgenticUserTemplate = $true
    agenticUserTemplate = @{
        Id = "digitalWorkerTemplate"
        File = "agenticUserTemplateManifest.json"
        SchemaVersion = "0.1.0-preview"
        AgentIdentityBlueprintId = $BlueprintClientId.Trim()
        CommunicationProtocol = "activityProtocol"
    }
}

$jsonBody = $body | ConvertTo-Json -Depth 20
$token = az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv --tenant $tenantId
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) {
    throw "Failed to get an Azure AI token. Run 'az login --tenant $tenantId' and retry."
}

Write-Host "Publishing $AgentName autopilot version $AppVersion to Microsoft 365..."
$response = Invoke-RestMethod `
    -Uri $publishUrl `
    -Method Post `
    -Headers @{
        "Content-Type" = "application/json"
        "Accept" = "application/json"
        "Authorization" = "Bearer $token"
    } `
    -Body $jsonBody

$response | ConvertTo-Json -Depth 10
