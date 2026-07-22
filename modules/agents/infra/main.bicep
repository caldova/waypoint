targetScope = 'subscription'
// targetScope = 'resourceGroup'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@minLength(1)
@maxLength(90)
@description('Name of the resource group to use or create')
param resourceGroupName string = 'rg-${environmentName}'

@description('Location of the resource group container. This may differ from the Foundry resource location.')
param resourceGroupLocation string = location

// Restricted locations to match list from
// https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/responses?tabs=python-key#region-availability
@minLength(1)
@description('Primary location for all resources')
@allowed([
  'australiaeast'
  'brazilsouth'
  'canadacentral'
  'canadaeast'
  'eastus'
  'eastus2'
  'francecentral'
  'germanywestcentral'
  'italynorth'
  'japaneast'
  'koreacentral'
  'northcentralus'
  'norwayeast'
  'polandcentral'
  'southafricanorth'
  'southcentralus'
  'southeastasia'
  'southindia'
  'spaincentral'
  'swedencentral'
  'switzerlandnorth'
  'uaenorth'
  'uksouth'
  'westus'
  'westus2'
  'westus3'
])
param location string

param aiDeploymentsLocation string

@description('Id of the user or app to assign application roles')
param principalId string

@description('Principal type of user or app')
param principalType string

@description('Optional JSON array of additional admin principals to auto-grant Foundry User + Azure AI Account Owner on the AI account. Each entry: { "principalId": "<oid>", "principalType": "User" | "ServicePrincipal" | "Group" }. Sourced from the ADDITIONAL_ADMINS azd env var; defaults to empty.')
param additionalAdminsJson string = '[]'

var additionalAdmins = json(additionalAdminsJson)

@description('Optional. Name of an existing AI Services account within the resource group. If not provided, a new one will be created.')
param aiFoundryResourceName string = ''

@description('Optional. Name of the AI Foundry project. If not provided, a default name will be used.')
param aiFoundryProjectName string = 'ai-project-${environmentName}'

@description('List of model deployments. ADVANCED: leave empty to use the modelDeploymentName / modelName / modelVersion / modelSku* scalars below (the common case). Provide an explicit JSON array only when you need to deploy multiple models in one env. When non-empty, the scalar defaults are ignored.')
param aiProjectDeploymentsJson string = '[]'

// ---------------------------------------------------------------------------
// Default model deployments (single source of truth)
//
// Most envs need one chat model and one embedding model: agents use the chat
// deployment, and Foundry/Search knowledge-base initialization uses the
// embedding deployment. Expose the fields as typed scalars with defaults so a
// fresh `azd provision` always deploys known-good models, and any agent that
// reads AZURE_AI_MODEL_DEPLOYMENT_NAME (set as a bicep output below) picks up
// the chat deployment name. Override per-env with:
//   azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME <name>
//   azd env set MODEL_NAME <catalog-name>
//   azd env set MODEL_VERSION <YYYY-MM-DD>
//   azd env set MODEL_SKU_NAME <GlobalStandard|Standard|...>
//   azd env set MODEL_CAPACITY <int>
//   azd env set AZURE_AI_EMBEDDING_DEPLOYMENT_NAME <name>
//   azd env set EMBEDDING_MODEL_NAME <catalog-name>
//   azd env set EMBEDDING_MODEL_VERSION <version>
//   azd env set EMBEDDING_MODEL_SKU_NAME <Standard|...>
//   azd env set EMBEDDING_MODEL_CAPACITY <int>
//
// To deploy multiple models in one env, set AI_PROJECT_DEPLOYMENTS to a JSON
// array (legacy escape hatch). When that is non-empty, these scalars are
// ignored entirely.
// ---------------------------------------------------------------------------
@description('Name of the default chat model deployment exposed to agents as AZURE_AI_MODEL_DEPLOYMENT_NAME. Conventionally equal to modelName.')
param modelDeploymentName string = 'gpt-5.5'

@description('Catalog name of the default chat model (e.g. gpt-5-mini).')
param modelName string = 'gpt-5.5'

@description('Model version date suffix (catalog-specific, e.g. 2025-08-07 for gpt-5-mini).')
param modelVersion string = '2026-04-24'

@description('Model format. "OpenAI" for the OpenAI family.')
param modelFormat string = 'OpenAI'

@description('SKU name for the model deployment (e.g. GlobalStandard, Standard, ProvisionedManaged).')
param modelSkuName string = 'GlobalStandard'

