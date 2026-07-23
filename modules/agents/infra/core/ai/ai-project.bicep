targetScope = 'resourceGroup'

@description('Tags that will be applied to all resources')
param tags object = {}

@description('Main location for the resources')
param location string

var resourceToken = uniqueString(subscription().id, resourceGroup().id, location)

@description('Name of the project')
param aiFoundryProjectName string

@description('Id of the user or app to assign application roles')
param principalId string

@description('Principal type of user or app')
param principalType string

@description('Optional. Additional admin principals (users or SPs) to grant full Foundry data-plane access. Each entry: { principalId, principalType }. Use to wire peer admins (e.g. teammates) at provision time.')
param additionalAdmins array = []

@description('Optional. Name of an existing AI Services account in the current resource group. If not provided, a new one will be created.')
param existingAiAccountName string = ''

@description('List of connections to provision')
param connections array = []

@secure()
@description('Map of connection name to credentials object. Kept as @secure to prevent secrets from appearing in deployment logs. Example: { "my-conn": { "key": "secret" } }')
param connectionCredentials object = {}

@description('Also provision dependent resources and connect to the project')
param additionalDependentResources dependentResourcesType

@description('Enable monitoring via appinsights and log analytics')
param enableMonitoring bool = true

@description('Enable hosted agent deployment')
param enableHostedAgents bool = false

@description('Enable the capability host for agent conversations. When false and hosted agents are enabled, the capability host is not created (v2 hosted agents handle storage automatically).')
param enableCapabilityHost bool = true

@description('Optional. Existing container registry resource ID. If provided, a connection will be created to this ACR instead of creating a new one.')
param existingContainerRegistryResourceId string = ''

@description('Optional. Existing container registry login server (e.g., myregistry.azurecr.io). Required if existingContainerRegistryResourceId is provided.')
param existingContainerRegistryEndpoint string = ''

@description('Optional. Name of an existing ACR connection on the Foundry project. If provided, no new ACR or connection will be created.')
param existingAcrConnectionName string = ''

@description('Optional. Existing Application Insights connection string. If provided, a connection will be created but no new App Insights resource.')
param existingApplicationInsightsConnectionString string = ''

@description('Optional. Existing Application Insights resource ID. Used for connection metadata when providing an existing App Insights.')
param existingApplicationInsightsResourceId string = ''

@description('Optional. Name of an existing Application Insights connection on the Foundry project. If provided, no new App Insights or connection will be created.')
param existingAppInsightsConnectionName string = ''

// Load abbreviations
var abbrs = loadJsonContent('../../abbreviations.json')

// Determine which resources to create based on connections
var hasStorageConnection = length(filter(additionalDependentResources, conn => conn.resource == 'storage')) > 0
var hasAcrConnection = length(filter(additionalDependentResources, conn => conn.resource == 'registry')) > 0
var hasExistingAcr = !empty(existingContainerRegistryResourceId)
var hasExistingAcrConnection = !empty(existingAcrConnectionName)
var hasExistingAppInsightsConnection = !empty(existingAppInsightsConnectionName)
var hasExistingAppInsightsConnectionString = !empty(existingApplicationInsightsConnectionString)
// Only create new App Insights resources if monitoring enabled and no existing connection/connection string
var shouldCreateAppInsights = enableMonitoring && !hasExistingAppInsightsConnection && !hasExistingAppInsightsConnectionString
var hasSearchConnection = length(filter(additionalDependentResources, conn => conn.resource == 'azure_ai_search')) > 0
var hasBingConnection = length(filter(additionalDependentResources, conn => conn.resource == 'bing_grounding')) > 0
var hasBingCustomConnection = length(filter(
  additionalDependentResources,
  conn => conn.resource == 'bing_custom_grounding'
)) > 0

// Extract connection names from ai.yaml for each resource type
var storageConnectionName = hasStorageConnection
  ? filter(additionalDependentResources, conn => conn.resource == 'storage')[0].connectionName
  : ''
var acrConnectionName = hasAcrConnection
  ? filter(additionalDependentResources, conn => conn.resource == 'registry')[0].connectionName
  : ''
var searchConnectionName = hasSearchConnection
  ? filter(additionalDependentResources, conn => conn.resource == 'azure_ai_search')[0].connectionName
  : ''
var bingConnectionName = hasBingConnection
  ? filter(additionalDependentResources, conn => conn.resource == 'bing_grounding')[0].connectionName
  : ''
var bingCustomConnectionName = hasBingCustomConnection
  ? filter(additionalDependentResources, conn => conn.resource == 'bing_custom_grounding')[0].connectionName
  : ''

// Enable monitoring via Log Analytics and Application Insights
module logAnalytics '../monitor/loganalytics.bicep' = if (shouldCreateAppInsights) {
  name: 'logAnalytics'
  params: {
    location: location
    tags: tags
    name: 'logs-${resourceToken}'
  }
}

