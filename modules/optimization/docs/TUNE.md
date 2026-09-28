# TUNE: rubrics to optimizer to RFT

TUNE starts after `docs\OBSERVE.md` has produced a reviewed Foundry
rubric/eval, baseline output-items, and a calibrated deterministic grader. It
captures the generic optimizer-to-RFT path for improving a Forge hosted agent
and then transferring the optimized behavior to a cheaper RFT model.

## What this covers

1. Check Forge optimizer readiness from Caliber.
2. Review Agent Optimizer jobs and candidates.
3. Apply a selected candidate locally in Forge after review.
4. Deploy the reviewed optimized hosted agent.
5. Re-run the same Foundry eval.
6. Export optimized output-items and recalibrate the deterministic grader.
7. Package RFT assets for the allowlisted lower-cost MAI base model.
8. Submit live RFT only after explicit spend approval.

## Inputs

Set these values for the environment you are working in:

```powershell
$Caliber = "<path-to-caliber>"
$Forge = "<path-to-forge>"
$ProjectEndpoint = "<foundry-project-endpoint>"
$EvalModel = "gpt-6-astra"
$OptimizationModel = "gpt-5.5"
$RftBaseModel = "mai-code-1.1-flash-2026-08-27"
$MaiBaseBenchmarkDeployment = "mai-code-1-1-flash-base"
$Agent = "contract-policy-expert"
$DatasetDir = "$Caliber\datasets\$Agent"
$RunDir = "$Caliber\runs\eval-results\$Agent"
$OptimizerRunDir = "$Caliber\runs\optimizer\$Agent"
$RftDir = "$Caliber\runs\rft\$Agent-expanded"
```