@description('TPM capacity for the model deployment, in the SKUs native unit. Passed as a string for azd-param-file compatibility; coerced to int when used.')
param modelCapacity string = '200'

@description('Name of the embedding model deployment used by contracts-kb knowledge-base initialization.')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Catalog name of the embedding model used by contracts-kb knowledge-base initialization.')
param embeddingModelName string = 'text-embedding-3-large'

@description('Model format for the embedding deployment.')
param embeddingModelFormat string = 'OpenAI'

@description('Model version for the embedding deployment.')
param embeddingModelVersion string = '1'

@description('SKU name for the embedding deployment.')
param embeddingModelSkuName string = 'Standard'

@description('TPM capacity for the embedding deployment, in the SKUs native unit. Passed as a string for azd-param-file compatibility; coerced to int when used.')
param embeddingModelCapacity string = '50'

@description('List of connections')
param aiProjectConnectionsJson string = '[]'

@secure()
@description('JSON map of connection name to credentials object. Example: {"my-conn":{"key":"secret"}}')
param aiProjectConnectionCredentialsJson string = '{}'

@description('List of resources to create and connect to the AI project')
param aiProjectDependentResourcesJson string = '[]'

// ── Expert single-tool connections ───────────────────────────────────────────
// Each IQ expert binds to exactly ONE tool. WorkIQ binds a Foundry tool-catalog
// MCP server (provisioned below as a RemoteTool project connection). WebIQ
// (market-evidence-expert) binds the hosted WebIQ MCP server
// (https://api.microsoft.ai/v3/mcp, project connection `web-iq`) — NOT Azure
// "Grounding with Bing Search". Bing grounding is therefore no longer provisioned
// here. It can still be opted into explicitly via aiProjectDependentResourcesJson
// (resource: 'bing_grounding') if a future agent needs it.

// WorkIQ (collaboration-evidence-expert) binds three Microsoft 365 Agents
// (agent365) catalog MCP servers by exact connection name — WorkIQCopilot,
// WorkIQTeams, WorkIQSharePoint. They authenticate per-request as the signed-in
// USER (UserEntraToken) against the agent365 audience, so NO secret is stored on
// the connection. Each URL param overrides the well-known agent365 catalog
// endpoint; when left empty (the default in CI) the connection falls back to the
// known endpoint so a fresh environment provisions all three with zero manual
// input. The connection NAMES are fixed to match the agent prompt bindings.
@description('WorkIQ Microsoft 365 Copilot MCP server URL (project connection WorkIQCopilot). Empty falls back to the well-known agent365 endpoint.')
param workiqEmailMcpServerUrl string = ''

@description('WorkIQ Microsoft Teams MCP server URL (project connection WorkIQTeams). Empty falls back to the well-known agent365 endpoint.')
param workiqTeamsMcpServerUrl string = ''

@description('WorkIQ SharePoint MCP server URL (project connection WorkIQSharePoint). Empty falls back to the well-known agent365 endpoint.')
param workiqSharepointMcpServerUrl string = 'https://agent365.svc.cloud.microsoft/agents/servers/mcp_SharePointRemoteServer'

@description('Legacy WorkIQ SharePoint MCP server URL. Prefer workiqSharepointMcpServerUrl / WORKIQ_SHAREPOINT_MCP_SERVER_URL.')
param workiqMcpServerUrl string = ''

@description('Microsoft 365 Agents (agent365) token audience for the WorkIQ UserEntraToken connections.')
param workiqAgent365Audience string = 'ea9ffc3e-8a23-4a7d-836d-234d7c7565c1'

@description('Provision the three WorkIQ project connections. Standalone deployments retain the full-fleet default; the simplified root deployment disables them.')
param enableWorkiqConnections bool = true

var aiProjectDeploymentsOverride = json(aiProjectDeploymentsJson)
var defaultDeployments = [
  {
    name: modelDeploymentName
    model: {
      name: modelName
      format: modelFormat
      version: modelVersion
    }
    sku: {
      name: modelSkuName
      capacity: int(modelCapacity)
    }
  }
  {
    name: embeddingDeploymentName
    model: {
      name: embeddingModelName
      format: embeddingModelFormat
      version: embeddingModelVersion
    }
    sku: {
      name: embeddingModelSkuName
      capacity: int(embeddingModelCapacity)
    }
  }
]
// When AI_PROJECT_DEPLOYMENTS is set (non-empty JSON array), honour it verbatim;
// otherwise build chat + embedding deployments from the scalar defaults above.
var aiProjectDeployments = empty(aiProjectDeploymentsOverride) ? defaultDeployments : aiProjectDeploymentsOverride
var aiProjectConnections = json(aiProjectConnectionsJson)
var aiProjectConnectionCreds = json(aiProjectConnectionCredentialsJson)
var aiProjectDependentResources = json(aiProjectDependentResourcesJson)

