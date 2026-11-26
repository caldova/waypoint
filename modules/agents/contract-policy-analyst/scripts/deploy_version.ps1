param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9-]*$')][string]$Release,
    [Parameter(Mandatory)][ValidateSet('none', 'minimal', 'low', 'medium', 'high')][string]$ReasoningEffort,
    [int]$ExpectVersion = 0,
    [ValidatePattern('^$|^[A-Za-z0-9_-]+$')][string]$Candidate = '',
    [string]$Environment = 'contract-policy-analyst'
)
$ErrorActionPreference = 'Stop'
$agent = 'contract-policy-analyst'
$root = Split-Path $PSScriptRoot -Parent
$localDir = if ($Release -eq 'baseline') { '' } else { "releases/$Release" }
$releaseDir = if ($localDir) { Join-Path $root "releases\$Release" } else { Join-Path $root '.agent_configs' }
$configDir = Join-Path $releaseDir 'baseline'
$selectedDir = if ($Candidate) { Join-Path $releaseDir $Candidate } else { $configDir }
foreach ($file in 'instructions.md', 'tools.json', 'metadata.yaml') {
    if (-not (Test-Path (Join-Path $selectedDir $file))) { throw "Missing $file in $selectedDir" }
}
$metadata = Join-Path $configDir 'metadata.yaml'
if (-not (Test-Path $metadata)) { throw "Missing release: $configDir" }
$model = ((Get-Content $metadata | Where-Object { $_ -match '^model:\s*(\S+)' }) -replace '^model:\s*', '').Trim()
if (-not $model) { throw 'Release declares no model.' }

Push-Location $root
try {
    $env:AZURE_DEV_USER_AGENT = 'microsoft_foundry_skill'
    $endpoint = (azd env get-value FOUNDRY_PROJECT_ENDPOINT -e $Environment).Trim()
    if ($LASTEXITCODE) { throw 'Cannot resolve deployment environment.' }
    $token = az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv
    if ($LASTEXITCODE) { throw 'Existing Azure authentication is unavailable; no login was attempted.' }
    $headers = @{ Authorization = "Bearer $token" }
    $versionsUrl = "$endpoint/agents/$agent/versions?api-version=v1&limit=1"
    $latest = 0
    try {
        $before = Invoke-RestMethod -Headers $headers -Uri $versionsUrl
        if ($before.data) { $latest = [int]$before.data[0].version }
    }
    catch {
        if ([int]$_.Exception.Response.StatusCode -ne 404) { throw }
    }
    if ($ExpectVersion -and $latest + 1 -ne $ExpectVersion) {
        throw "Would create version $($latest + 1), not $ExpectVersion."
    }
    foreach ($setting in @(
        @('AZURE_AI_MODEL_DEPLOYMENT_NAME', $model),
        @('OPTIMIZATION_LOCAL_DIR', $localDir),
        @('CPA_APPLIED_CANDIDATE_ID', $Candidate),
        @('CPA_REASONING_EFFORT', $ReasoningEffort)
    )) {
        azd env set $setting[0] $setting[1] -e $Environment
        if ($LASTEXITCODE) { throw "Cannot set $($setting[0])." }
    }
    Write-Host "Deploying $agent release=$Release candidate=$Candidate model=$model reasoning=$ReasoningEffort"
    azd deploy $agent -e $Environment --no-prompt
    if ($LASTEXITCODE) { throw "Deployment failed ($LASTEXITCODE)." }
    $after = Invoke-RestMethod -Headers $headers -Uri $versionsUrl
    $version = $after.data[0]
    $settings = $version.definition.environment_variables
    foreach ($check in @{
        AZURE_AI_MODEL_DEPLOYMENT_NAME = $model
        OPTIMIZATION_LOCAL_DIR = $localDir
        CPA_APPLIED_CANDIDATE_ID = $Candidate
        CPA_REASONING_EFFORT = $ReasoningEffort
        CPA_MODEL_ROUTE = 'account'
    }.GetEnumerator()) {
        if ("$($settings.($check.Key))" -ne $check.Value) {
            throw "Version $($version.version) environment mismatch: $($check.Key)."
        }
    }
    $out = Join-Path $root 'runs'
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $record = @{
        agent = $agent; version = $version.version; release = $Release; candidate = $Candidate
        model = $model; reasoning_effort = $ReasoningEffort
        instructions_sha256 = (Get-FileHash (Join-Path $selectedDir 'instructions.md') -Algorithm SHA256).Hash.ToLower()
        tools_sha256 = (Get-FileHash (Join-Path $selectedDir 'tools.json') -Algorithm SHA256).Hash.ToLower()
    } | ConvertTo-Json
    $record | Set-Content (Join-Path $out "deployment-$($version.version).json")
    $record
}
finally { Pop-Location }