Keep optimizer snapshots, eval run outputs, RFT package artifacts, uploaded-file
metadata, and live RFT job state under ignored `runs\` storage. Do not commit
tenant-specific endpoints, local worktree paths, live eval/run IDs, optimizer
operation IDs, candidate IDs, uploaded-file IDs, or fine-tuning job IDs.

## Optimizer target

The accepted optimizer candidate becomes the gold quality target for RFT. The
demo story should show a visible hill climb:

```text
weak baseline -> candidate improvements -> accepted peak candidate
```

For `contract-policy-expert`, the desired improvement pattern is:

- Start with a realistic weak baseline that has enough failure signal.
- Optimize instructions and procedural skills first.
- Prefer a clean persisted optimizer job over recovered/failed persistence
  artifacts for public demo lineage.
- For current v2 work, use the accepted `gpt-6-astra` hosted-agent candidate as
  the quality target. Earlier `gpt-5.5` / `o4-mini` job IDs are historical
  reference-only evidence unless a fresh current lineage snapshot ties them to
  the v2 source and deployment.
- Use RFT as the cost-transfer step that attempts to preserve optimized
  evidence-contract behavior on a supported lower-cost RFT base model.

The dominant failure mode to optimize and train against is schema/evidence drift:
ad hoc JSON, missing source references, missing classifications, unsupported
claims, or prose outside the final evidence contract.

## V2 grader strategy

Use `modules\evals\graders\contract-policy-expert\contract_policy_evidence_grader.py`
as the reference grader, not as a blindly reusable live Blossom endpoint. It
already covers the core evidence-contract behavior: strict JSON, identity,
invoice correlation, allowed citations, expected support direction,
classification/confidence metadata, unsupported-gap reporting, and no fake
approval/writeback actions.

For the current v2 MAI/Blossom job, augment and repackage that logic before live
submission:

| Augmentation | Why it matters |
| --- | --- |
| Python grader payload | Public Foundry grader samples support `grader.type: python` with inline `source` defining `grade(sample, item) -> float`; use this as the primary path so no separate grader service is needed. |
| Endpoint wrapper fallback | Keep the packaged endpoint wrapper only as a fallback if the allowlisted route rejects Python graders. |
| Response schema parity | The Blossom `response_format.json_schema` must exactly match the `expert_evidence` JSON fields the grader expects. |
| V2 source alignment | Expected `agent`, `plane`, `output_type`, citation refs, classifications, and correlation fields must reflect the current v2 `contract-policy-expert` datasets and deployed teacher behavior. |
| Retrieval/tool discipline checks | Add penalties for answers that ignore provided/retrieved evidence, cite unavailable sources, or invent retrieval/write actions. |
| Score diagnostics | Keep per-dimension diagnostics in local and fallback endpoint tests so failed rows can explain whether the problem is schema, citations, unsupported gaps, boundary violations, or summary mismatch. |
| Calibration threshold | Recalibrate `pass_threshold` against current v2 baseline/teacher outputs; do not inherit historical thresholds. If the base model cannot be invoked before RFT, start with a lower diagnostic threshold and require dense partial-credit grading. |
| Grader-run validation | Before file upload or job creation, POST the packaged Python grader and a gold validation row to the grader-run validation route and require the expected score. |

Live RFT remains blocked until the v2 Python grader passes local golden tests
and the Foundry grader-run validation route, calibration produces a useful
failure band, and the exact Blossom job payload is reviewed.

## Blossom/MAI pre-work safe path

Blossom submission is expensive and should be a single controlled launch. Do
all possible validation before the irreversible API call:

| Gate | Safe-path requirement | Current v2 preflight status |
| --- | --- | --- |
| Local Caliber health | `uv --directory modules\evals run caliber doctor --json` passes. | Passed. `runs/` and `outputs/` are ignored; no project endpoint is configured locally. |
| Asset inventory | `uv --directory modules\evals run caliber manifest --json` identifies `contract-policy-expert` as the active RFT lane and `assurance-analyst` as provenance only. | Passed. |
| Dataset shape | Train/validation JSONL validate and every RFT row ends with a user turn. | Passed for 80 train rows and 16 validation rows. |
| Reference grader package | The deterministic grader packages as a self-contained file with strict evidence-schema checks. | Passed for `runs\rft\contract-policy-expert-v2-mai\contract-policy-expert-rft-grader.py`. |
| Gold-answer parity | Score the known corpus answers from train/validation against the packaged grader. | Passed. All 96 packaged gold answers scored `1.0` with zero failures. |
| Gold-answer ceiling output | Emit answer-key output-items for validation rows and score them through the normal calibration path. | Passed. `runs\eval-results\contract-policy-expert\contract-policy-expert-validation-gold-output-items.jsonl` scored 16/16 at `1.0`; pass rates are 1.0 for thresholds 0.5-0.95. This is a ceiling, not the pass-threshold source. |
| Model-output calibration plan | Score available gold, teacher, and MAI base serving output-items before choosing a threshold. | Passed. Gold ceiling, strict-contract `gpt-6-astra` teacher outputs, and MAI base serving outputs from deployment `mai-code-1-1-flash-base` are scored. |
| No-submit integration preflight | Check Azure auth, package artifacts, project endpoint, Python grader source, and base-model naming without upload/import/job submission. | Passed for the Python-grader path. Azure auth can mint an `https://ai.azure.com` bearer token, the target project endpoint is configured, the files/jobs list routes are reachable, package artifacts are present, and `BLOSSOM_GRADER_ENDPOINT` / `BLOSSOM_GRADER_SECRET` are not required unless falling back to an endpoint grader. Saved in `runs\rft\contract-policy-expert-v2-mai\integration-preflight.json`. |
| Live-submit gate | Package manifest must stay `ready_for_live_submit: false` until current lineage, Python grader validation, model support, and spend approval are complete. | Correctly blocked. |
| Python grader | Package the deterministic grader as inline `grader.type: python` source with `grade(sample, item) -> float`; validate it through the Foundry grader-run route before any upload or job submit. | Passed. Packaged as the primary dry-run payload; local tests cover exact contract parity, committed dataset target parity, bad citations, fake action penalties, and generated grader-run request shape. The project grader-run POST returned reward `1.0`. |
| Endpoint grader fallback | Keep an endpoint wrapper available only if the preview RFT route rejects `grader.type: python`. | Scaffold packaged as `contract-policy-expert-rft-blossom-endpoint-grader.py`; not an active blocker for the Python-grader path. |
| Response schema | Generate the exact `response_format.json_schema` for `expert_evidence` and verify it matches grader expectations. | Passed for the packaged strict `expert_evidence` schema. After repeated zero-token MAI failures, the next diagnostic package should intentionally omit `response_format` to match the historical `o4-mini` job shape more closely while keeping the JSON contract in the prompt/reference output and grader. |
| Grader-run what-if | Build a request for `POST /openai/v1/fine_tuning/alpha/graders/run` using the packaged Python grader, first validation item, and gold expected answer as the `model_sample` string. | Passed. Saved request and result in `runs\rft\contract-policy-expert-v2-mai\`; Foundry returned HTTP 200 with reward `1.0` and no grader errors. |
| Current teacher evidence | Capture current v2 teacher outputs for the 16-row RFT validation split using the same strict `expert_evidence` response format as the dry-run RFT payload. | Passed for `gpt-6-astra`. `runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-output-items.jsonl` has 16 matched rows; calibration avg `0.915`, min `0.889`, max `0.969`. A separate 24-row optimized Foundry eval export exists as held-out context only because it has zero ID overlap with the RFT validation split. |
| Frozen dry-run payload | Regenerate the package with the exact no-submit job spec. | Passed for the MAI diagnostic package. `contract-policy-expert-rft-job.dry-run.json` now includes `model: mai-code-1.1-flash-2026-08-27`, `grader.type: python`, inline 0-5 grader source, and upload placeholders, but no schema-constrained `response_format`. Packaged train/validation messages append the explicit `expert_evidence` JSON shape that made `mai-code-1-1-flash-base` score cleanly. |
| File registration | Upload/import train and validation JSONL, poll both `file-...` IDs to `processed`, and capture status details. | Passed. Training file `file-b7a342162cc7477c8e71da1bc5486e9c` and validation file `file-8aeb467e8a304099895df211c06bb738` are both `processed`; saved in `contract-policy-expert-rft-file-upload-result.json`. |
| Exact Blossom payload | Generate and review the final `POST /openai/v1/fine_tuning/jobs` JSON with model, file IDs, Python grader source, hyperparameters, and response schema mode. | Submitted after the strict-schema retries failed with zero billed tokens. Current historical-shape retry removes review-only status/metadata, endpoint fallback, `pass_threshold`, and strict `response_format`; it keeps `trainingType: DeveloperTier`, the dense 0-5 Python grader, and explicit conservative hyperparameters. Submit and status responses are stored only in ignored `runs\` artifacts. |

Current offline dry-run package:

```text
runs\rft\contract-policy-expert-v2-mai\
  contract-policy-expert-rft-train.jsonl        # 80 rows
  contract-policy-expert-rft-validation.jsonl   # 16 rows
  contract-policy-expert-rft-grader.py          # self-contained reference grader
  contract-policy-expert-rft-blossom-endpoint-grader.py
  contract-policy-expert-rft-response-format.json
  contract-policy-expert-rft-job.dry-run.json
  contract-policy-expert-rft-grader-validation-request.json
  contract-policy-expert-rft-grader-validation-result.json
  contract-policy-expert-rft-file-upload-result.json
  contract-policy-expert-rft-job.final-review.json
  contract-policy-expert-rft-job.submit.json
  contract-policy-expert-rft-job.submit-result.json
  contract-policy-expert-rft-job.status.json
  manifest.json                                 # ready_for_live_submit: false