@description('Enable hosted agent deployment')
param enableHostedAgents bool

@description('Enable the capability host for supporting BYO storage of agent conversations. When false and hosted agents are enabled, the capability host is not created.')
param enableCapabilityHost bool

@description('Enable Azure AI Search provisioning and the Foundry IQ knowledge-base MCP connection on the project.')
param enableSearch bool = true

@description('Enable monitoring for the AI project')
param enableMonitoring bool

@description('When true, skip Foundry project/role/connection provisioning and reference the existing project read-only. Use when pointing at an existing Foundry project via --project-id.')
param useExistingAiProject bool = false

@description('Optional. Existing container registry resource ID. If provided, no new ACR will be created and a connection to this ACR will be established.')
param existingContainerRegistryResourceId string = ''

@description('Optional. Existing container registry endpoint (login server). Required if existingContainerRegistryResourceId is provided.')
param existingContainerRegistryEndpoint string = ''

@description('Optional. Name of an existing ACR connection on the Foundry project. If provided, no new ACR or connection will be created.')
param existingAcrConnectionName string = ''

@description('Optional. Existing Application Insights connection string. If provided, a connection will be created but no new App Insights resource.')
param existingApplicationInsightsConnectionString string = ''

@description('Optional. Existing Application Insights resource ID. Used for connection metadata when providing an existing App Insights.')
param existingApplicationInsightsResourceId string = ''

@description('Optional. Name of an existing Application Insights connection on the Foundry project. If provided, no new App Insights or connection will be created.')
param existingAppInsightsConnectionName string = ''

// Tags that should be applied to all resources.
//
// Note that 'azd-service-name' tags should be applied separately to service host resources.
// Example usage:
//   tags: union(tags, { 'azd-service-name': <service name in azure.yaml> })
var tags = {
  'azd-env-name': environmentName
}

// Check if resource group exists and create it if it doesn't
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupName
  location: resourceGroupLocation
  tags: tags
}

// Build dependent resources array conditionally
// Check if ACR already exists in the user-provided array to avoid duplicates
// Also skip if user provided an existing container registry endpoint or connection name
var hasAcr = contains(map(aiProjectDependentResources, r => r.resource), 'registry')
var shouldCreateAcr = enableHostedAgents && !hasAcr && empty(existingContainerRegistryResourceId) && empty(existingAcrConnectionName)
var withAcr = shouldCreateAcr
  ? union(aiProjectDependentResources, [
      {
        resource: 'registry'
        connectionName: 'acr-${uniqueString(subscription().id, resourceGroupName, location)}'
      }
    ])
  : aiProjectDependentResources

// Add Azure AI Search to dependent resources when enableSearch is true and the
// user has not already declared it. The ai-project module also requires a
// storage connection for the search service, so include that too when missing.
var hasSearch = contains(map(withAcr, r => r.resource), 'azure_ai_search')
var hasStorage = contains(map(withAcr, r => r.resource), 'storage')
var withSearch = (enableSearch && !hasSearch)
  ? union(withAcr, [
      {
        resource: 'azure_ai_search'
        connectionName: 'azure-ai-search-connection'
      }
    ])
  : withAcr
var dependentResources = (enableSearch && !hasStorage)
  ? union(withSearch, [
      {
        resource: 'storage'
        connectionName: 'azure-storage-connection'
      }
    ])
  : withSearch

// WebIQ (market-evidence-expert) grounds on the hosted WebIQ MCP server
// (project connection `web-iq`), so Azure "Grounding with Bing Search" is no
// longer auto-provisioned. Bing grounding is only created when a caller
// explicitly declares a `bing_grounding` resource in aiProjectDependentResourcesJson.
var dependentResourcesWithBing = dependentResources

