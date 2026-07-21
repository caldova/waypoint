# Caldova Migration Guide

> [!WARNING]
> Historical planning notes retained for provenance. The consolidation is
> complete; use the root README and `docs/architecture.md` for current ownership
> and topology.

Components. General goal is to consolidate the various repos into a single monorepo. This will make it easier to manage dependencies and streamline development.

## Waypoint - Seth

1. Move aspire app (Seth)
2. Reconstitue database (Jess)

## Forge - Seth

1. Simplify aggregate agent and agent list
2. Keep `contract-policy-expert` as is.
3. Move to monorepo and update dependencies

- Expert Agents
  - `contract-policy-expert`
  - `market-research`
  - n*
- Orchestrator
  - `validation-agent`
  - `aggregator`+?
- Teams
  - `invoice-analyst`

## Ledgerfield - Seth

Synthetic Data Generation

1. Move into monorepo
2. Update scripts to target monorepo structure

## Caliber - Seth

1. Move into monorepo
2. Update scripts to target monorepo structure
3. 48 hr back telemetry into app insights / log analytics to simulate optimization job

## Keystone - Jess

1. Simplify to single repo
2. Still multi workflow, but single repo

## GitHub Copilot App

- Canvases all in one place and clearly defined

## Documentation

The following would be awesome

- click throughs as github pages
- clear documentation of the various components and how they interact

## Outstanding Issues

The following issues are still outstanding and need to be addressed before the migration is complete:

- A365 pre-populated data with backend data. Need to figure out how to get things in there
- Auto-hiring of agents in A365.
- GitHub Copilot app accounts
- Backfill app insights / log analytics with 48 hr telemetry data to simulate optimization job.
