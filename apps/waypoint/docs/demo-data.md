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
