// Waypoint web PR previews: everything the one-time setup creates, declared.
//
//   - The isolated preview resource group and its resources (resources.bicep).
//   - waypoint-preview-web: a preview-only sign-in (SPA) app with admin consent to
//     the production API's user_impersonation scope and basic sign-in scopes.
//     Per-PR redirect URIs are added to THIS app, never to the production app.
//   - waypoint-preview-deployer: the GitHub OIDC identity for the `preview`
//     environment, with Contributor on the preview resource group only and
//     Graph Application.ReadWrite.OwnedBy limited to the app it owns (the
//     preview sign-in app), so it can manage per-PR redirect URIs.
//
// Deploy with tools/deploy/scripts/preview_setup.sh, which derives the inputs
// from production and creates the `preview` GitHub Environment.

targetScope = 'subscription'

extension microsoftGraphV1

@description('Name of the isolated preview resource group.')
param resourceGroupName string = 'waypoint-preview-rg'

@description('Region for the preview resource group, registry, and identity.')
param location string

@description('Region for the Container Apps environment. Override when the main region has no capacity.')
param environmentLocation string = location

@description('Client (app) ID of the production `waypoint` API app registration.')
param apiAppId string

@description('Exact GitHub OIDC subject for the `preview` environment, e.g. repo:owner/name:environment:preview.')
param githubOidcSubject string

@description('Redirect URIs already on the preview sign-in app (one per open PR preview), kept on redeploy.')
param existingRedirectUris array = []

var managedTag = 'waypoint-preview-managed'
var graphAppId = '00000003-0000-0000-c000-000000000000'
var graphSignInScopes = ['User.Read', 'openid', 'profile', 'offline_access']

resource graphSp 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: graphAppId
}

resource apiSp 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: apiAppId
}

// ---- deployer (GitHub OIDC) --------------------------------------------------

resource deployerApp 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: 'waypoint-preview-deployer'
  displayName: 'waypoint-preview-deployer'
  signInAudience: 'AzureADMyOrg'
  tags: [managedTag]
}

// Graph child resources are keyed '<parent uniqueName>/<name>'.
resource githubPreview 'Microsoft.Graph/applications/federatedIdentityCredentials@v1.0' = {
  name: '${deployerApp.uniqueName}/github-preview'
  description: 'Waypoint web PR previews'
  issuer: 'https://token.actions.githubusercontent.com'
  subject: githubOidcSubject
  audiences: ['api://AzureADTokenExchange']
}

resource deployerSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: deployerApp.appId
}

resource deployerManagesOwnedApps 'Microsoft.Graph/appRoleAssignedTo@v1.0' = {
  principalId: deployerSp.id
  resourceId: graphSp.id
  appRoleId: filter(graphSp.appRoles, role => role.value == 'Application.ReadWrite.OwnedBy')[0].id
}

// ---- preview sign-in app ------------------------------------------------------

resource previewWebApp 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: 'waypoint-preview-web'
  displayName: 'waypoint-preview-web'
  signInAudience: 'AzureADMyOrg'
  tags: [managedTag]
  spa: {
    redirectUris: existingRedirectUris
  }
  requiredResourceAccess: [
    {
      resourceAppId: apiAppId
      resourceAccess: [
        {
          id: filter(apiSp.oauth2PermissionScopes, scope => scope.value == 'user_impersonation')[0].id
          type: 'Scope'
        }
      ]
    }
    {
      resourceAppId: graphAppId
      resourceAccess: map(graphSignInScopes, name => {
        id: filter(graphSp.oauth2PermissionScopes, scope => scope.value == name)[0].id
        type: 'Scope'
      })
    }
  ]
  owners: {
    relationshipSemantics: 'append'
    relationships: [deployerSp.id]
  }
}

resource previewWebSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: previewWebApp.appId
}

// Admin consent, so reviewers aren't asked to consent on first sign-in.
resource apiConsent 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = {
  clientId: previewWebSp.id
  resourceId: apiSp.id
  consentType: 'AllPrincipals'
  scope: 'user_impersonation'
}

resource graphConsent 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = {
  clientId: previewWebSp.id
  resourceId: graphSp.id
  consentType: 'AllPrincipals'
  scope: join(graphSignInScopes, ' ')
}

// ---- Azure resources --------------------------------------------------------

resource previewGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    'waypoint-preview': 'environment'
  }
}

module resources 'resources.bicep' = {
  name: 'waypoint-preview-resources'
  scope: previewGroup
  params: {
    location: location
    environmentLocation: environmentLocation
    deployerPrincipalId: deployerSp.id
  }
}

output resourceGroupName string = previewGroup.name
output deployerClientId string = deployerApp.appId
output previewWebClientId string = previewWebApp.appId
output environmentDefaultDomain string = resources.outputs.environmentDefaultDomain