module applicationInsights '../monitor/applicationinsights.bicep' = if (shouldCreateAppInsights) {
  name: 'applicationInsights'
  params: {
    location: location
    tags: tags
    name: 'appi-${resourceToken}'
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
    projectMIPrincipalId: aiAccount::project.identity.principalId
  }
}

// Account and project creation are bootstrapped before this template because
// the provider rejects their PUTs during full-template ARM validation even
// though the same direct resource PUTs succeed for the deployment principal.
// This module owns all managed child resources and role reconciliation.
resource aiAccount 'Microsoft.CognitiveServices/accounts@2025-09-01' existing = {
  name: !empty(existingAiAccountName) ? existingAiAccountName : 'ai-account-${resourceToken}'

  resource project 'projects@2026-03-01' existing = {
    name: aiFoundryProjectName
  }

  resource aiFoundryAccountCapabilityHost 'capabilityHosts@2025-12-01' = if (enableHostedAgents && enableCapabilityHost) {
    name: 'agents'
    properties: {
      capabilityHostKind: 'Agents'
    }
  }
}

// Create connection towards appinsights:
// - when we create a new App Insights resource, OR
// - when the user provided an existing App Insights connection string + resource ID but no existing connection name
// Both cases are merged into a single resource to avoid duplicate ARM resource definitions (which fail deployment).
var shouldCreateExistingAppInsightsConnection = enableMonitoring && hasExistingAppInsightsConnectionString && !hasExistingAppInsightsConnection && !empty(existingApplicationInsightsResourceId)
var shouldCreateAppInsightsConnection = shouldCreateAppInsights || shouldCreateExistingAppInsightsConnection

resource appInsightConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = if (shouldCreateAppInsightsConnection) {
  parent: aiAccount::project
  name: 'appi-${resourceToken}'
  properties: {
    category: 'AppInsights'
    target: shouldCreateAppInsights ? applicationInsights.outputs.id : existingApplicationInsightsResourceId
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: shouldCreateAppInsights
        ? applicationInsights.outputs.connectionString
        : existingApplicationInsightsConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: shouldCreateAppInsights ? applicationInsights.outputs.id : existingApplicationInsightsResourceId
    }
  }
}

// Create additional connections from ai.yaml configuration
module aiConnections './connection.bicep' = [
  for (connection, index) in connections: {
    name: 'connection-${connection.name}'
    params: {
      aiServicesAccountName: aiAccount.name
      aiProjectName: aiAccount::project.name
      connectionConfig: connection
      credentials: connectionCredentials[?connection.name] ?? {}
    }
  }
]

// ---------------------------------------------------------------------------
// Foundry data-plane RBAC for humans / CI service principals.
//
// History note: granting only `Foundry User` (53ca6127) at project scope was
// not enough in practice — the Foundry portal Playground hit PermissionDenied
// on `Microsoft.CognitiveServices/accounts/AIServices/agents/read` and
// `projects/storage/*`. The fix is to grant both:
//   - Foundry User                            (project scope, data actions
//                                              for agent + storage reads)
//   - Foundry Project Manager                 (account scope, publish hosted
//                                              agents + limited role management)
// at the ACCOUNT scope. Foundry Account Owner is not sufficient for publishing
// hosted agents because it lacks the required project data actions.
//
// `additionalAdmins` repeats the same two grants for peer admins so you do
// not have to bootstrap each teammate by hand. Each entry must be
// `{ principalId: '<oid>', principalType: 'User' | 'ServicePrincipal' | 'Group' }`.
// ---------------------------------------------------------------------------

var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User
var foundryProjectManagerRoleId = 'eadc314b-1a2d-4efa-be10-5d325db5065e' // Foundry Project Manager
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services User (data-plane: Content Safety, OpenAI, etc.)

resource localUserFoundryUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccount
  name: guid(aiAccount.id, principalId, foundryUserRoleId)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

resource localUserProjectManagerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccount
  name: guid(aiAccount.id, principalId, foundryProjectManagerRoleId)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', foundryProjectManagerRoleId)
  }
}

resource additionalAdminFoundryUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for admin in additionalAdmins: {
    scope: aiAccount
    name: guid(aiAccount.id, admin.principalId, foundryUserRoleId)
    properties: {
      principalId: admin.principalId
      principalType: admin.principalType
      roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
    }
  }
]

resource additionalAdminProjectManagerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for admin in additionalAdmins: {
    scope: aiAccount
    name: guid(aiAccount.id, admin.principalId, foundryProjectManagerRoleId)
    properties: {
      principalId: admin.principalId
      principalType: admin.principalType
      roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', foundryProjectManagerRoleId)
    }
  }
]

