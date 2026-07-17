targetScope = 'resourceGroup'

@description('Name of the AI Services account that will own the Foundry project.')
param accountName string

@description('Azure region for the AI Services account.')
param location string

@description('Object id of the deployment principal.')
param principalId string

@description('Tags applied to the AI Services account.')
param tags object = {}

var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var azureAIAccountOwnerRoleId = 'e47c6f54-e4a2-4754-9501-8e0985b135e1'

resource account 'Microsoft.CognitiveServices/accounts@2025-09-01' = {
  name: accountName
  location: location
  tags: tags
  sku: {
    name: 'S0'
  }
  kind: 'AIServices'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: accountName
    networkAcls: {
      defaultAction: 'Allow'
      virtualNetworkRules: []
      ipRules: []
    }
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource deploymentPrincipalFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, foundryUserRoleId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      foundryUserRoleId
    )
  }
}

resource deploymentPrincipalAccountOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, azureAIAccountOwnerRoleId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      azureAIAccountOwnerRoleId
    )
  }
}

output accountId string = account.id
output accountName string = account.name
