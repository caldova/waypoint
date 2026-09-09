# Getting started

This guide focuses on the local validation path. The current cloud deployment entry point is documented in `docs/deployment.md`.

## Prerequisites

- .NET Aspire tooling for the Waypoint AppHost.
- Python with `uv`.
- Node.js and npm.
- Git.

Optional cloud paths also require Azure, Microsoft Fabric, Microsoft 365, and Azure AI Foundry access.

## Repository tour

Start with the root README, then read:

1. `docs/status.md` for current caveats.
2. `docs/architecture.md` for the system shape.
3. `apps/waypoint/README.md` for the application runtime.
4. `modules/corpus/README.md` for synthetic domain data and seed generation.
5. `modules/agents/README.md` for the single `waypoint-agent`.
6. `modules/evals/README.md` for quality gates.
7. `modules/optimization/README.md` for improvement workflows.
8. `docs/deployment.md` for the current GitHub Actions deployment path.
9. `tools/deploy/README.md` for lower-level deployment orchestration scripts.

## Validate the app lanes

From the repository root:

```powershell
Push-Location apps\waypoint\api
uv run pytest --tb=short -q
Pop-Location

Push-Location apps\waypoint\web
npm ci
npm run typecheck
npm run build
Pop-Location
```

## Validate the corpus seed

The full corpus environment includes optional dependencies that may be platform-specific. The seed generator itself can be validated directly:

```powershell
$env:PYTHONPATH = (Resolve-Path modules\corpus\src).Path
python -m compileall -q modules\corpus\src
python -c "from pathlib import Path; from ledgerfield.waypoint_seed import generate_waypoint_seed; print(generate_waypoint_seed(Path('modules/corpus')))"
Remove-Item Env:\PYTHONPATH
```

## Validate agent and evaluation tooling

```powershell
python -m compileall -q apps\waypoint\integrations\agents\waypoint-iq modules\agents\agents\waypoint-agent

Push-Location modules\evals
uv run caliber telemetry backfill-plan --json
uv run ruff check .
Pop-Location
```

## Validate deploy tooling syntax

```powershell
bash -n tools/deploy/scripts/*.sh
```

## Run the app

The Waypoint AppHost is under `apps/waypoint`. See `apps/waypoint/README.md` for the most current local `aspire run` path and app-specific configuration.