```

The allowlisted lower-cost fine-tuning model for this lane is
`mai-code-1.1-flash-2026-08-27`. Use that exact model name when submitting
fine-tuning jobs unless the target project allowlist changes. For pre-submit
serving calibration, use deployment `mai-code-1-1-flash-base`.

The dry-run job spec now uses the Python-grader shape:

```json
{
  "grader": {
    "type": "python",
    "name": "contract_policy_expert_evidence_grader",
    "source": "def grade(sample, item) -> float: ..."
  },
  "pass_threshold": 0.9
}
```

The packaged endpoint grader remains a fallback artifact only. The next safe
live-readiness step is the grader-run validation route, not file upload and not
job creation:

```powershell
uv run caliber rft grader-validation-request `
  --package-dir runs\rft\contract-policy-expert-v2-mai `
  --out runs\rft\contract-policy-expert-v2-mai\contract-policy-expert-rft-grader-validation-request.json `
  --json
```

Then POST the request body from that artifact to:

```text
/openai/v1/fine_tuning/alpha/graders/run
```

Expected result: reward `1.0` for the gold validation sample. The route exists
for this project and passed with HTTP 200 after confirming `model_sample` must
be the output string, not an object with `output_text`. The successful response
is saved in
`runs\rft\contract-policy-expert-v2-mai\contract-policy-expert-rft-grader-validation-result.json`.
Do not upload files or create a fine-tuning job until this remains green for the
final frozen payload.

For the early MAI/Blossom test, the grader is intentionally strict and may
overfit to the current optimized evidence contract. That is acceptable for this
lane because the goal is cost-transfer parity with the optimized
`contract-policy-expert` behavior. The packaged endpoint returns only
`{"score": number}` to Blossom, while local preflight can call
`score_with_diagnostics(...)` to inspect parse, schema, identity, correlation,
evidence, unsupported, summary, boundary, and expected-shape subscores.

