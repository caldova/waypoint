# Grant the deployed contract-evidence-analyst instance identity the roles it needs (adapted from Alaska
# tools/deploy/scripts/grant_agent_identity.ps1):
#   Foundry User (project): data-plane access through the project.
#   Cognitive Services OpenAI User (account): inference on the account route (model_route.py), needed for MAI.
param(
    [string]$Agent = 'contract-evidence-analyst',
    [string]$Environment = 'contract-evidence-analyst'
)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:AZURE_DEV_USER_AGENT = 'microsoft_foundry_skill'
    $projectId = (azd env get-value AZURE_AI_PROJECT_ID -e $Environment).Trim()
    $accountId = $projectId -replace '/projects/[^/]+$', ''
    $endpoint = (azd env get-value FOUNDRY_PROJECT_ENDPOINT -e $Environment).Trim()
    $principal = (az rest --url "$endpoint/agents/$Agent" --uri-parameters api-version=v1 --resource https://ai.azure.com |
        ConvertFrom-Json).instance_identity.principal_id
    if (-not $principal) { throw "no instance identity for $Agent" }
    foreach ($grant in @(
            @{ role = '53ca6127-db72-4b80-b1b0-d745d6d5456d'; scope = $projectId; name = 'Foundry User' },
            @{ role = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'; scope = $accountId; name = 'Cognitive Services OpenAI User' })) {
        az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
            --role $grant.role --scope $grant.scope --only-show-errors | Out-Null
        if ($LASTEXITCODE) { throw "grant $($grant.name) failed" }
        Write-Host "granted $($grant.name) to $principal on $($grant.scope)"
    }
}
finally { Pop-Location }