// The hosted-agent platform uses the project managed identity while creating
// agent runtime resources. Foundry User is required for that project data-plane
// access; Cognitive Services User additionally enables direct Content Safety
// and OpenAI calls from the runtime.
resource projectMIFoundryUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccount
  name: guid(aiAccount.id, aiAccount::project.id, foundryUserRoleId)
  properties: {
    principalId: aiAccount::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', foundryUserRoleId)
  }
}

resource projectMICognitiveServicesUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiAccount
  name: guid(aiAccount.id, aiAccount::project.id, cognitiveServicesUserRoleId)
  properties: {
    principalId: aiAccount::project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
  }
}

// All connections are now created directly within their respective resource modules
// using the centralized ./connection.bicep module

// Storage module - deploy if storage connection is defined in ai.yaml
module storage '../storage/storage.bicep' = if (hasStorageConnection) {
  name: 'storage'
  params: {
    location: location
    tags: tags
    resourceName: 'st${resourceToken}'
    connectionName: storageConnectionName
    principalId: principalId
    principalType: principalType
    aiServicesAccountName: aiAccount.name
    aiProjectName: aiAccount::project.name
  }
}

// Azure Container Registry module - deploy if ACR connection is defined in ai.yaml
module acr '../host/acr.bicep' = if (hasAcrConnection) {
  name: 'acr'
  params: {
    location: location
    tags: tags
    resourceName: '${abbrs.containerRegistryRegistries}${resourceToken}'
    connectionName: acrConnectionName
    principalId: principalId
    principalType: principalType
    aiServicesAccountName: aiAccount.name
    aiProjectName: aiAccount::project.name
  }
}

// Connection for existing ACR - create if user provided an existing ACR resource ID but no existing connection
module existingAcrConnection './connection.bicep' = if (hasExistingAcr && !hasExistingAcrConnection) {
  name: 'existing-acr-connection'
  params: {
    aiServicesAccountName: aiAccount.name
    aiProjectName: aiAccount::project.name
    connectionConfig: {
      name: 'acr-${resourceToken}'
      category: 'ContainerRegistry'
      target: existingContainerRegistryEndpoint
      authType: 'ManagedIdentity'
      isSharedToAll: true
      metadata: {
        ResourceId: existingContainerRegistryResourceId
      }
    }
    credentials: {
      clientId: aiAccount::project.identity.principalId
      resourceId: existingContainerRegistryResourceId
    }
  }
}

// Extract resource group name from the existing ACR resource ID
// Resource ID format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.ContainerRegistry/registries/{name}
var existingAcrResourceGroup = hasExistingAcr ? split(existingContainerRegistryResourceId, '/')[4] : ''
var existingAcrName = hasExistingAcr ? last(split(existingContainerRegistryResourceId, '/')) : ''

// Grant AcrPull role to the AI project's managed identity on the existing ACR
// This allows the hosted agents to pull images from the user-provided registry
// Note: User must have permission to assign roles on the existing ACR (Owner or User Access Administrator)
// Using a module allows scoping to a different resource group if the ACR isn't in the same RG
// Skip if connection already exists (role assignment should already be in place)
module existingAcrRoleAssignment './acr-role-assignment.bicep' = if (hasExistingAcr && !hasExistingAcrConnection) {
  name: 'existing-acr-role-assignment'
  scope: resourceGroup(existingAcrResourceGroup)
  params: {
    acrName: existingAcrName
    acrResourceId: existingContainerRegistryResourceId
    principalId: aiAccount::project.identity.principalId
  }
}

// Bing Search grounding module - deploy if Bing connection is defined in ai.yaml or parameter is enabled
module bingGrounding '../search/bing_grounding.bicep' = if (hasBingConnection) {
  name: 'bing-grounding'
  params: {
    tags: tags
    resourceName: 'bing-${resourceToken}'
    connectionName: bingConnectionName
    aiServicesAccountName: aiAccount.name
    aiProjectName: aiAccount::project.name
  }
}

// Bing Custom Search grounding module - deploy if custom Bing connection is defined in ai.yaml or parameter is enabled
module bingCustomGrounding '../search/bing_custom_grounding.bicep' = if (hasBingCustomConnection) {
  name: 'bing-custom-grounding'
  params: {
    tags: tags
    resourceName: 'bingcustom-${resourceToken}'
    connectionName: bingCustomConnectionName
    aiServicesAccountName: aiAccount.name
    aiProjectName: aiAccount::project.name
  }
}