For calibration, first generate the answer-key ceiling file:

```powershell
Set-Location $Caliber
uv run caliber grader gold-outputs `
  --dataset datasets\contract-policy-expert\contract-policy-expert-validation.jsonl `
  --out runs\eval-results\contract-policy-expert\contract-policy-expert-validation-gold-output-items.jsonl `
  --json

uv run caliber grader calibrate `
  --dataset datasets\contract-policy-expert\contract-policy-expert-validation.jsonl `
  --outputs runs\eval-results\contract-policy-expert\contract-policy-expert-validation-gold-output-items.jsonl `
  --grader graders\contract-policy-expert\contract_policy_evidence_grader.py `
  --json
```

The answer-key ceiling should stay at `1.0`; use model-generated optimized
teacher and MAI/base output-items, not the answer-key file, to select the live
`pass_threshold`.

Then run the threshold-readiness plan:

```powershell
uv run caliber grader model-output-plan `
  --dataset datasets\contract-policy-expert\contract-policy-expert-validation.jsonl `
  --grader graders\contract-policy-expert\contract_policy_evidence_grader.py `
  --gold-outputs runs\eval-results\contract-policy-expert\contract-policy-expert-validation-gold-output-items.jsonl `
  --teacher-outputs runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-output-items.jsonl `
  --base-outputs runs\eval-results\contract-policy-expert\contract-policy-expert-validation-mai-base-output-items.jsonl `
  --json
```

Current status: the plan is ready for pre-submit threshold selection without an
MAI/base-output waiver. The base serving deployment is
`mai-code-1-1-flash-base`; fine-tuning job submissions should use model
`mai-code-1.1-flash-2026-08-27`. The captured evidence is:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-gold-output-items.jsonl
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-output-items.jsonl
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-calibration.json
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-base-validation-schema-prompt-output-items-8192.jsonl
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-base-validation-schema-prompt-summary-8192.json
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-model-output-plan.json
```

The strict-contract `gpt-6-astra` teacher capture used the packaged
`expert_evidence` response schema and scored:

```text
rows: 16/16 matched
score_summary: min 0.889, avg 0.915, max 0.969
pass_rates: 0.9 => 0.562, 0.95 => 0.125
recommended_thresholds: [0.9]
```

