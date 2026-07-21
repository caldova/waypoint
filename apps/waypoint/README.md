# Caldova Waypoint app

Waypoint is the governed system of record for Caldova's synthetic contract
manufacturing invoice-assurance scenario. The app combines a FastAPI API, React
Router web UI, PostgreSQL persistence, Microsoft Entra authentication,
OpenTelemetry, optional Fabric/OneLake access, and .NET Aspire orchestration.

## Runtime

| Component | Path | Responsibility |
| --- | --- | --- |
| Aspire AppHost | `apphost.cs` | Starts the API, web app, and local PostgreSQL; supplies `APP_` configuration. |
| API | `api/` | Domain APIs for invoices, work, findings, evidence, cases, recommendations, runs, approvals, and audit. |
| Web | `web/` | Human review, invoice queue, findings, cases, runs, and seller operations. |
| PostgreSQL | Aspire resource / Azure Flexible Server | Durable governed records. |
| OneLake | `api/app/common/onelake.py` | Optional corpus document access. |

The API is the authority boundary. Human users authenticate with delegated MSAL
tokens. Agents use scoped credentials supplied by deployment. Read-only agents
can inspect governed state; `waypoint-recorder` is the sole agent writer.

## Seller-operated assurance

The invoice queue exposes a live **Run assurance** action for one invoice. The
API invokes the deployed `assurance-orchestrator` asynchronously and returns an
accepted operation while the UI remains responsive. The orchestrator gathers
the enabled evidence, and only `waypoint-recorder` persists the governed result.

The current seller trigger is single-invoice. Batch assurance and separate
quality-operation triggers are not part of this validated app path.

## Prerequisites

- .NET SDK 10+
- Node.js 22+
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [Aspire CLI](https://aspire.dev/get-started/install-cli/)
- Docker for the local PostgreSQL resource

## Run locally

```bash
cd apps/waypoint
./setup.sh
aspire run
```

On Windows:

```powershell
cd apps/waypoint
.\setup.ps1
aspire run
```

Use the URLs shown by Aspire. Typical local endpoints are:

- Web: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>
- Aspire dashboard: <http://localhost:15888>

## Run components independently

```bash
# API
cd apps/waypoint/api
uv sync
uv run uvicorn app.main:app --reload

# Web, with the API running
cd apps/waypoint/web
npm ci
npm run dev
```

## Validate changes

```bash
cd apps/waypoint/api
uv run pytest
uv run ruff check app/
uv run ruff format --check app/

cd ../web
npm run typecheck
npm run build
```

## Configuration

The API uses Pydantic settings with the `APP_` prefix. `apphost.cs` maps local
and deployed values into that namespace. Important groups include:

- `APP_DATABASE_*` for PostgreSQL
- `APP_MSAL_*` and `APP_API_KEY_*` for human and agent auth
- `APP_FOUNDRY_*` for the seller-operated orchestrator call
- `APP_ONELAKE_*` for optional corpus access
- `APP_RUN_REAPER_*` for stale-run recovery

Do not commit tenant IDs, subscription IDs, endpoints, API keys, database
passwords, or generated environment files.

## Deployment

The app is deployed as part of the validated monorepo workflow. Use the root
[Azure deployment guide](../../docs/deployment.md), not the historical
app-local workflow or setup scripts.

The default deployment wires the seller operation to
`assurance-orchestrator`, enables only the FoundryIQ evidence lane, and deploys
`waypoint-recorder` as the write boundary.

## Documentation

- [App architecture](ARCHITECTURE.md)
- [Root architecture](../../docs/architecture.md)
- [Azure deployment](../../docs/deployment.md)
- [OneLake corpus](docs/onelake-corpus.md)
- [FabricIQ](docs/fabric-iq.md)
