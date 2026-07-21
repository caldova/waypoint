# Ledgerfield demo data

Ledgerfield is the corpus package and CLI under `modules/corpus` for Waypoint's
pharma contract manufacturing invoice-assurance demo.

Waypoint is the contract manufacturing invoice assurance lane in the broader Road to Start story. It reconciles supplier invoices against contract pricing, purchase orders, receipts, batch records, quality release, milestones, materials, capacity, and timing rules to find payment leakage, explain the finding, and draft supplier responses.

## Module layout

```text
data/
  suppliers/
    suppliers.json
  contracts/
    source-markdown/
    docx/
  policies/
    source-markdown/
    docx/
  invoices/
    supplier-invoices.json
    html/
    pdf/
  scenarios/
    invoice-assurance-scenarios.json
docs/
src/
  ledgerfield/
    api.py
    templates/
      preview.html.j2
      invoices/
        base.html.j2
        sup-001.html.j2
        ...
```

## Authoring principles

- Keep source documents in Markdown so they are easy to review, diff, and maintain.
- Prefix supplier-specific generated documents with the supplier ID from `data/suppliers/suppliers.json`.
- Do not prefix general company policy documents.
- Put contract and policy clauses in source documents.
- Put expected invoice findings, decision states, and evidence mappings in scenario metadata.
- Keep invoice facts in JSON first, then generate supplier-specific HTML invoice layouts and render those HTML files to PDF.
- Keep contracts concise, realistic, and useful as evidence puzzles for LLM reasoning.

## DOCX generation

Use the Python CLI when `.docx` artifacts are needed for ingestion demos:

```bash
uv sync
uv run ledgerfield generate-docx
```

The command converts:

- `data\contracts\source-markdown\*.md` to `data\contracts\docx\*.docx`
- `data\policies\source-markdown\*.md` to `data\policies\docx\*.docx`

## Invoice generation

Use `uv` for Python tooling. For the simplest local setup and full artifact generation:

```bash
uv sync
uv run ledgerfield setup
uv run ledgerfield generate-all
uv run ledgerfield doctor
```

The lower-level invoice-only commands are:

```bash
uv sync
uv run ledgerfield generate-invoices --format html
uv run playwright install chromium
uv run ledgerfield generate-invoices --format both
```

The invoice JSON in `data/invoices/supplier-invoices.json` is the source of truth. The generator writes supplier-specific HTML invoices to `data/invoices/html/` and can render matching PDFs to `data/invoices/pdf/`. Each supplier has a distinct invoice brand and layout profile.

## Waypoint seed export

Ledgerfield can generate a Waypoint-compatible admin import payload without copying the corpus into Waypoint:

```bash
uv run ledgerfield generate-waypoint-seed
```

The command writes `data/waypoint/waypoint-seed.json` from `data/waypoint/invoice-decisions.json` plus the canonical supplier, contract, policy, and scenario sources. The payload contains Waypoint's expected top-level arrays: `suppliers`, `contract_documents`, `policies`, `scenarios`, `invoices`, `findings`, and `evidence`. Each invoice also includes nested `lines`, `findings`, and `evidence`.

The current seed includes 18 invoice decision cases for the invoice decisions UI. HTML/PDF fields use stable synthesized artifact URIs under `data/waypoint/invoices/html/` and `data/waypoint/invoices/pdf/`; Waypoint can store those URIs as references or map them to generated artifacts later.

### Seed contract

The payload is a single JSON object with seven top-level arrays. Required keys per record are enforced by `validate_waypoint_seed` in `src/ledgerfield/waypoint_seed.py`:

- `suppliers` — supplier directory records (`id` referenced by invoices/findings).
- `contract_documents` — contract evidence docs (`id` referenced by `findings.contract_document_ids`).
- `policies` — policy evidence docs (`id` referenced by `findings.policy_ids`).
- `scenarios` — `id`, `source_uri`, `generated_at` (referenced by `invoices.scenario_id`).
- `invoices` — `id`, `supplier_id`, `scenario_id`, `invoice_number`, `invoice_date`, `due_date`, `status`, `currency`, `total_amount`, `html_uri`, `pdf_uri`, `metadata`, plus nested `lines`, `findings`, `evidence`. Line `amount`s must sum to `total_amount`.
- `findings` — `id`, `invoice_id`, `scenario_id`, `category`, `severity`, `status` (one of `open`, `review`, `approved`, `recover`, `escalate`, `closed`), `summary`, `overpayment_amount`, `evidence_ids`, `contract_document_ids`, `policy_ids`, `metadata`.
- `evidence` — `id`, `title`, `evidence_type`, `invoice_id`, `finding_id`, `uri`, `excerpt`, `metadata`.