The threshold failure report for `0.9` is saved at:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-threshold-0.9-failure-report.json
```

It reports 9/16 passed and 7/16 failed. All seven failures are the
`scn-cmo-011-release-packet-before-qa` validation variants. The outputs are
valid JSON, have correct identity/correlation/schema, and cite the right
contract/policy sources, but the teacher often marks the evidence as `review`
and adds unsupported-gap caveats while the gold target expects `recover`
(`Withhold the release packet fee until final sponsor QA acceptance is
provided.`). This is useful semantic signal, not a parser or response-shape
problem.

The first MAI job with `pass_threshold: 0.9` failed with zero billed training
tokens and no usable learning signal. The later dense-grader and 0-5 reward
retries reached training/eval setup but still failed with zero billed tokens.
The historical-shape retry `ftjob-b766020193b040b7be4c909017353024` removed
strict `response_format`, `pass_threshold`, and the endpoint-grader fallback
while keeping the earlier MAI model alias, `DeveloperTier`, the processed 80/16
train-validation files, dense inline 0-5 Python grader, and conservative
hyperparameters. After Alicia and Srujan's clarification, future submissions
should use explicit model `mai-code-1.1-flash-2026-08-27`. The historical-shape
retry reached retry, training restart, and validation eval creation
(`eval_6abac2aca43c81919f62d56b95bfd10c`) before the same terminal gate:
`Training tokens billed: 0` and `Training data validation failed.
Training stopped after the training data was exhausted because no training
example produced usable learning signal...`.

That result rules out strict `response_format` as the sole failure mode. The
remaining high-probability gap is live trainer/grader contract evidence that is
not visible from local package validation: the actual trainer-side `sample` and
`item` shape, the per-example reward distribution, and the trainer's
classification reason for each rollout. Do not submit another MAI retry until
engineering provides those values or confirms the platform-side issue and fix.
The committed canonical train/validation files match `main` exactly
(`80` train rows and `16` validation rows), and `main` records the successful
historical `o4-mini` RFT job `ftjob-0265d673736e496dbd360530958c6149` for this
agent lineage. The grader is the same scorecard family, but the current branch
is deliberately more permissive for diagnostics: broader sample-shape parsing,
partial credit for malformed nonempty output, near-citation credit, and a
packaged 0-5 reward wrapper. The old raw submit payload was not committed, so
only lineage/data/grader-family parity can be asserted, not byte-for-byte live
request parity.
The MAI serving benchmark requested after Alicia's guidance is now captured in
ignored local artifacts:

```text
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-validation-output-items-8192.jsonl
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-validation-summary-8192.json
```

The first full run with `max_completion_tokens: 2048` returned HTTP 200 for all
16 rows but produced empty visible outputs because the model spent the whole
budget on hidden reasoning. It is not quality evidence. The valid rerun used
`max_completion_tokens: 8192`, Entra auth with the Microsoft tenant verified,
and the chat-completions route. It produced visible output for all 16 rows:

```text
rows: 16
http_status_counts: 200 => 16
score_summary: min 0.100, avg 0.1766, median 0.1365, max 0.331
pass_rates: 0.15 => 0.500, 0.20 => 0.3125, 0.25 => 0.3125, 0.50 => 0.0
```

This initial run was useful, but the score was artificially low: the validation
prompt only said "FoundryIQ evidence contract JSON" and did not spell out the
required `expert_evidence` keys. The model cited the right sources but invented
alternate JSON shapes. Dimension diagnostics showed the problem:

```text
schema avg: 0.042
identity avg: 0.094
correlation avg: 0.000
evidence avg: 0.172
boundary avg: 1.000
```

A follow-up serving benchmark appended the exact `expert_evidence` shape to the
developer message while keeping the same rows, route, deployment, Entra tenant,
and `max_completion_tokens: 8192`:

```text
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-validation-schema-prompt-output-items-8192.jsonl
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-validation-schema-prompt-summary-8192.json
```

That corrected prompt produced strong scores:

```text
rows: 16
http_status_counts: 200 => 16
visible_outputs: 16
score_summary: min 0.904, avg 0.9599, median 0.966, max 0.988
pass_rates: 0.90 => 1.000, 0.95 => 0.8125
dimension_averages: schema 1.000, identity 1.000, correlation 1.000,
  evidence 0.960, unsupported 0.9062, summary 0.5859, boundary 1.000
```

Conclusion: the `0.1766` run should not drive threshold selection. It diagnoses
an underspecified prompt/schema contract. MAI-family serving can satisfy the
current grader when the expected JSON object is made explicit, and the
teacher-style threshold band around `0.9` remains plausible for schema-explicit
outputs. The zero-token RFT failure is therefore more likely a live trainer
rollout / sample-shape / completion-budget issue than a too-strict grader or
incapable MAI-family model. That corrected run was against the wrong serving deployment,
however: Alicia clarified that `mai-code-1-1-flash-base` is the base deployment
in the resource.

The clean base-deployment rerun used `mai-code-1-1-flash-base`, the same exact
schema-explicit prompt, the same 16 validation rows, Entra auth, and
`max_completion_tokens: 8192`:

```text
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-base-validation-schema-prompt-output-items-8192.jsonl
runs\eval-results\contract-policy-expert\mai-base-benchmark\mai-base-validation-schema-prompt-summary-8192.json
```

Clean base result:

```text
observed_response_model: mai-2-coding-fast
rows: 16
http_status_counts: 200 => 16
visible_outputs: 16
score_summary: min 0.916, avg 0.9674, median 0.966, max 0.988
pass_rates: 0.90 => 1.000, 0.95 => 0.9375
dimension_averages: schema 1.000, identity 1.000, correlation 1.000,
  evidence 0.955, unsupported 0.9688, summary 0.6328, boundary 1.000
```

Conclusion after Alicia's clarification: the clean base deployment can satisfy
the current grader when the expected JSON contract is explicit. Keep the
teacher-style threshold band around `0.9`; do not lower the threshold based on
the earlier underspecified prompt or the accidental fine-tuned-looking serving
deployment.

No-submit integration preflight:

```powershell
uv run caliber rft integration-preflight `
  --package-dir runs\rft\contract-policy-expert-v2-mai `
  --base-model mai-code-1.1-flash-2026-08-27 `
  --json
```

This preflight makes no live side effects: no file upload/import, no job
creation, and no endpoint invocation. Current result: local package artifacts
are present, Azure auth can acquire an `https://ai.azure.com` token, and the
target project endpoint is configured:

