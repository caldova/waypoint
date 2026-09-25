# Demo data

The canonical synthetic corpus lives in `modules/corpus`.

It contains suppliers, contracts, policies, invoice scenarios, expected
findings, generated-document tooling, and the Waypoint seed generator. Waypoint
imports the generated `waypoint-seed.json` through its admin seed endpoint.

For local development:

```bash
cd modules/corpus
uv run ledgerfield generate-waypoint-seed
```

Configure Waypoint with the generated file through
`APP_LEDGERFIELD_SEED_PATH` or the corresponding Aspire setting. Do not copy
corpus source files into the app module.

Expected findings and scenario outcomes belong only in scenario metadata, not
supplier-facing invoices, contracts, or policies.

The root deployment generates the seed, uploads enabled corpus stores, and
imports the seed automatically.

## Keeping demo activity recent

Run **Actions → Refresh demo timestamps** to make the demo history look current.
It moves the assurance activity (runs, cases, recommendations, drafts, and
decision events) onto weekday business hours over the past `window_days`
(default 7), with the latest run finishing shortly before the time you run it.
Timing inside each run is kept exactly, the order of runs never changes, and
invoice/due dates move so every invoice predates its run. The HTTP request audit
log and reference data (contracts, policies, scenarios) are not changed.

It is safe to re-run: each run re-anchors the same history to "now". Use
`dry_run` to preview the summary without writing. Locally:

```bash
cd apps/waypoint/api
APP_DATABASE_CONNECTION=... uv run python -m app.demo_timestamps --window-days 7 --dry-run
```
