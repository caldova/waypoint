<#
.SYNOPSIS
  Deploy one contract-evidence-analyst version (one arm) with exactly one model, declared truthfully.

.DESCRIPTION
  Adapted from Alaska's alaska-ata-agent deploy_version.ps1. Sets the per-version azd env (config
  selection, model read from that config's metadata.yaml, pinned reasoning effort), runs
  `azd deploy contract-evidence-analyst` from this standalone azd project (never the root azure.yaml),
  then reads the new version back and checks its env.

  -Release baseline     .agent_configs/baseline (minimal honest starter prompt) on gpt-6-astra
  -Release <arm>        releases/<arm>/baseline, e.g. optimized (applied optimizer candidate on the teacher),
                        mai2-base (optimized prompt on untuned MAI-2), mai2-rft (optimized prompt on tuned MAI-2)

.EXAMPLE
  pwsh scripts/deploy_version.ps1 -Release baseline -ReasoningEffort low -ExpectVersion 1
#>
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9-]*$')][string]$Release,
    [Parameter(Mandatory)][ValidateSet('none', 'minimal', 'low', 'medium', 'high')][string]$ReasoningEffort,
    [int]$ExpectVersion = 0,
    [string]$EnvName = 'contract-evidence-analyst'
)
$ErrorActionPreference = 'Stop'
$agent = 'contract-evidence-analyst'
$root = Split-Path $PSScriptRoot -Parent

if ($Release -eq 'baseline') { $localDir = ''; $configDir = Join-Path $root '.agent_configs/baseline' }
else { $localDir = "releases/$Release"; $configDir = Join-Path $root "releases/$Release/baseline" }
$metadata = Join-Path $configDir 'metadata.yaml'
if (-not (Test-Path $metadata)) { throw "no config at $configDir" }
$model = ((Get-Content $metadata | Where-Object { $_ -match '^model:\s*(\S+)' } | Select-Object -First 1) -replace '^model:\s*', '').Trim()
if (-not $model) { throw "$metadata declares no model" }

Push-Location $root
try {
    $env:AZURE_DEV_USER_AGENT = 'microsoft_foundry_skill'
    $endpoint = (azd env get-value FOUNDRY_PROJECT_ENDPOINT -e $EnvName).Trim()
    $before = az rest --url "$endpoint/agents/$agent/versions" --uri-parameters api-version=v1 limit=1 --resource https://ai.azure.com 2>$null | ConvertFrom-Json
    $latest = if ($before.data) { [int]$before.data[0].version } else { 0 }
    if ($ExpectVersion -and $latest + 1 -ne $ExpectVersion) {
        throw "latest $agent version is $latest; deploying would create v$($latest + 1), not v$ExpectVersion"
    }

    azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME $model -e $EnvName
    azd env set OPTIMIZATION_CANDIDATE_ID '' -e $EnvName
    azd env set OPTIMIZATION_LOCAL_DIR $localDir -e $EnvName
    azd env set CEA_REASONING_EFFORT $ReasoningEffort -e $EnvName
    Write-Host "deploy $Release -> model=$model local_dir='$localDir' reasoning=$ReasoningEffort"
    # remote_build uploads the folder; keep local venvs/caches out of it.
    Remove-Item -Recurse -Force .venv, .pytest_cache -ErrorAction SilentlyContinue
    azd deploy $agent -e $EnvName --no-prompt
    if ($LASTEXITCODE) { throw "azd deploy failed ($LASTEXITCODE)" }

    $after = az rest --url "$endpoint/agents/$agent/versions" --uri-parameters api-version=v1 limit=1 --resource https://ai.azure.com | ConvertFrom-Json
    $v = $after.data[0]
    $envs = $v.definition.environment_variables
    $checks = @{
        AZURE_AI_MODEL_DEPLOYMENT_NAME = $model; OPTIMIZATION_LOCAL_DIR = $localDir
        CEA_REASONING_EFFORT = $ReasoningEffort; CEA_MODEL_ROUTE = 'account'
    }
    foreach ($k in $checks.Keys) {
        $actual = "$($envs.$k)"
        if ($actual -ne $checks[$k]) { throw "v$($v.version): $k='$actual', expected '$($checks[$k])'" }
    }
    $instr = Get-Content -Raw (Join-Path $configDir 'instructions.md')
    $sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($instr))).Replace('-', '').ToLower()
    [pscustomobject]@{ agent = $agent; version = $v.version; release = $Release; model = $model
        local_dir = $localDir; reasoning_effort = $ReasoningEffort; instructions_sha256 = $sha } | ConvertTo-Json
}
finally { Pop-Location }