```text
Project endpoint: https://aif-caldova.services.ai.azure.com/api/projects/ai-project-caldova
Foundry account: aif-caldova
Resource group: rg-caldova
Region: swedencentral
Account endpoint: https://aif-caldova.cognitiveservices.azure.com/
Public network access: Enabled
RFT base model: mai-code-1.1-flash-2026-08-27
```

Read-only probes against this project succeeded for:

```text
GET /openai/v1/files
GET /openai/v1/fine_tuning/jobs?limit=1
```

The direct project root and `/openai/v1/models` probes returned 404, so do not
use them as readiness checks. The no-submit integration preflight is now green
for the Python-grader path; keep live submission blocked until the grader-run
validation route returns the expected score, model-output calibration is
complete, file upload/import is reviewed, and spend is explicitly approved.

## Blossom submit sequence

When all pre-work gates are green, execute in this order:

1. Freeze train, validation, held-out eval, response schema, grader source, and
   job payload; record hashes in ignored run storage.
2. Run local grader golden tests and the Foundry grader-run validation route for
   the Python grader. Use the endpoint wrapper only as fallback.
3. Upload or import train/validation files via `/openai/v1/files` or
   `/openai/v1/files/import`.
4. Poll `/openai/v1/files/{file_id}` until both files are `processed`; stop on
   any `error` and inspect `status_details`.
5. Review the exact `POST /openai/v1/fine_tuning/jobs` payload, including
   `trainingType: DeveloperTier`, `method.type: reinforcement`, grader config,
   hyperparameters, and whether `response_format` is intentionally present or
   omitted.
6. Get explicit spend approval with the exact payload and expected monitoring
   plan visible.
7. Submit once, capture the returned job ID, then monitor bounded
   `/fine_tuning/jobs/{job_id}`, `/events`, and `/checkpoints` until terminal
   state.
8. Deploy only a selected checkpoint/model to a review endpoint and compare it
   against the current v2 `gpt-6-astra` teacher with the same held-out eval.

Live submission note: the first POST without `trainingType` was rejected before
job creation because the MAI target does not support the default Standard
training type. `globalStandard` accepted syntactically but showed severe queue
and stall behavior. After the non-MSIT subscription configuration was fixed,
`DeveloperTier` became the cleaner path. Use explicit conservative
hyperparameters (`n_epochs: 2`, `batch_size: 8`,
`learning_rate_multiplier: 1`, `compute_multiplier: 1`, `eval_interval: 5`,
`eval_samples: 1`) until a successful MAI run gives better evidence. The current
job status is recorded in ignored run state, not committed documentation.

If `response_format` is present, the Python grader must support structured
samples as `sample.output_json` as well as string samples as
`sample.output_text`. A grader that only reads `output_text` can receive no
usable learning signal even when local string-sample validation passes.
Also support common chat-completion wrappers such as `choices[0].message.content`
in local diagnostics so live payload-shape drift does not collapse every sample
to zero.

If `response_format` is omitted, preserve the JSON contract in the developer
prompt and `reference_output`, and verify the grader gives partial credit to
malformed-but-nonempty output, near citations, and correct advisory boundaries.
This is the closest MAI diagnostic to the successful historical `o4-mini` path,
whose committed dry-run package did not include a `response_format` field.

After the live job reaches a terminal succeeded state:

1. Swap the `contract-policy-expert` model reference to the selected tuned
   model or checkpoint in a reviewed branch.
2. Re-run the evaluation suite as a new evaluation group named
   `contract-policy-expert-tuned`.
3. Capture five full evaluation runs for that group before comparing quality,
   stability, and cost against the current v2 teacher.

## Step 1 - Check optimizer readiness

```powershell
Set-Location $Caliber
uv run caliber optimizer plan `
  --forge-path $Forge `
  --agent $Agent `
  --dataset "$DatasetDir\$Agent-eval.jsonl" `
  --eval-config "$RunDir\$Agent-foundryiq-calibration.eval.yaml" `
  --json
