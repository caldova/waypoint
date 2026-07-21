# GitHub Actions OIDC setup

Waypoint's root deployment workflow authenticates to Azure with GitHub OIDC.
No Azure client secret is stored in GitHub.

This document covers the monorepo deployment identity. The canonical workflow is
`/.github/workflows/deploy.yml`; module-local workflows are not the one-click
deployment entry point.

## Prerequisites

- Azure CLI authenticated as a user who can create app registrations, service
  principals, and role assignments
- GitHub CLI authenticated with repository administrator access
- `jq`
- Owner, or Contributor plus User Access Administrator, on the target
  subscription

The bootstrap also grants the least-privilege Microsoft Graph application
permission needed for the deployment identity to create or update the Waypoint
MSAL application and makes the deployment identity an owner of that
application.

## Bootstrap

Run from the repository root:

```bash
az login
gh auth login

tools/deploy/scripts/oidc.sh \
  --owner caldova \
  --repo waypoint \
  --subscription-id "$(az account show --query id -o tsv)" \
  --app-name waypoint-gha-oidc \
  --branch main \
  --pull-request
```

The script is idempotent. It creates or reuses:

1. The Entra application and service principal.
2. A federated credential for `main`.
3. A federated credential for pull-request validation.
4. Contributor and User Access Administrator assignments on the subscription.
5. The Graph grant and Waypoint app ownership needed for MSAL reconciliation.
6. The GitHub repository configuration consumed by the root workflow.

Use `--environment <name>` instead of the branch subject when deployment is
gated by a GitHub Environment. Use `--no-pull-request` only if pull-request jobs
must not authenticate to Azure.

## What the workflow reads

The deployment expects these repository variables:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `AZURE_LOCATION`

The bootstrap writes the supported repository configuration by default. Use
`--no-set-repo-config` only when an administrator will set the values manually.

## Security notes

- OIDC federated credentials are scoped to the configured repository subject.
- The workflow's Azure identity is separate from the Waypoint human-login app.
- Runtime API keys and PostgreSQL passwords are generated in Key Vault, not
  stored in GitHub.
- Never paste tenant IDs, subscription IDs, object IDs, tokens, or generated
  secrets into documentation or committed output.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `AADSTS700213` or no matching federated identity | Rerun the bootstrap with the same owner, repository, branch or environment, and pull-request setting used by the workflow. |
| Role-assignment failure | Confirm the signed-in bootstrap user has Owner, or Contributor plus User Access Administrator, at subscription scope. |
| GitHub configuration write fails | Confirm `gh auth status` and repository admin access, or rerun with `--no-set-repo-config` and set the printed values manually. |
| MSAL reconciliation fails | Confirm the Graph grant was not disabled and the deployment identity owns the Waypoint app registration. |

See the canonical [Azure deployment guide](../../../docs/deployment.md) for the
full workflow and environment inputs.
