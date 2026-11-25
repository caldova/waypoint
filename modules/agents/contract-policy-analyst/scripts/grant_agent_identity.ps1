param(
    [string]$Environment = 'contract-policy-analyst',
    [ValidatePattern('/blobServices/default/containers/cpa-eval-audits$')]
    [string]$AuditContainerResourceId = ''
)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $env:AZURE_DEV_USER_AGENT = 'microsoft_foundry_skill'
    $projectId = (azd env get-value AZURE_AI_PROJECT_ID -e $Environment).Trim()
    if ($LASTEXITCODE) { throw 'Cannot resolve project ID.' }
    $accountId = $projectId -replace '/projects/[^/]+$', ''
    $endpoint = (azd env get-value FOUNDRY_PROJECT_ENDPOINT -e $Environment).Trim()
    if ($LASTEXITCODE) { throw 'Cannot resolve project endpoint.' }
    $token = az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv
    if ($LASTEXITCODE) { throw 'Existing authentication unavailable; no login attempted.' }
    $agent = Invoke-RestMethod -Headers @{Authorization = "Bearer $token"} `
        -Uri "$endpoint/agents/contract-policy-analyst?api-version=v1"
    $principal = $agent.instance_identity.principal_id
    if (-not $principal) { throw 'No hosted analyst instance identity.' }
    $grants = @(
        @{role = '53ca6127-db72-4b80-b1b0-d745d6d5456d'; scope = $projectId; name = 'Foundry User'},
        @{role = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'; scope = $accountId; name = 'Cognitive Services OpenAI User'}
    )
    if ($AuditContainerResourceId) {
        $grants += @{
            role = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
            scope = $AuditContainerResourceId
            name = 'Storage Blob Data Contributor (private evaluation container only)'
        }
    }
    foreach ($grant in $grants) {
        az role assignment create --assignee-object-id $principal `
            --assignee-principal-type ServicePrincipal --role $grant.role `
            --scope $grant.scope --only-show-errors | Out-Null
        if ($LASTEXITCODE) { throw "Grant failed: $($grant.name)." }
        Write-Host "Granted $($grant.name) to hosted analyst identity."
    }
}
finally { Pop-Location }