// Merge the expert MCP-server connections into the project connection list so
// the generic ai-project connections loop creates/updates them idempotently.
// These three WorkIQ connections are provisioned with the EXACT names, auth
// (UserEntraToken), audience and catalog metadata that the
// collaboration-evidence-expert prompt binds, so a fresh environment is
// self-provisioning and re-deploys are idempotent (matching PUTs).
//
// NOTE: the market-evidence-expert's `web-iq` connection (CustomKeys) stores a
// secret WebIQ API key and is therefore NOT provisioned here — doing so without
// the key would wipe it. It is supplied out-of-band / via a secret; see
// docs/FORGE_CURRENT_STATE.md.
var effectiveWorkiqSharepointMcpServerUrl = !empty(workiqSharepointMcpServerUrl)
  ? workiqSharepointMcpServerUrl
  : workiqMcpServerUrl
var workiqCopilotTarget = !empty(workiqEmailMcpServerUrl)
  ? workiqEmailMcpServerUrl
  : 'https://agent365.svc.cloud.microsoft/agents/servers/mcp_M365Copilot'
var workiqTeamsTarget = !empty(workiqTeamsMcpServerUrl)
  ? workiqTeamsMcpServerUrl
  : 'https://agent365.svc.cloud.microsoft/agents/servers/mcp_TeamsServer'
var workiqSharepointTarget = !empty(effectiveWorkiqSharepointMcpServerUrl)
  ? effectiveWorkiqSharepointMcpServerUrl
  : 'https://agent365.svc.cloud.microsoft/agents/servers/mcp_SharePointRemoteServer'
var expertMcpConnections = [
  {
    name: 'WorkIQCopilot'
    category: 'RemoteTool'
    target: workiqCopilotTarget
    authType: 'UserEntraToken'
    isSharedToAll: false
    audience: workiqAgent365Audience
    metadata: {
      toolEntityId: 'azureml://location/eastus/apiCenter/registry-prod-bl/type/tools/objectId/microsoft-copilot-chat-frontier/version/1'
      type: 'catalog_MCP'
    }
  }
  {
    name: 'WorkIQTeams'
    category: 'RemoteTool'
    target: workiqTeamsTarget
    authType: 'UserEntraToken'
    isSharedToAll: false
    audience: workiqAgent365Audience
    metadata: {
      toolEntityId: 'azureml://location/eastus/apiCenter/registry-prod-bl/type/tools/objectId/microsoft-teams-mcp-frontier/version/1'
      type: 'catalog_MCP'
    }
  }
  {
    name: 'WorkIQSharePoint'
    category: 'RemoteTool'
    target: workiqSharepointTarget
    authType: 'UserEntraToken'
    isSharedToAll: false
    audience: workiqAgent365Audience
    metadata: {
      toolEntityId: 'azureml://location/eastus/apiCenter/registry-prod-bl/type/tools/objectId/microsoft-sharepoint-mcp-frontier/version/1'
      type: 'catalog_MCP'
    }
  }
]
var allAiProjectConnections = concat(
  aiProjectConnections,
  enableWorkiqConnections ? expertMcpConnections : []
)
var allAiProjectConnectionCreds = aiProjectConnectionCreds

// AI Project module — only when creating new resources
module aiProject 'core/ai/ai-project.bicep' = if (!useExistingAiProject) {
  scope: rg
  name: 'ai-project'
  params: {
    tags: tags
    location: aiDeploymentsLocation
    aiFoundryProjectName: aiFoundryProjectName
    principalId: principalId
    principalType: principalType
    additionalAdmins: additionalAdmins
    existingAiAccountName: aiFoundryResourceName
    connections: allAiProjectConnections
    connectionCredentials: allAiProjectConnectionCreds
    additionalDependentResources: dependentResourcesWithBing
    enableMonitoring: enableMonitoring
    enableHostedAgents: enableHostedAgents
    enableCapabilityHost: enableCapabilityHost
    existingContainerRegistryResourceId: existingContainerRegistryResourceId
    existingContainerRegistryEndpoint: existingContainerRegistryEndpoint
    existingAcrConnectionName: existingAcrConnectionName
    existingApplicationInsightsConnectionString: existingApplicationInsightsConnectionString
    existingApplicationInsightsResourceId: existingApplicationInsightsResourceId
    existingAppInsightsConnectionName: existingAppInsightsConnectionName
  }
}