The payload does not yet carry a top-level `schema_version`; consumers should pin the Ledgerfield release/artifact version (below) until one is added.

### Reproducibility

Seed generation is deterministic: invoice dates derive from a fixed base date plus index, there is no RNG, and the `generated_at` timestamp comes from the committed `generated_at` in `data/waypoint/invoice-decisions.json`. To keep this stable, `generate-waypoint-seed` refuses to fall back to wall-clock time by default. Override or relax this with:

- `LEDGERFIELD_SEED_GENERATED_AT` — pin the timestamp explicitly (used for reproducible CI runs).
- `LEDGERFIELD_SEED_ALLOW_WALLCLOCK=1` — opt into non-deterministic wall-clock time (warns).

### CI artifact

The `Waypoint Seed` workflow (`.github/workflows/waypoint-seed.yml`) regenerates the seed, validates the JSON, runs a drift check (`git diff --exit-code` proves the regenerated file matches the committed copy), and uploads it as a build artifact named `waypoint-seed-<version>-<short-sha>` (containing `waypoint-seed.json` and a `counts.json` summary). It runs on pushes to `main`, `v*` tags, pull requests touching the seed inputs, and `workflow_dispatch`.

The seed workflow exposes an `artifact-name` output. The root monorepo deployment
downloads that artifact non-interactively and imports it through Waypoint's
admin seed endpoint.

> Optional follow-up: an Azure Blob upload job (OIDC `azure/login` + `az storage blob upload`) gated on `main`/tags could publish the seed to a fixed blob URL the deploy reads directly. This requires a federated credential / storage-account contract and is intentionally out of scope for the current artifact-only flow.

## Invoice style preview API

Run the live preview/API server:

```bash
uv run ledgerfield serve
```

Then open:

- Preview lab: <http://127.0.0.1:8000/preview>
- OpenAPI docs: <http://127.0.0.1:8000/docs>
- Invoice HTML: <http://127.0.0.1:8000/api/invoices/INV-SUP-001-2026-10/html>
- Agent manifest: <http://127.0.0.1:8000/api/agent/manifest>
- Agent doctor: <http://127.0.0.1:8000/api/agent/doctor>

Supplier-specific invoice templates live in `src/ledgerfield/templates/invoices/`. Edit a supplier template, refresh `/preview`, and the invoice is rendered dynamically from the canonical JSON facts.

## Agentic integration surface

Consuming apps and agents can discover Ledgerfield capabilities with:

```bash
uv run ledgerfield doctor
uv run ledgerfield serve
```

Then call:

- `GET /api/agent/manifest` for source-of-truth paths, supported commands, generated artifact folders, and API endpoints.
- `GET /api/agent/doctor` for source and generated artifact counts plus PDF page-size status.
- `POST /api/agent/bootstrap?artifacts=true` to generate local artifacts.
- `POST /api/agent/bootstrap?artifacts=true&seed_db=true&append_cycles=1` to generate artifacts and seed Postgres in one call.

Waypoint consumes the generated `data/waypoint/waypoint-seed.json` through its
admin import endpoint rather than copying corpus files into the app module.

## Postgres seeding

Start local Postgres and seed it from the canonical JSON data:

```bash
docker compose up -d postgres
uv run ledgerfield db status
uv run ledgerfield db seed --if-needed --append-cycles 1
uv run ledgerfield db append --cycles 2
```

Set `LEDGERFIELD_DATABASE_URL` or pass `--dsn` to point at another Postgres database. The seed command creates schema if needed, loads canonical suppliers/scenarios/documents/invoices, and can append additional live-looking invoice cycles.

## Agent and Copilot guidance

This module includes custom instructions for Copilot CLI, Copilot agents, and
other agentic tools:

- `.github/copilot-instructions.md` for corpus-module Copilot context.
- `.github/instructions/*.instructions.md` for path-specific data and Python conventions.
- `.github/skills/ledgerfield-demo-data/SKILL.md` as a portable Agent Skill for consuming projects such as Waypoint.
- `AGENTS.md` for agent runtimes that read the common agent-instructions format.

These instructions tell agents to treat Ledgerfield as the canonical corpus
package, use `uv`, preserve the contract/policy/scenario separation, and avoid
committing generated invoice, PDF, DOCX, or cache artifacts.

The `ledgerfield-demo-data` skill teaches consuming apps to use the CLI and
`/api/agent/*` endpoints instead of hard-coding generated artifacts.
