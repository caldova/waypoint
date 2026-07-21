# OneLake corpus storage

Waypoint can store synthetic corpus documents in a Microsoft Fabric OneLake
lakehouse and expose their text through the API context gateway.

OneLake storage is part of the default full deployment, but it is independent
of the FabricIQ evidence lane. FabricIQ remains opt-in.

## Architecture

| Concern | Implementation |
| --- | --- |
| Fabric capacity | `infra/fabric-capacity.bicep` |
| Workspace, lakehouse, and role grants | `infra/scripts/provision-fabric.sh` |
| Corpus upload | Root deployment using the corpus module's `ledgerfield upload-onelake` command |
| Runtime reads | `api/app/common/onelake.py` |
| Configuration | `APP_ONELAKE_ACCOUNT_URL`, `APP_ONELAKE_WORKSPACE`, `APP_ONELAKE_LAKEHOUSE`, `APP_ONELAKE_CORPUS_PREFIX` |

The Waypoint API managed identity must be a Fabric workspace Member. Fabric
workspace roles, not Azure RBAC alone, authorize OneLake reads.

## Graceful fallback

OneLake is optional for local development. If no workspace is configured,
document endpoints preserve metadata and return URI-only content instead of
failing the request.

## Local development

From `apps/waypoint`:

```bash
az login
cp api/.env.example api/.env
./infra/scripts/onelake-local-env.sh
```

The helper resolves the workspace by display name and idempotently updates the
gitignored `api/.env`. It does not create or modify Fabric resources.

Restart the API after updating the environment.

## Deployment

The root `/.github/workflows/deploy.yml` is the canonical path. With
`fabric_provision_enabled=true`, it:

1. Provisions or reconciles the capacity, workspace, and lakehouse.
2. Grants the required workspace roles.
3. Configures the API's `APP_ONELAKE_*` settings.
4. Uploads the corpus after the workspace is ready.
5. Includes the Fabric and upload stages in acceptance evidence.

The full default path and an unchanged rerun have been validated.

## Layout contract

The corpus module writes the following stable layout:

```text
Files/corpus/
  contracts/
  policies/
  invoices/
  evidence/

Tables/
  suppliers/
  invoices/
  invoice_lines/
  reconciliation_findings/
```

Supplier-facing documents remain separate from scenario metadata and expected
findings.

## Cost control

Fabric capacity bills while active. Use
`infra/scripts/fabric-capacity-control.sh` to inspect, suspend, resume, or scale
the capacity. Suspending capacity can make OneLake reads unavailable; Waypoint
then uses its URI-only fallback.

## FabricIQ distinction

The OneLake corpus is storage. It does not prove that the optional
`operations-data-expert` is grounded in a live Fabric Data Agent. See
[fabric-iq.md](fabric-iq.md) for the optional lane's current status.
