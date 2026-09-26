# Contracts API

Waypoint's durable system of record for the `contracts` agent: documents that
arrive by email (or Teams/API upload), their extracted values, supporting
evidence, generated reports, and run state. Artifacts are independent of the
invoice-assurance tables, so invoices can use this path later without adopting
the assurance schema.

All routes are under `/api/contracts` and use the existing auth: reads need the
reader role, writes need the writer role (the `Waypoint.Write` app role for
agent identities).

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/intake/messages/upsert` | Register each attachment of a mailbox message as an artifact. Idempotent. |
| `GET` | `/artifacts/latest` | Latest artifact for a user and type. |
| `GET` | `/artifacts/{artifact_id}` | Artifact plus its extractions, evidence, and reports. |
| `PATCH` | `/artifacts/{artifact_id}` | Update `processing_status`; merge `metadata`. |
| `POST` | `/artifacts/{artifact_id}/extractions` | Append an extraction result. |
| `POST` | `/artifacts/{artifact_id}/evidence` | Append an evidence record. |
| `POST` | `/artifacts/{artifact_id}/runs` | Open (or reuse the active) agent run for the artifact. |
| `POST` | `/artifacts/{artifact_id}/reports` | Record a report that already exists at `file_url`. |
| `POST` | `/artifacts/{artifact_id}/reports/{report_id}/shares` | Record a share outcome (for example after approval). |

## Behavior

- **Idempotent intake.** Each attachment's identity is
  `mailbox_id + message_id + attachment_id + sha256`. Replaying a message
  returns the existing artifact with `created: false`; a re-sent attachment
  with different bytes (new hash) is a new artifact. Read/unread state is never
  used. Concurrent replays register exactly one artifact.
- **Owner.** `owner_user_id` defaults to the sender. Both are lower-cased.
- **Latest lookup.** Filters by owner and `artifact_type` (default `contract`)
  and orders by `received_at`, then `created_at`, then `id`, so the result is
  deterministic. The owner defaults to the signed-in user; app-only callers
  (agents, API keys) must pass `owner_user_id`. Returns 404 when there is none.
- **Original file vs. values.** `original_file_uri` is stored on the artifact;
  extracted values live in extraction records. A `succeeded`/`partial`
  extraction also sets the artifact's `extracted_json`; a `failed` one is
  recorded without discarding earlier values.
- **Append-only records.** Extractions, evidence, and reports are never
  overwritten. Report share changes append to `share_events`.
- **Reports need a real file.** `file_url` is required, so a report cannot be
  recorded (or claimed) without a concrete file.
- **Runs.** A run is an ordinary agent run named `contracts:{artifact_id}`, so
  the existing active-run reuse and stale-run reaper apply. Its id is added to
  the artifact's `run_ids`.

## Storage

PostgreSQL tables (created on startup, like the rest of the schema):
`contract_artifacts`, `contract_intake_checkpoints`,
`contract_artifact_extractions`, `contract_artifact_evidence`, and
`contract_artifact_reports`. The checkpoint primary key is the intake identity,
which is what makes registration idempotent under concurrency.
