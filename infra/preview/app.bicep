// One Waypoint web PR preview: container app `web-pr-<number>` in the preview
// environment. Deployed on every push by tools/deploy/scripts/preview_web.sh;
// redeploying with a new image updates it in place.

targetScope = 'resourceGroup'

@description('Pull request number.')
@minValue(1)
param prNumber int

@description('Image to run, from the preview registry.')
param image string

@description('Name of the preview registry the image lives in.')
param registryName string

@description('API the web server proxies /api to (the shared production API).')
param apiUrl string

@description('Client ID of the preview sign-in app (waypoint-preview-web).')
param msalClientId string

param msalTenantId string

@description('Production API scope, e.g. api://<waypoint>/user_impersonation.')
param msalApiScope string

@description('owner/name, for tagging.')
param repository string = ''

@description('Region of the preview Container Apps environment (it can differ from the resource group).')
param location string = resourceGroup().location

var name = 'web-pr-${prNumber}'

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: 'waypoint-preview-env'
}

resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'waypoint-preview-pull'
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: {
    'waypoint-preview': 'pr'
    'waypoint-pr': string(prNumber)
    'waypoint-repository': repository
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${pullIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
      }
      registries: [
        {
          server: registry.properties.loginServer
          identity: pullIdentity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'NODE_ENV', value: 'production' }
            { name: 'PORT', value: '8000' }
            { name: 'API_ENDPOINT_HTTP', value: apiUrl }
            { name: 'WAYPOINT_MSAL_ENABLED', value: 'true' }
            { name: 'WAYPOINT_MSAL_TENANT_ID', value: msalTenantId }
            { name: 'WAYPOINT_MSAL_CLIENT_ID', value: msalClientId }
            { name: 'WAYPOINT_MSAL_API_SCOPE', value: msalApiScope }
            { name: 'WAYPOINT_MSAL_REDIRECT_URI', value: 'https://${name}.${environment.properties.defaultDomain}/login' }
          ]
        }
      ]
      // Scale to zero: an idle preview costs nothing.
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output url string = 'https://${app.properties.configuration.ingress.fqdn}'
