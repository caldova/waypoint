# Quality-evidence lineage and fail-closed gates

This is the reference for the `caliber lineage`, `caliber gates`, and
`caliber eval validate-assets` commands: a versioned, immutable, hash-anchored
quality-evidence trail for agent evaluation/optimization/RFT work, plus a
fail-closed gate checker used before any spend-incurring or promotion
operation.

None of these commands apply an optimizer candidate, deploy a model
checkpoint, promote a model, or mutate production state. They only compute,
verify, report, and gate. Every gate defaults to blocked.

The repository-level operator flow is documented in
[`../../../docs/quality-operations.md`](../../../docs/quality-operations.md).
The authenticated Waypoint quality page and the `castia eval` / `castia
optimize` loop present the same sequence:
run, inspect, measure, improve, and release with approval.

## Why this exists

Agent Optimizer and RFT runs produce metrics (baseline score, candidate score,
job cost, etc.). Without a lineage trail, those numbers are just embedded,
unqualified metrics: there's no way to tell whether the prompt/config,
dataset, rubric, grader, or model deployment that produced a metric is still
the one in the repo today, or whether the metric is a historical reference
that can no longer be re-verified. This module makes that distinction
explicit and machine-checkable.

## The snapshot schema (`schema_version: "1"`)

Built by `caliber.lineage.build_snapshot(...)`, one JSON object per line in a
JSONL ledger:

| Field | Meaning |
| --- | --- |
| `schema_version` | Currently `"1"`. |
| `agent` | Agent name, e.g. `contract-policy-expert`. |
| `operation_id` | Correlation id for the operation this snapshot documents (eval run id, optimizer job id, RFT job id, or any caller-chosen id). |
| `operation_kind` | Free-form kind, e.g. `eval`, `agent_optimizer`, `rft`, `manual`. |
| `review_status` | One of `draft`, `accepted`, `rejected`, `superseded`. |
| `environment` | Non-secret label, e.g. `local`, `dev`, `demo`. Never a tenant id, endpoint, or credential. |
| `reference_only` | If `true`, this snapshot is a historical record whose raw sources may no longer be re-hashable. See below. |
| `created_at` | ISO-8601 UTC timestamp, second precision. |
| `source_commit` | Git SHA of the checkout used to build the snapshot (via `caliber.paths.git_sha`), or `"unknown"` outside a git checkout. |
| `hashes.{prompt_config,dataset,rubric_eval_config,grader}` | SHA-256 of file bytes, plus `identifier` (the path) and `available` (whether the file existed at snapshot time). |
| `hashes.model_deployment` | SHA-256 of the deployment name string (not a file), since a deployment isn't a hashable file. |
| `model.{base_model,deployment}` | Human-readable model identifiers (not secret). |
| `metrics` | Free-form key/value metrics attached at snapshot time (`--metric key=value`, repeatable). |
| `approvals` | List of `{approver, role}` objects (`--approval approver:role`, repeatable). |
| `notes` | Free-form text. |
| `snapshot_id` | SHA-256 of the canonical (sorted-key) JSON of every other field above. This is the immutability key. |

At least one hashable component (prompt/config, dataset, rubric/eval config,
grader, or model deployment) must be supplied, so every snapshot is anchored
to something concrete — an empty snapshot cannot be created.

**Append-only, never overwritten.** `append_snapshot`/`caliber lineage
snapshot` write one JSON line per call to a JSONL ledger and reject appending
a snapshot whose `snapshot_id` already exists in that ledger (`ValueError:
snapshot <id> already exists ...`). Snapshots are never edited or deleted in
place; a new operation always produces a new snapshot.

## Verification statuses

`caliber lineage verify` recomputes hashes from the *current* files on disk
and classifies the result as one of `VERIFY_STATUSES`:

- **`current`** — every hash component that was `available` in the original
  snapshot rehashes identically today.
- **`stale`** — the snapshot is not `reference_only`, but at least one
  rehashed component no longer matches (prompt/config, dataset, rubric/eval
  config, grader, or model deployment changed since the snapshot was taken).
- **`reference_only`** — the snapshot has `reference_only: true`. This status
  is permanent and does not change even if the current files happen to hash
  identically to what's recorded; reference snapshots document a historical
  quality claim, not an actively re-verifiable one.
- **`unverifiable`** — no ledger/snapshot could be found to verify against.

## Reference-only historical evidence

`modules/optimization/evidence/contract-policy-expert/reference-lineage.json`
captures the two accepted historical runs documented in
`modules/optimization/docs/CONTRACT_POLICY_EXPERT_RFT_ARTIFACTS.md`:

- The Agent Optimizer run `opt_994a956b2d6e49939506323a15dfc5d2`
  (baseline `0.5084` → candidate `cand_6bf6980ed16f4538ba0faf8935d93c01` at
  `0.8521`).
