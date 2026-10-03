#!/usr/bin/env pwsh
# Grants the contracts agent's runtime identities the project roles they need.
# Manual step today (see README "Runtime identities and roles"); safe to re-run.
#
#   AGENT_CONTRACTS_INSTANCE_IDENTITY_PRINCIPAL_ID  hosted instance identity (Responses/Invocations turns); set by azd
#   CONTRACTS_MAILBOX_AGENT_ID                      Agent 365 agent identity (Teams/Activity turns); set after the agent is hired
#
# Foundry User (data plane, project scope) lets the agent read its own definition
# for /version and call the project toolbox. Waypoint.Write (app role on the
# Waypoint API, from WAYPOINT_API_SCOPE) lets it call the API; requires Graph
# rights to assign app roles (API app owner or Cloud Application Administrator).

$ErrorActionPreference = 'Stop'

function Get-EnvValue([string] $name) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if (-not $value) {
        $line = azd env get-values 2>$null | Where-Object { $_ -like "$name=*" } | Select-Object -First 1
        if ($line) { $value = $line.Split('=', 2)[1].Trim('"') }
    }
    return $value
}

$scope = Get-EnvValue 'AZURE_AI_PROJECT_ID'
if (-not $scope) {
    Write-Warning 'AZURE_AI_PROJECT_ID is not set; skipping contracts role grants.'
    return
}

$role = 'Foundry User'
$principals = [ordered]@{
    'hosted instance identity' = Get-EnvValue 'AGENT_CONTRACTS_INSTANCE_IDENTITY_PRINCIPAL_ID'
    'Agent 365 agent identity' = Get-EnvValue 'CONTRACTS_MAILBOX_AGENT_ID'
}

$failed = $false
foreach ($entry in $principals.GetEnumerator()) {
    if (-not $entry.Value) {
        Write-Warning "$($entry.Key): id not set; skipping."
        continue
    }
    $existing = @(az role assignment list --scope $scope --assignee-object-id $entry.Value --role $role --query '[].id' -o tsv)
    if ($LASTEXITCODE -eq 0 -and $existing.Count -gt 0 -and $existing[0]) {
        Write-Host "$($entry.Key): $role already granted."
        continue
    }
    az role assignment create --scope $scope --role $role `
        --assignee-object-id $entry.Value --assignee-principal-type ServicePrincipal `
        --only-show-errors --output none
    if ($LASTEXITCODE -eq 0) {
        Write-Host "$($entry.Key): granted $role (allow 5-10 minutes to propagate)."
    } else {
        Write-Warning "$($entry.Key): failed to grant $role. The deployer needs Owner or User Access Administrator on the project."
        $failed = $true
    }
}

$apiScope = Get-EnvValue 'WAYPOINT_API_SCOPE'
$apiAppId = if ($apiScope -match 'api://([0-9a-fA-F-]{36})') { $Matches[1] }
if (-not $apiAppId) {
    Write-Warning 'WAYPOINT_API_SCOPE is not an api://<app-id> scope; skipping Waypoint app role grants.'
} else {
    $apiRole = 'Waypoint.Write'
    # Quote URLs: on Windows az runs through cmd.exe, which breaks on `$select` and parentheses.
    $sp = az rest --method get --url "`"https://graph.microsoft.com/v1.0/servicePrincipals(appId='$apiAppId')?`$select=id,appRoles`"" | ConvertFrom-Json
    $roleId = ($sp.appRoles | Where-Object value -eq $apiRole).id
    $assigned = (az rest --method get --url "`"https://graph.microsoft.com/v1.0/servicePrincipals/$($sp.id)/appRoleAssignedTo?`$top=999`"" | ConvertFrom-Json).value
    foreach ($entry in $principals.GetEnumerator()) {
        if (-not $entry.Value) { continue }
        if ($assigned | Where-Object { $_.principalId -eq $entry.Value -and $_.appRoleId -eq $roleId }) {
            Write-Host "$($entry.Key): $apiRole already granted."
            continue
        }
        $body = New-TemporaryFile
        Set-Content $body (@{ principalId = $entry.Value; resourceId = $sp.id; appRoleId = $roleId } | ConvertTo-Json -Compress)
        az rest --method post --url "https://graph.microsoft.com/v1.0/servicePrincipals/$($sp.id)/appRoleAssignedTo" `
            --body "@$body" --headers 'Content-Type=application/json' --output none
        $ok = $LASTEXITCODE -eq 0
        Remove-Item $body
        if ($ok) {
            Write-Host "$($entry.Key): granted $apiRole."
        } else {
            Write-Warning "$($entry.Key): failed to grant $apiRole."
            $failed = $true
        }
    }
}

if ($failed) { exit 1 }
