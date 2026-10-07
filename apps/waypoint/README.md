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
| Web | `web/` | Human review, invoice queue, findings, cases, runs, and quality operations. |
| PostgreSQL | Aspire resource / Azure Flexible Server | Durable governed records. |
| OneLake | `api/app/common/onelake.py` | Optional corpus document access. |

The API is the authority boundary. Human users authenticate with delegated MSAL
tokens. Agents use scoped credentials supplied by deployment. Read-only agents
can inspect governed state; `waypoint-recorder` is the sole agent writer.

## Invoice assurance

The invoice queue exposes a live **Run assurance** action for one invoice and a
multi-select batch path for up to 25 invoices. The API invokes the deployed
`assurance-orchestrator` asynchronously while the UI remains responsive. The
orchestrator gathers the enabled evidence, and only `waypoint-recorder` persists
the governed result.

To run the full seeded batch:

1. Open **Invoices** and clear filters if you want every visible invoice.
2. Use the checkbox in the table header to select all visible rows.
3. Select **Review batch**, verify the invoice list, then select
   **Start batch assurance**.
4. Open **Activity** to monitor the accepted or reused runs.

The endpoint is `POST /api/invoices/assurance-runs/batch`. It deduplicates input,
accepts at most 25 unique invoice IDs, starts at most four new runs concurrently,
preserves input order, reuses active invoice-scoped runs, and isolates failures.

The authenticated **Quality** page documents the separate agent quality loop:
run assurance, inspect traces, measure quality, improve the agent, and release
only with explicit approval. Those cloud operations run with `castia eval` and
`castia optimize`; they do not execute in the browser.

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
npm run i18n:check
npm run build
```

## Localization

The web UI ships in English (`en`) and Latin American Spanish (`es`), using
[i18next](https://www.i18next.com/) and `react-i18next`. Only the UI is
translated. Agent findings, corpus data, and API messages stay in English.

- **Strings** live in `web/app/i18n/locales/<locale>/<namespace>.json`, with one
  namespace per page plus `common` for the shell and shared labels. English is
  the source of truth: `t()` keys are type-checked against the English files,
  so a missing key fails `npm run typecheck`.
- **URLs:** English pages are unprefixed (`/invoices`) and other languages
  live under their code (`/es/invoices`). Links stay in the current language;
  use `localize()` from `useLocale()` for in-app paths. `/en/...` redirects to
  the unprefixed URL.
- **Language choice:** an unprefixed URL redirects to `/es/...` when the
  visitor prefers Spanish: the `waypoint_lang` cookie (set by the language
  picker in the user menu or on the sign-in page) first, then the browser's
  `Accept-Language`. `/auth/msal/callback` is never prefixed.
- **Formatting:** use `useFormat()` from `web/app/i18n/format.ts` for currency,
  numbers, percentages, and dates. Don't call `toLocaleString()` or hardcode `$`.
  Decision, run-status, and action labels come from `useLabels()` in
  `web/app/i18n/labels.ts`.
- **Keep in English:** product, plane, and agent names (Caldova, Waypoint,
  Foundry, FoundryIQ, WorkIQ, WebIQ, FabricIQ, Microsoft 365, Teams, Copilot,
  OneLake, Assurance Orchestrator, and so on) and acronyms such as MSA and RFT.

To add a string, add the key to the English file and to every other locale,
then use `t("key")` from `useTranslation("<namespace>")`. Use `{{name}}`
interpolation instead of concatenating strings. Plurals use `_one` and
`_other`, and Spanish also needs `_many`. `npm run i18n:check` (also run in CI)
fails when locales drift apart.

To add a language, add a locale folder with every namespace and add the code to
`SUPPORTED_LOCALES`, `LOCALE_NAMES`, and `INTL_LOCALES`. Then register its
files in `web/app/i18n/resources.ts`. Its `/<code>/...` routes are generated
in `web/app/routes.ts`.

## Configuration

The API uses Pydantic settings with the `APP_` prefix. `apphost.cs` maps local
and deployed values into that namespace. Important groups include:

- `APP_DATABASE_*` for PostgreSQL
- `APP_MSAL_*` and `APP_API_KEY_*` for human and agent auth
- `APP_FOUNDRY_*` for the reviewer-operated orchestrator call
- `APP_ONELAKE_*` for optional corpus access
- `APP_RUN_REAPER_*` for stale-run recovery

Do not commit tenant IDs, subscription IDs, endpoints, API keys, database
passwords, or generated environment files.

## Deployment

The app is deployed as part of the validated monorepo workflow. Use the root
[Azure deployment guide](../../docs/deployment.md), not the historical
app-local workflow or setup scripts.

The default deployment wires the assurance operation to
`assurance-orchestrator`, enables only the FoundryIQ evidence lane, and deploys
`waypoint-recorder` as the write boundary.

## Documentation

- [App architecture](ARCHITECTURE.md)
- [Root architecture](../../docs/architecture.md)
- [Azure deployment](../../docs/deployment.md)
- [Agent quality operations](../../docs/quality-operations.md)
- [OneLake corpus](docs/onelake-corpus.md)
- [FabricIQ](docs/fabric-iq.md)
