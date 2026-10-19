// Azure resources for Waypoint PR previews (deployed by main.bicep).
//
// Isolated from production on purpose: PR code reaches Azure through the
// preview deployer identity, which only holds Contributor on THIS resource
// group. Previews never touch the production container apps, registry, or
// Entra app registration. Per-PR container apps (app.bicep) are created and
// deleted by .github/workflows/preview-web.yml.

targetScope = 'resourceGroup'

@description('Location for all preview resources.')
param location string = resourceGroup().location

@description('Location for the Container Apps environment. Override when the main region has no capacity.')
param environmentLocation string = location

@description('Object ID of the preview deployer service principal (GitHub OIDC).')
param deployerPrincipalId string

@description('Principal type of the deployer; `User` is only for manual smoke tests.')
@allowed(['ServicePrincipal', 'User'])
param deployerPrincipalType string = 'ServicePrincipal'

@description('Short, unique suffix for globally named resources.')
param nameSuffix string = uniqueString(resourceGroup().id)

param tags object = {
  'waypoint-preview': 'environment'
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var contributorRoleId = 'b24988ac-6180-42a0-ab88-20f7382dd24c'

// Preview images only: a separate registry keeps PR builds away from the
// production image tags.
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'waypointpreview${nameSuffix}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

// Pull identity shared by every preview container app.
resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'waypoint-preview-pull'
  location: location
  tags: tags
}

resource pullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, pullIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: pullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

// Consumption-only environment: previews scale to zero, so idle PRs cost nothing.
// No Log Analytics workspace; `az containerapp logs show` still streams console logs.
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'waypoint-preview-env'
  location: environmentLocation
  tags: tags
  properties: {
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

resource deployerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, deployerPrincipalId, contributorRoleId)
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
  }
}

output environmentName string = environment.name
output environmentDefaultDomain string = environment.properties.defaultDomain
output registryName string = registry.name
output registryLoginServer string = registry.properties.loginServer
output pullIdentityId string = pullIdentity.id