```

Expected result: Forge is optimizer-ready for `contract-policy-expert`.

Required Forge surfaces:

```text
agents\contract-policy-expert\main.py
agents\contract-policy-expert\.agent_configs\baseline\metadata.yaml
agents\contract-policy-expert\.agent_configs\baseline\instructions.md
agents\contract-policy-expert\.agent_configs\baseline\skills\retrieval-discipline\SKILL.md
agents\contract-policy-expert\.agent_configs\baseline\skills\read-only-evidence-contract\SKILL.md
```

If model or tool-description optimization is in scope, Forge also needs
optimizer-visible model and tool configuration wired through runtime code. Keep
that as a separate reviewed implementation decision; do not infer local tool
wiring from recovered candidate JSON unless the selected mutation actually
changed tool metadata.

## Step 2 - Run or review optimizer candidates

Use the Foundry Agent Optimizer flow from the Forge agent root:

```powershell
Set-Location "$Forge\agents\$Agent"
azd ai agent optimize status <optimizer-operation-id> --watch
```

Review:

- Baseline score and pass rate
- Candidate scores
- Mutation surfaces, such as `system_prompt`, `skills`, `tools`, or `model`
- Whether the optimizer job persisted cleanly
- Candidate config and result artifacts
- Payload-size risks, especially result persistence failures such as Cosmos DB
  item-size limits

For a demo path, prefer a clean `succeeded` optimizer job with a clear hill climb
over a higher-risk failed persistence artifact. If a failed job produced
recoverable candidates, keep those snapshots under ignored `runs\optimizer\`.

## Step 3 - Show the hill climb

The demo story should make the hill-climbing metaphor explicit: Agent Optimizer
starts from a real but under-specified hosted agent, tries candidates, and
selects the highest-quality candidate before RFT starts.

Use a table like this in local notes or slides:

| Stage | Candidate | Score | Pass rate | Demo meaning |
|---|---|---:|---:|---|
| Start | `<baseline-candidate-id>` | `<score>` | `<pass-rate>` | Real weak baseline with enough failure signal |
| Climb 1 | `<candidate-id>` | `<score>` | `<pass-rate>` | First major optimizer jump |
| Climb 2 | `<candidate-id>` | `<score>` | `<pass-rate>` | Higher candidate after search |
| Explore | `<candidate-id>` | `<score>` | `<pass-rate>` | Slight regression, useful to show search is not linear |
| Peak | `<accepted-candidate-id>` | `<score>` | `<pass-rate>` | Optimized current v2 quality target |

RFT only starts after the peak candidate is reviewed and accepted.

## Step 4 - Apply selected candidate locally

```powershell
Set-Location "$Forge\agents\$Agent"
azd ai agent optimize apply --candidate <accepted-candidate-id>
git -C $Forge diff -- agents\contract-policy-expert
```

Gate: apply only the selected candidate. If `azd ai agent optimize apply` cannot
resolve the candidate locally, recover the selected candidate config through the
documented Foundry data-plane route and manually apply only the reviewed mutation
surfaces. Stop before deploy if the Forge diff does not match the accepted
candidate delta.

When recovering manually, verify:

- Source/runtime agent version from the optimizer job
- Candidate mutation keys
- Local files changed
- Whether tool/model metadata actually changed
- Normalized file contents against recovered candidate fields

Do not deploy until the source diff is reviewed.

## Step 5 - Deploy reviewed optimized Forge agent

```powershell
Set-Location $Forge
azd deploy $Agent --no-prompt
azd ai agent show $Agent -e <azd-env-name> --no-prompt -o json
```

Record the active deployed version, model, endpoint availability, and image
digest in ignored run notes or durable process docs only when they are safe to
share. Do not commit tenant-specific values.

## Step 6 - Run post-optimizer eval

```powershell
Set-Location $Forge
azd ai agent eval run `
  --config "$RunDir\$Agent-foundryiq-calibration.eval.yaml" `
  --name "$Agent-foundryiq-optimized-run" `
  --no-wait `
  --no-prompt `
  -o json
```

```powershell
$EvalId = "<eval-id>"
$OptimizedRunId = "<optimized-eval-run-id>"
```

Use the same Foundry rubric/eval as the baseline run so the optimized result is
comparable.

## Step 7 - Export optimized output-items

```powershell
Set-Location $Caliber
uv run caliber eval export-output-items `
  --project-endpoint $ProjectEndpoint `
  --eval-id $EvalId `
  --run-id $OptimizedRunId `
  --out "$RunDir\output-items-optimized.jsonl" `
  --json
```

Expected ignored output:

```text
runs\eval-results\contract-policy-expert\output-items-optimized.jsonl
```

## Step 8 - Recalibrate deterministic grader

```powershell
uv run caliber grader calibrate `
  --dataset "$DatasetDir\$Agent-eval.jsonl" `
  --outputs "$RunDir\output-items-optimized.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --json