- The RFT job `ftjob-0265d673736e496dbd360530958c6149` for `o4-mini-2025-04-16`.

Both are schema-conformant snapshots with `reference_only: true` and their
original scores/job ids/cost data preserved verbatim in `metrics`. They are
loaded with `caliber.lineage.load_reference_snapshots()` and included in
`caliber lineage report --reference <path>`. **They always report
`reference_only` lineage status, never `current`**, per the gating rule
above — this is intentional: these numbers are historical evidence for the
demo narrative, not a live promotion basis.

The `optimizer-diff` and `rft-cost-quality` canvases
(`modules/optimization/extensions/*-canvas/extension.mjs`, mirrored under
`.github/extensions/*-canvas/`) load this same file via the shared
`modules/optimization/extensions/shared/lineage-evidence.mjs` module and
surface a `Lineage: reference-only` badge alongside the original historical
numbers — the numbers themselves were not altered, only annotated.

## Fail-closed gates

`caliber gates check` (backed by `caliber.gates.evaluate_gates`) evaluates six
independent gates for one named `--operation` (a free-form label such as
`optimizer_apply`, `rft_submit`, `candidate_promote`, `checkpoint_deploy` —
the gate never performs the operation, only reports whether it would be
allowed):

| Gate | Passes when |
| --- | --- |
| `review_approved` | `--review-approved` is passed. |
| `lineage_fresh` | `--lineage-status` is `current` (from a prior `caliber lineage verify` run). `reference_only`, `stale`, and `unverifiable` always fail this gate. Historical reference evidence is for comparison only and cannot authorize a governed mutation. |
| `model_ready` | `--model-ready` is passed. |
| `quota_ready` | `--quota-ready` is passed. |
| `spend_confirmed` | `--spend-confirmed` is passed. |
| `protected_approval` | No `--required-approver-role` was given, **or** an `--approval approver:role` matching that role (and `--protected-approver` name, if also given) is present. |

Every gate defaults to `false`/closed. `allowed` is `true` only if all six
gates pass. The result always includes `blocking_reasons` (names of failed
gates) and a `guarantees` list restating that the command never performs the
operation itself.

## Commands

```bash
# Validate an agent's eval.yaml plus its referenced dataset and rubric/evaluator files
uv run caliber eval validate-assets --eval-config modules/agents/contract-policy-expert/eval.yaml --json

# Compute and append an immutable lineage snapshot (never overwrites)
uv run caliber lineage snapshot \
  --agent contract-policy-expert \
  --operation-id eval-run-123 \
  --operation-kind eval \
  --dataset datasets/contract-policy-expert/contract-policy-expert-eval.jsonl \
  --rubric-eval-config modules/agents/contract-policy-expert/eval.yaml \
  --grader graders/contract-policy-expert/contract_policy_evidence_grader.py \
  --model-deployment gpt-5-mini \
  --metric pass_rate=0.91 \
  --json

# Recompute hashes from current sources and classify current/stale/reference-only
uv run caliber lineage verify --agent contract-policy-expert --json

# Report current/stale/reference-only counts per agent, including reference evidence
uv run caliber lineage report --agent contract-policy-expert \
  --reference modules/optimization/evidence/contract-policy-expert/reference-lineage.json \
  --json

# Fail-closed gate check before an optimizer apply / RFT submit / promotion
uv run caliber gates check --operation rft_submit \
  --review-approved --lineage-status current \
  --model-ready --quota-ready --spend-confirmed \
  --json
```

Ledgers default to `runs/lineage/<agent>/manifest.jsonl` (an ignored,
generated path — see `.gitignore`); pass `--ledger <path>` to use a different
location, e.g. a committed one for reference evidence.

## Tests

- `modules/evals/tests/test_lineage.py` — hashing, snapshot building/validation,
  append immutability, read/find/latest, `verify_snapshot` status
  classification, `load_reference_snapshots` validation, `lineage_report`
  merging.
- `modules/evals/tests/test_gates.py` — default-closed gates, lineage-status
  gating, `protected_approval` logic, guarantees text.
- `modules/evals/tests/test_eval_assets.py` — valid/invalid configs, missing
  dataset/evaluator, empty/malformed rubric dimensions, backslash-path
  handling, and a regression test against the real
  `modules/agents/contract-policy-expert/eval.yaml`.
- `modules/evals/tests/test_cli_lineage_gates.py` — end-to-end CLI smoke tests
  through `caliber.cli.main` for `lineage snapshot/verify/report`,
  `gates check`, and `eval validate-assets`.
- `modules/evals/tests/test_paths.py` — the shared `git_sha()` helper.
- `modules/optimization/extensions/shared/lineage-evidence.test.mjs` — the
  shared JS lineage loader/classifier/badge renderer used by both canvases
  (`node --test`).

Run everything with:

```bash
cd modules/evals && uv run pytest -q && uv run ruff check .
cd modules/optimization/extensions/shared && node --test
```