// Existing project module — read-only reference when reusing an existing Foundry project
module existingAiProject 'core/ai/existing-ai-project.bicep' = if (useExistingAiProject) {
  scope: rg
  name: 'existing-ai-project'
  params: {
    aiServicesAccountName: aiFoundryResourceName
    aiFoundryProjectName: aiFoundryProjectName
    existingAcrConnectionName: existingAcrConnectionName
    existingContainerRegistryEndpoint: existingContainerRegistryEndpoint
    existingContainerRegistryResourceId: existingContainerRegistryResourceId
    existingApplicationInsightsConnectionString: existingApplicationInsightsConnectionString
    existingApplicationInsightsResourceId: existingApplicationInsightsResourceId
  }
}

// ACR for existing project — create when hosted agents need a registry but the existing project has none
var shouldCreateAcrForExistingProject = useExistingAiProject && shouldCreateAcr
var acrConnectionName = 'acr-${uniqueString(subscription().id, resourceGroupName, location)}'

module acrForExistingProject 'core/host/acr.bicep' = if (shouldCreateAcrForExistingProject) {
  scope: rg
  name: 'acr-for-existing-project'
  params: {
    location: location
    tags: tags
    resourceName: 'cr${uniqueString(subscription().id, resourceGroupName, location)}'
    connectionName: acrConnectionName
    principalId: principalId
    principalType: principalType
    aiServicesAccountName: aiFoundryResourceName
    aiProjectName: aiFoundryProjectName
  }
}

// Resources
output AZURE_RESOURCE_GROUP string = resourceGroupName

// Default chat model deployment name. Surfaced as an output so the deploy
// workflow's hydrate step copies it into azd env, where each agent.yaml's
// `${AZURE_AI_MODEL_DEPLOYMENT_NAME}` placeholder gets substituted at
// container deploy time. Override per-env via `azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME ...`.
// Reads from the active deployments list (works for both the default and the
// AI_PROJECT_DEPLOYMENTS override) so agents always point at a deployment
// that actually exists in the Foundry project.
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = aiProjectDeployments[0].name
output AZURE_AI_EMBEDDING_DEPLOYMENT_NAME string = embeddingDeploymentName
output AZURE_AI_EMBEDDING_MODEL_NAME string = embeddingModelName
output CONTENT_UNDERSTANDING_ENDPOINT string = 'https://${useExistingAiProject ? existingAiProject.outputs.aiServicesAccountName : aiProject.outputs.aiServicesAccountName}.services.ai.azure.com'
output CONTENT_UNDERSTANDING_API_VERSION string = '2025-11-01'
output CONTENT_UNDERSTANDING_ANALYZER_ID string = 'prebuilt-invoice'
output CONTENT_UNDERSTANDING_SCOPE string = 'https://cognitiveservices.azure.com/.default'
output CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME string = modelDeploymentName
output CONTENT_UNDERSTANDING_COMPLETION_MODEL_NAME string = modelName

output AZURE_AI_ACCOUNT_ID string = useExistingAiProject
  ? existingAiProject.outputs.accountId
  : aiProject.outputs.accountId
output AZURE_AI_PROJECT_ID string = useExistingAiProject
  ? existingAiProject.outputs.projectId
  : aiProject.outputs.projectId
output AZURE_AI_FOUNDRY_PROJECT_ID string = useExistingAiProject
  ? existingAiProject.outputs.projectId
  : aiProject.outputs.projectId
output AZURE_AI_ACCOUNT_NAME string = useExistingAiProject
  ? existingAiProject.outputs.aiServicesAccountName
  : aiProject.outputs.aiServicesAccountName
output AZURE_AI_PROJECT_NAME string = useExistingAiProject
  ? existingAiProject.outputs.projectName
  : aiProject.outputs.projectName

// Endpoints
output AZURE_AI_PROJECT_ENDPOINT string = useExistingAiProject
  ? existingAiProject.outputs.AZURE_AI_PROJECT_ENDPOINT
  : aiProject.outputs.AZURE_AI_PROJECT_ENDPOINT
output AZURE_OPENAI_ENDPOINT string = useExistingAiProject
  ? existingAiProject.outputs.AZURE_OPENAI_ENDPOINT
  : aiProject.outputs.AZURE_OPENAI_ENDPOINT
output APPLICATIONINSIGHTS_CONNECTION_STRING string = useExistingAiProject
  ? existingAiProject.outputs.APPLICATIONINSIGHTS_CONNECTION_STRING
  : aiProject.outputs.APPLICATIONINSIGHTS_CONNECTION_STRING