```

Use the optimized output-items to ensure the deterministic grader rewards the
same behavior that the Foundry rubric accepted. Inspect failed rows before live
RFT submission.

For v2 Blossom submission, this step must also produce the Python-grader
calibration input: current train/validation/eval rows, current optimized
teacher outputs, local grader scores, chosen `pass_threshold`, and any
per-dimension diagnostics needed to explain failures before spending on the
MAI fine-tuning job.

## Step 9 - Plan RFT for cost transfer

RFT starts only after the current v2 hill climb is accepted. The training goal
is not "beat the optimizer"; it is "keep the optimized evidence-contract
behavior while moving inference from the current v2 hosted-agent teacher to a
supported lower-cost RFT base model."

Do not assume the historical `o4-mini-2025-04-16` job/deployment is reusable for
v2. Confirm current Foundry RFT model support, select the lower-cost candidate
model intentionally, and require explicit live-spend approval before submission.

```powershell
uv run caliber rft plan `
  --train "$DatasetDir\$Agent-train.jsonl" `
  --validation "$DatasetDir\$Agent-validation.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --base-model $RftBaseModel `
  --project-endpoint $ProjectEndpoint `
  --suffix "$Agent-cost-expanded" `
  --json
```

## Step 10 - Package expanded RFT assets

```powershell
uv run caliber rft package `
  --train "$RftDir\$Agent-rft-source-combined-train.jsonl" `
  --validation "$RftDir\$Agent-rft-source-combined-validation.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --agent $Agent `
  --base-model $RftBaseModel `
  --suffix "$Agent-cost-expanded" `
  --out-dir $RftDir `
  --optimizer-job-id <optimizer-operation-id> `
  --optimizer-candidate-id <accepted-candidate-id> `
  --json
```

Expected ignored artifacts:

```text
runs\rft\contract-policy-expert-expanded\contract-policy-expert-rft-train.jsonl
runs\rft\contract-policy-expert-expanded\contract-policy-expert-rft-validation.jsonl
runs\rft\contract-policy-expert-expanded\contract-policy-expert-rft-grader.py
runs\rft\contract-policy-expert-expanded\contract-policy-expert-rft-job.dry-run.json
runs\rft\contract-policy-expert-expanded\manifest.json
```

The generated RFT train/validation JSONL files include a UTF-8 BOM for Foundry
fine-tuning upload compatibility.

## Step 11 - Inspect RFT package gate

```powershell
uv run caliber rft status --state "$RftDir\manifest.json" --json
```

Expected gate shape:

```json
{
  "ready_for_live_submit": false,
  "blocked_until": [
    "optimizer candidate is selected as the gold quality target",
    "gold candidate outputs are calibrated with the RFT grader",
    "v2 Python grader is validated and aligned with response_format",
    "RFT base model support is verified",
    "live RFT spend is explicitly approved"
  ]
}
```

## Step 12 - Submit live RFT

Caliber currently packages and tracks RFT artifacts; live submission may use the
Foundry SDK/script path until a first-class `caliber rft submit` command exists.

Before submitting:

1. Confirm the optimized current v2 quality target is accepted.
2. Confirm the selected lower-cost RFT base model is supported in the target
   Foundry project.
3. Confirm live spend approval.
4. Keep uploaded-file IDs, fine-tuning job IDs, and job state under ignored
   `runs\` storage.

Monitor the job with bounded status checks. Do not use an unbounded polling loop.

## Output contract for TUNE

TUNE is complete when:

1. A selected optimizer candidate is reviewed in Forge source.
2. The optimized hosted agent is deployed.
3. The same Foundry rubric/eval has been rerun.
4. Optimized output-items are exported.
5. The deterministic grader is recalibrated.
6. The RFT package exists under ignored `runs\rft\contract-policy-expert-expanded`.
7. If live RFT is submitted, the job ID and uploaded-file IDs are stored only in
   ignored run state.

## RFT golden path economics

Use economics as a promotion gate, not a slide-only claim. The expected shape is:

| Model path | Purpose | Approx cost shape |
|---|---|---|
| Optimized current v2 hosted agent | Quality target after hill climb | Teacher / quality target cost |
| RFT lower-cost candidate | Cost-transfer candidate | Lower token economics if output length stays similar |

Promote the RFT model only if it stays within the accepted quality band of the
optimized current v2 candidate and materially lowers measured eval cost.