// Azure AI Search module - deploy if search connection is defined in ai.yaml
module azureAiSearch '../search/azure_ai_search.bicep' = if (hasSearchConnection) {
  name: 'azure-ai-search'
  params: {
    tags: tags
    resourceName: 'search-${resourceToken}'
    connectionName: searchConnectionName
    knowledgeBaseName: 'contracts-kb'
    knowledgeSourceName: 'contracts-ks'
    kbMcpConnectionName: 'kb-mcp-connection'
    storageAccountResourceId: hasStorageConnection ? storage!.outputs.storageAccountId : ''
    containerName: 'knowledge'
    aiServicesAccountName: aiAccount.name
    aiProjectName: aiAccount::project.name
    principalId: principalId
    principalType: principalType
    location: location
  }
}

// Outputs
output AZURE_AI_PROJECT_ENDPOINT string = aiAccount::project.properties.endpoints['AI Foundry API']
output AZURE_OPENAI_ENDPOINT string = aiAccount.properties.endpoints['OpenAI Language Model Instance API']
output aiServicesEndpoint string = aiAccount.properties.endpoint
output accountId string = aiAccount.id
output projectId string = aiAccount::project.id
output aiServicesAccountName string = aiAccount.name
output aiServicesProjectName string = aiAccount::project.name
output aiServicesPrincipalId string = aiAccount.identity.principalId
output projectName string = aiAccount::project.name
output APPLICATIONINSIGHTS_CONNECTION_STRING string = shouldCreateAppInsights
  ? applicationInsights.outputs.connectionString
  : (hasExistingAppInsightsConnectionString ? existingApplicationInsightsConnectionString : '')
output APPLICATIONINSIGHTS_RESOURCE_ID string = shouldCreateAppInsights
  ? applicationInsights.outputs.id
  : (hasExistingAppInsightsConnectionString ? existingApplicationInsightsResourceId : '')

// Connection outputs from the connections array
output connectionIds array = [
  for (connection, index) in (connections ?? []): {
    name: aiConnections[index].outputs.connectionName
    id: aiConnections[index].outputs.connectionId
  }
]

// Grouped dependent resources outputs
output dependentResources object = {
  registry: {
    name: hasAcrConnection ? acr!.outputs.containerRegistryName : ''
    loginServer: hasAcrConnection
      ? acr!.outputs.containerRegistryLoginServer
      : ((hasExistingAcr || hasExistingAcrConnection) ? existingContainerRegistryEndpoint : '')
    resourceId: hasAcrConnection
      ? acr!.outputs.containerRegistryResourceId
      : ((hasExistingAcr || hasExistingAcrConnection) ? existingContainerRegistryResourceId : '')
    connectionName: hasAcrConnection
      ? acr!.outputs.containerRegistryConnectionName
      : (hasExistingAcrConnection ? existingAcrConnectionName : (hasExistingAcr ? 'acr-${resourceToken}' : ''))
  }
  bing_grounding: {
    name: (hasBingConnection) ? bingGrounding!.outputs.bingGroundingName : ''
    connectionName: (hasBingConnection) ? bingGrounding!.outputs.bingGroundingConnectionName : ''
    connectionId: (hasBingConnection) ? bingGrounding!.outputs.bingGroundingConnectionId : ''
  }
  bing_custom_grounding: {
    name: (hasBingCustomConnection) ? bingCustomGrounding!.outputs.bingCustomGroundingName : ''
    connectionName: (hasBingCustomConnection) ? bingCustomGrounding!.outputs.bingCustomGroundingConnectionName : ''
    connectionId: (hasBingCustomConnection) ? bingCustomGrounding!.outputs.bingCustomGroundingConnectionId : ''
  }
  search: {
    serviceName: hasSearchConnection ? azureAiSearch!.outputs.searchServiceName : ''
    serviceEndpoint: hasSearchConnection ? azureAiSearch!.outputs.searchServiceEndpoint : ''
    connectionName: hasSearchConnection ? azureAiSearch!.outputs.searchConnectionName : ''
    kbMcpConnectionName: hasSearchConnection ? azureAiSearch!.outputs.kbMcpConnectionName : ''
    knowledgeBaseName: hasSearchConnection ? azureAiSearch!.outputs.knowledgeBaseName : ''
    knowledgeSourceName: hasSearchConnection ? azureAiSearch!.outputs.knowledgeSourceName : ''
    indexerName: hasSearchConnection ? azureAiSearch!.outputs.indexerName : ''
    containerName: hasSearchConnection ? azureAiSearch!.outputs.containerName : ''
  }
  storage: {
    accountName: hasStorageConnection ? storage!.outputs.storageAccountName : ''
    connectionName: hasStorageConnection ? storage!.outputs.storageConnectionName : ''
  }
}

type dependentResourcesType = {
  @description('The type of dependent resource to create')
  resource: 'storage' | 'registry' | 'azure_ai_search' | 'bing_grounding' | 'bing_custom_grounding'

  @description('The connection name for this resource')
  connectionName: string
}[]