output APPLICATIONINSIGHTS_RESOURCE_ID string = useExistingAiProject
  ? existingAiProject.outputs.APPLICATIONINSIGHTS_RESOURCE_ID
  : aiProject.outputs.APPLICATIONINSIGHTS_RESOURCE_ID

// Dependent Resources and Connections

// ACR
output AZURE_AI_PROJECT_ACR_CONNECTION_NAME string = shouldCreateAcrForExistingProject
  ? acrForExistingProject.outputs.containerRegistryConnectionName
  : (useExistingAiProject
      ? existingAiProject.outputs.dependentResources.registry.connectionName
      : aiProject.outputs.dependentResources.registry.connectionName)
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = shouldCreateAcrForExistingProject
  ? acrForExistingProject.outputs.containerRegistryLoginServer
  : (useExistingAiProject
      ? existingAiProject.outputs.dependentResources.registry.loginServer
      : aiProject.outputs.dependentResources.registry.loginServer)
output AZURE_CONTAINER_REGISTRY_RESOURCE_ID string = shouldCreateAcrForExistingProject
  ? acrForExistingProject.outputs.containerRegistryResourceId
  : (useExistingAiProject
      ? existingAiProject.outputs.dependentResources.registry.resourceId
      : aiProject.outputs.dependentResources.registry.resourceId)

// Bing Search
output BING_GROUNDING_CONNECTION_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.bing_grounding.connectionName
  : aiProject.outputs.dependentResources.bing_grounding.connectionName
output BING_GROUNDING_RESOURCE_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.bing_grounding.name
  : aiProject.outputs.dependentResources.bing_grounding.name
output BING_GROUNDING_CONNECTION_ID string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.bing_grounding.connectionId
  : aiProject.outputs.dependentResources.bing_grounding.connectionId

// Bing Custom Search
output BING_CUSTOM_GROUNDING_CONNECTION_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.bing_custom_grounding.connectionName
  : aiProject.outputs.dependentResources.bing_custom_grounding.connectionName
output BING_CUSTOM_GROUNDING_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.bing_custom_grounding.name
  : aiProject.outputs.dependentResources.bing_custom_grounding.name
output BING_CUSTOM_GROUNDING_CONNECTION_ID string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.bing_custom_grounding.connectionId
  : aiProject.outputs.dependentResources.bing_custom_grounding.connectionId

// Azure AI Search
output AZURE_AI_SEARCH_CONNECTION_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.connectionName
  : aiProject.outputs.dependentResources.search.connectionName
output AZURE_AI_SEARCH_SERVICE_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.serviceName
  : aiProject.outputs.dependentResources.search.serviceName
output AZURE_AI_SEARCH_SERVICE_ENDPOINT string = useExistingAiProject
  ? (!empty(existingAiProject.outputs.dependentResources.search.serviceName)
      ? 'https://${existingAiProject.outputs.dependentResources.search.serviceName}.search.windows.net'
      : '')
  : (!empty(aiProject.outputs.dependentResources.search.serviceName)
      ? 'https://${aiProject.outputs.dependentResources.search.serviceName}.search.windows.net'
      : '')
output AZURE_AI_SEARCH_KB_MCP_CONNECTION_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.kbMcpConnectionName
  : aiProject.outputs.dependentResources.search.kbMcpConnectionName
output AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.knowledgeBaseName
  : aiProject.outputs.dependentResources.search.knowledgeBaseName
output AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.knowledgeSourceName
  : aiProject.outputs.dependentResources.search.knowledgeSourceName
output AZURE_AI_SEARCH_INDEXER_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.indexerName
  : aiProject.outputs.dependentResources.search.indexerName
output AZURE_AI_SEARCH_CONTAINER_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.search.containerName
  : aiProject.outputs.dependentResources.search.containerName

// Azure Storage
output AZURE_STORAGE_CONNECTION_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.storage.connectionName
  : aiProject.outputs.dependentResources.storage.connectionName
output AZURE_STORAGE_ACCOUNT_NAME string = useExistingAiProject
  ? existingAiProject.outputs.dependentResources.storage.accountName
  : aiProject.outputs.dependentResources.storage.accountName

// Connections
output AI_PROJECT_CONNECTION_IDS_JSON string = useExistingAiProject
  ? string(existingAiProject.outputs.connectionIds)
  : string(aiProject.outputs.connectionIds)
