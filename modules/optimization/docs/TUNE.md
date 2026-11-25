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
| Calibration threshold | Recalibrate `pass_threshold` against current v2 baseline/teacher outputs; do not inherit historical thresholds. Numeric Python graders must declare explicit pass semantics; keep the grader reward and selected threshold on Foundry's 0-1 scale, and carry the threshold into both the reinforcement config and the grader config. |
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
| Exact Blossom payload | Generate and review the final `POST /openai/v1/fine_tuning/jobs` JSON with model, file IDs, Python grader source, hyperparameters, pass threshold placement, and response schema mode. | Current corrected shape omits strict `response_format`, keeps `trainingType: DeveloperTier`, the dense 0-1 Python grader, and explicit conservative hyperparameters, and sets `pass_threshold: 0.9` both on `method.reinforcement` and inside `method.reinforcement.grader`. Submit and status responses are stored only in ignored `runs\` artifacts. |

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
  "method": {
    "type": "reinforcement",
    "reinforcement": {
      "pass_threshold": 0.9,
      "grader": {
        "type": "python",
        "name": "contract_policy_expert_evidence_grader",
        "source": "def grade(sample, item) -> float: ...",
        "pass_threshold": 0.9
      }
    }
  }
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

That result rules out strict `response_format` as the sole failure mode.
Engineering later diagnosed the misleading system failure as a deterministic
grader configuration defect: a non-boolean numeric grader needs an explicit
`pass_threshold` so the trainer can decide whether a reward is correct. Without
that pass semantic, every sample-grade attempt can fail before producing usable
learning signal, and the service may surface the user/config error as a generic
system failure. Harsh clarified the successful shape: the Python grader must
return scores on the 0-1 range and `pass_threshold` must be in the same range.
The corrected MAI RFT payload uses the native 0-1 dense reward and sets
`pass_threshold: 0.9` in both reinforcement-level config and the Python grader
config.
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

The first corrected RFT retry with the schema-explicit prompt failed during
training-file preprocessing with `unsafe_file`. The platform did not identify a
row, phrase, or policy category, so the exact trigger is unknown. To avoid
guessing, the package prompt was neutralized: it keeps the same required
`expert_evidence` keys but removes repeated placeholder language such as
`missing or unproven claim`, `withheld`, `recovered`, and `not billable`.

The neutral schema prompt still scored cleanly against `mai-code-1-1-flash-base`:

```text
rows: 16
score_summary: min 0.945, avg 0.9597, median 0.9545, max 0.981
pass_rates: 0.90 => 1.000, 0.95 => 0.750
```

As a no-job side-effect check, the neutral package files were uploaded for
fine-tune preprocessing only. Both files processed successfully:

```text
training_file: file-428ff8967e2740629c558a060af471d3
validation_file: file-6cce073d49ac4c6bafb04849025a764a
```

This does not prove which phrase caused the earlier `unsafe_file`, but it proves
the neutralized 80/16 package can pass file processing before any new job
submission.

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

## MAI-2 (`mai-code-2-flash`) RFT pre-work

Status: **do not start a paid run**. The original v2 references fail the
boundary check because they contain finance-disposition directives. The v3
preflight report records seven passing offline checks, but a follow-up source
audit found that all 152 prepared train, validation, and eval rows cite
`cmo-*` contract paths and supplier IDs absent from the current Waypoint corpus,
which uses `sup-*`. That older preflight checked corpus provenance only for
challenge rows, so its 7/7 result is stale. The updated preflight checks all
splits and fails the current v3 package. Rebuild or explicitly map the source
data and citations before any model call. The v3 labels also remain synthetic
and `pending_human_review`; domain review, real-output calibration, remote
acceptance and current budget confirmation remain open. Spend was authorized
for this effort, but authorization does not resolve data or grader defects. No
MAI-2 data was uploaded, job submitted, model invoked or deployment created by
this preparation. A local `ready_to_run` or `ready_to_submit` field in a
generic plan is not authorization or proof of remote readiness.

### Reproduce the offline package and checks

Use PowerShell 7.4+ from `modules\evals` with existing dependencies. Pick a
**new** `$o` for each attempt; never overwrite prior runs. These commands do not
contact Foundry. `PSNativeCommandUseErrorActionPreference` stops the script if a
native command fails.

```powershell
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$env:UV_OFFLINE = '1'
$d = 'datasets\contract-policy-expert'
$g = 'graders\contract-policy-expert\contract_policy_evidence_grader_v2.py'
$o = 'runs\rft\contract-policy-expert-mai2\replace-with-new-run-id'
if (Test-Path $o) { throw "Run already exists: $o" }
New-Item -ItemType Directory -Path $o -Force | Out-Null

foreach ($split in @('train', 'validation', 'eval')) {
  uv run --no-sync caliber rft prepare-prompts `
    --source "$d\contract-policy-expert-$split.jsonl" --out "$o\$split.jsonl"
}
uv run --no-sync caliber rft prepare-prompts `
  --source "$d\contract-policy-expert-challenge-candidates.jsonl" --out "$o\challenge.jsonl"
uv run --no-sync caliber rft package --train "$o\train.jsonl" `
  --validation "$o\validation.jsonl" --grader $g --preset mai2-waypoint-local `
  --pass-threshold 0.9 --suffix cpe-mai2-prep --out-dir "$o\package"
uv run --no-sync caliber rft grader-validation-request --package-dir "$o\package" `
  --suite --out "$o\grader-validation-suite.json" | Out-Null
uv run --no-sync caliber rft audit-data --train "$o\train.jsonl" `
  --validation "$o\validation.jsonl" --eval "$o\eval.jsonl" --eval "$o\challenge.jsonl" `
  --grader $g --out "$o\data-audit.json" | Out-Null
uv run --no-sync caliber grader robustness --dataset "$o\train.jsonl" `
  --dataset "$o\validation.jsonl" --dataset "$o\eval.jsonl" `
  --dataset "$o\challenge.jsonl" --grader $g --out "$o\grader-robustness-v2.json" | Out-Null
try {
  uv run --no-sync caliber rft preflight --train "$o\train.jsonl" `
    --validation "$o\validation.jsonl" --eval "$o\eval.jsonl" --challenge "$o\challenge.jsonl" `
    --grader $g --package-dir "$o\package" --grader-suite "$o\grader-validation-suite.json" `
    --corpus-path ..\corpus --source-root datasets --out "$o\preflight.json" | Out-Null
} finally {
  if (Test-Path "$o\preflight.json") {
    Get-Content "$o\preflight.json" -Raw | ConvertFrom-Json |
      Select-Object local_checks_passed, ready_to_run_meter, errors, warnings
  }
}
Get-FileHash "$o\eval.jsonl", "$o\challenge.jsonl"
```

Preflight exits nonzero on failed local checks and refuses to overwrite a
report. It verifies source transformations, source hashes and retrieved corpus
excerpts, split identity and prompt leakage, RFT row shape, a conservative
reference-directive screen, grader score bounds and adversarial cases,
job/manifest/threshold consistency, and parity with the packaged trainer
wrapper. The directive screen is not semantic review and can miss problems.
Preflight currently exits nonzero; it performs no tokenization or remote
checks, and `ready_to_run_meter` is deliberately `false`.

The prepared prompts remove `expected_decision_state`, `issue_category`,
scenario hints and supplier risk examples from model-visible input. They retain
source hashes and removed paths. Historical references use `ledgerfield-seed`
even though no run ID is supplied; derived references use the requested
`unknown` instead and record that normalization. An actual run ID present in
the request is preserved. Original rows and business labels are untouched.

### Local evidence and limits

In the recorded run at
`modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v2`:

- The audit passed for 80 train, 16 validation, 24 original eval and six
  challenge rows, with no identity, normalized-prompt or cross-split leakage.
  Supplier aliases are compared by normalized name as well as ID.
- Preflight passed **6/7 checks** and failed the reference-boundary check:
  a conservative phrase screen flagged 75 of 126 rows. This is a lower bound,
  not a substitute for human review. (The screen was later broadened to
  include recalculate, reprice, credit, present and similar verbs; it now flags
  all 126 original rows.) There are also five coverage warnings.
  The longest row was about 1,308 tokens by a chars/4 estimate, **not** a
  tokenizer result or an upper bound. Verify real tokens and the current model
  limit before upload.
- The final report is `preflight-advisory-boundary.json`; `data-audit.json`,
  `grader-robustness-v2.json`, `grader-validation-suite.json` and the `package\`
  directory are beside it. Earlier `preflight*.json` reports predate the new
  boundary check and must not be used as evidence of current readiness.
- With `UV_OFFLINE=1`, `uv run --no-sync pytest -q` reported **97 passed**, and
  `uv run --no-sync ruff check src tests graders` passed. The previously
  skipped real-agent eval-asset check now runs: the validator accepts the
  current `dataset` key as well as `dataset_reference`, and rejects conflicting
  aliases. Asset validity does not make its training split a held-out set.
- The new `datasets\contract-policy-expert\contract-policy-expert-challenge-candidates.jsonl`
  contains six fictional, clause-grounded scenarios across three suppliers,
  all marked `pending_human_review`; all six have distractors, two expect an
  evidence gap, and one expects `approve`. Each records its derivation and
  UTF-8/LF-normalized corpus source hashes. These are counterfactuals, not
  actual operational records or independently reviewed labels. The suppliers
  are disjoint from train/validation but are the same three as the old eval.
- Train and validation still contain **no** distractors or expected gaps, and
  no `approve` examples. The candidate holdout does not fix that training
  coverage. Obtain independently reviewed, representative additions without
  moving held-out cases into training. The 24-row eval alone is coarse and
  saturated; six candidates are not evidence of generalization.
- Snapshot SHA-256 values for the prepared original eval and challenge are
  `fe9e0148059919dd925d8eb22f2e911d5a97f1cef3b50e0cb81d9b91b48e9865`
  and `5dc56aff011e74711c293d9f7ea7db6eddbdf30e4159d61004531d4f13baf7b4`.
  Freeze and verify the actual reviewed holdout hashes before any model run;
  source paths and line endings can change derived file hashes across checkouts.

### Grader v2 and remote validation

`graders\contract-policy-expert\contract_policy_evidence_grader_v2.py` leaves
v1 intact. At provisional threshold 0.9, its 48 gold-derived perturbation
types produced 5,430 applicable samples across 126 rows, with zero expectation
violations. Local source/wrapper parity was exact in 10,860 comparisons.

| Synthetic response | Observed score |
|---|---|
| Gold, reordered gold, negated boundary disclaimer | 1.00 |
| Empty / malformed or duplicate-key JSON | 0.00 / 0.02 |
| Wrong support, retrieved distractor, or missing expected gap | 0.40 |
| Wrong invoice, run ID, or invented citation | 0.35 |
| Payment/boundary violation | 0.20 |
| All unsupported | 0.40-0.45 |
| Keyword stuffing, irrelevant or contradicted text | 0.45 |

No known-bad variant scored above 0.45, but these are mechanically perturbed
references, not model outputs. They cannot establish grader calibration,
training efficacy or remote trainer parity. Alaska saw a trainer/reward
mismatch in an always-true-grader side experiment; that was separate from e6.
The boundary perturbation above tests claims that an action **was performed**.
It does not establish that v2 rejects a directive to a reviewer. In fact,
historical directive references currently score 1.0; see the conflict below.

`grader-validation-suite.json` contains six **unexecuted** requests for
`POST /openai/v1/fine_tuning/alpha/graders/run`: gold (1.0), wrong supports
(0.4), wrong invoice (0.35), fabricated citation (0.35), boundary violation
(0.2) and empty output (0.0). Each suite entry contains a `request` body and
its expected local score. After explicit authorization, compare and retain
every remote response, including failures; one successful gold-only response
is insufficient.

### Reference and decision-boundary conflict

The current optimized task and rubric establish an evidence-only boundary:
`.agent_configs\optimized\instructions.md:5-10,63-67` reserves finance actions
and decisions, and
`evaluators\contract-policy-expert-generated-rubric\rubric_dimensions.json:32-35`
prohibits a final outcome directing approval, dispute, payment, hold or
reconciliation. These paths are relative to
`modules\agents\contract-policy-expert`.

The older generator copies each scenario's `recommended_action` into **both**
the evidence claims and summary (`modules\evals\src\caliber\contract_policy.py:681-697`);
v2 scores the summary against that recommendation
(`modules\evals\graders\contract-policy-expert\contract_policy_evidence_grader_v2.py:651-663`)
and its boundary check is primarily about claimed actions already performed.
Examples in the unchanged originals include:

- `modules\evals\datasets\contract-policy-expert\contract-policy-expert-train.jsonl:9`:
  “Withhold the batch-related charges until QA release evidence is available.”
- `modules\evals\datasets\contract-policy-expert\contract-policy-expert-validation.jsonl:1`:
  “Withhold the release packet fee until final sponsor QA acceptance is provided.”
- `modules\evals\datasets\contract-policy-expert\contract-policy-expert-eval.jsonl:1`:
  “Pay at the capped escalation rate and request a corrected invoice or approval evidence.”
- `modules\evals\datasets\contract-policy-expert\contract-policy-expert-challenge-candidates.jsonl:1`:
  “Dispute the separate standard certificate charge because it is included in unit cost.”
  This last row is synthetic and still `pending_human_review`.

For the first validation row, the directive reference scores 1.0. An
illustrative, non-directive response describing the conditional evidence and
an unverified QA sign-off scores 0.45. This illustrates both recommendation
matching and the empty-gap-label problem; it is **not** a reviewed replacement
answer or a calibrated model result.

The evidence-only direction is already established in the current repository;
no new policy choice is needed merely to identify the inconsistency. The old
grader describes a looser intermediate recommendation contract, however, so
do not assume its finance directives are authorized for the current agent.
Correct evidence claims, missing-evidence labels and the meaning of each
`supports` value still require a domain owner's review; a phrase filter cannot
invent or verify them.

| Option | Benefit | Consequence |
|---|---|---|
| **Recommended:** create separately versioned, reviewed evidence-only references and align v2's reward and boundary checks | Matches the current no-decision contract; retains historical data and v1 results | Requires scenario-level domain review, new labels and recalibration before training |
| Suppress summary matching alone | Small code change | Insufficient: directive claims and false empty-gap labels remain, and correctness is not established |
| Allow finance dispositions for a different task | Preserves legacy recommendations | Conflicts with the current agent and rubric; requires explicit product/policy approval and a separately scoped contract |

### v3 evidence-only remediation

This implements the recommended option above, as candidates for review. The
originals, v1/v2 graders and the v2 run are unchanged.

- `modules\evals\src\caliber\contract_policy_evidence_only.py` derives
  `datasets\contract-policy-expert\evidence-only-v3\{train,validation,eval,challenge}.jsonl`
  and `manifest.json` deterministically from the originals
  (`caliber rft evidence-only --dataset-dir ... --out-dir ... [--verify]`).
  Each row moves `recommended_action`, `decision_state` and `issue_category`
  into `metadata.historical_reference`, and gets claims that paraphrase the
  cited clause, a specific evidence gap, and a neutral `reference_summary`
  ending "The payment decision remains reserved to the controller."
  `metadata.evidence_only_reference` records the source hash, derivation,
  uncertainty and `support_review_flag`. Labels are
  `synthetic_evidence_only_reference_v3`, `pending_human_review`.
- Rows: train 106 (80 transformed, 10 distractor, 7 approval-evidence,
  9 missing-evidence), validation 22 (16/2/2/2), eval 24, challenge 6.
  Coverage rows are synthetic and only in train/validation.
  `support_review_flag` is set on 27 train, 9 validation and 16 eval rows;
  those carry the historical `supports` value unchanged and need a domain
  owner's check.
- `graders\contract-policy-expert\contract_policy_evidence_grader_v3.py`
  scores the summary against `reference_summary`, caps any directive in the
  summary, claims or gaps at 0.2, and caps gaps that assert the missing
  evidence was present ("contents are visible", "was supplied") at 0.4.
- Robustness adds `directive_summary` (the historical action as summary),
  `directive_claim`, `should_directive` and broader `affirmed_gap` variants.
  These apply to v3 rows only; the v2 test results are unchanged.

Reproduce with the runbook above, but build the v3 sources first and point
prepare-prompts at them, using grader v3:

```powershell
$v = "$d\evidence-only-v3"
$g = 'graders\contract-policy-expert\contract_policy_evidence_grader_v3.py'
uv run --no-sync caliber rft evidence-only --dataset-dir $d --out-dir $v --verify
foreach ($split in @('train', 'validation', 'eval', 'challenge')) {
  uv run --no-sync caliber rft prepare-prompts --source "$v\$split.jsonl" --out "$o\$split.jsonl"
}
# then package, grader-validation-request, audit-data, grader robustness and
# preflight exactly as above.
```

Recorded run: `modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3`.

- Preflight `preflight.json`: **7/7 checks pass**, `local_checks_passed=true`,
  `ready_to_run_meter=false`. The boundary screen finds 0 of 158 rows with
  directives. Trainer-wrapper parity: 0 mismatches in 15,510 comparisons.
  The one warning is that a 30-row held-out set is coarse (3.3 points per row).
- Robustness `grader-robustness-v3.json`: 51 perturbation types, 7,755
  samples over 158 rows, 0 expectation violations. Gold scores 1.0; directive
  variants 0.2; boundary violation 0.2; wrong invoice and fabricated citation
  0.35; wrong supports, distractor, missing gap and affirmed gap 0.4;
  contradicted or irrelevant summary 0.45; prose 0.02; empty 0.
- Validation has 22 rows, but the `mai2-waypoint-local` preset still samples
  16 for eval. Pass `--hyperparameter eval_samples=22` to package if
  full-validation evals are wanted.
- With `UV_OFFLINE=1`: `pytest -q` reported **101 passed**; ruff passed.
- Prepared SHA-256: train `4bf140cce1ee7b53e35580623dcc079f0de68b437c8eae53d5f5a2b361ac8175`,
  validation `c02a7e099818c989ca41bcc3e7f4e49df7da1f6212b34cc06864054c71310ff1`,
  eval `b9be73608d8e12b9c3ebddd064d68fb96d45224a78e119dd35932fb3f9ef867f`,
  challenge `736c62e9cead99019e75f13521c69ea8cadf820e9b3ea6da85b9b03ee3f2a0e9`.
  Re-freeze after review edits.

Limits: the v3 summary reward is term overlap against a long neutral summary,
so real model paraphrases may score lower than gold. Calibrate on base and
teacher outputs before choosing the threshold. Passing local checks does not
make the synthetic labels correct.

### Follow-up corpus review (2026-11-24)

An independent read-only audit of the prepared prompts found a blocking source
identity mismatch:

- All **152** train (106), validation (22), and eval (24) rows cite contract
  paths such as `data/contracts/source-markdown/cmo-001-...md` and use supplier
  IDs `cmo-001` through `cmo-015`. None of the 15 `cmo-*` contract files exists
  in `modules\corpus`; the checked-out documents and supplier records use
  `sup-001` through `sup-015`. The six challenge rows use `sup-*` references
  and resolve against the current corpus.
- The prepared model input preserves those `cmo-*` citation strings, so a
  response citing them would not match the current corpus source references.
  Some corresponding `sup-*` clauses appear similar, but a filename/supplier
  ID substitution is not evidence that the full documents, source history, or
  labels are equivalent.
- The recorded 7/7 check validated corpus sources only for the challenge file.
  The updated `rft_preflight` checks supplier identity, prompt/reference
  context agreement, source path safety, and exact retrieved sections across
  every split. The new report records **7/8 checks passing**, with corpus
  alignment failing; it is not evidence that invoice facts or labels are
  correct.
- A reproducible audit compared all 120 original train/validation/eval rows
  across all 15 historical scenarios. With identifier normalization from
  `cmo-*` to `sup-*`, every prompt-visible supplier, invoice, and line field
  matched its corresponding current record, and every cited section's text,
  classification, and normalized citation matched. This supports a candidate
  mapping, not equivalence of complete documents or approval of the inherited
  labels. The audit script and hash-bearing result are in the ignored
  `runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3\` directory as
  `audit_historical_mapping.py` and `historical-corpus-mapping-audit.json`.
- The same run directory contains `evidence-label-review-bundle.json` and
  `build_review_bundle.py`. The bundle groups the 158 v3 rows into 53
  representative cases, including all 26 hypothetical approval,
  missing-evidence and challenge cases. It includes the proposed labels,
  supplied invoice facts, hypothetical facts, current cited passages, and
  source hashes. Grouping fails if factual inputs or expected outputs differ.
  Every case remains `pending_human_review`; this is not approved ground truth.
- The 52 `support_review_flag` rows reduce to six underlying scenarios. Each
  carries historical `recover` across all cited evidence rows; the negative
  premise is supplied in the invoice description, while the cited document
  contents do not independently establish it. The rubric requires separating
  supplied assertions from documentary findings and says missing documents
  alone do not establish non-billability. Keep these labels pending owner
  review; do not convert the invoice-description claims into facts.
- In the blister-packaging scenario, the optimized instructions specifically
  say the charge is conditional when the authorization contents are not
  supplied. Yet v3 labels both cited passages `recover` and scores the
  unchanged answer with `review` supports at 0.4 versus 1.0 for `recover`.
  The grader and reference-consistency check currently require one shared
  support value for every citation, even when passages play different roles.
  Correct the evidence contract and review source-specific labels before
  calibrating or training; a passing synthetic perturbation suite cannot
  resolve this disagreement.
- The synthetic missing-evidence coverage rows sometimes add a historical
  policy citation that does not resolve the missing predicate (for example,
  the premium-freight case cites dispute-packet procedure). Review or remove
  those secondary claims/citations before freezing the training labels.

Next local step: build separately versioned train, validation, and eval data
with exact current `sup-*` references, preserving original lineage; reconcile
the per-source support semantics and seek human review of the reference labels
and synthetic cases. Rerun the source audit and preflight on that new data.
Do not upload or calibrate on the current prepared prompts.

### Corpus-aligned candidate (2026-11-24)

The prior mapping audit was rerun from its source hashes. It verified 120
original train, validation, and eval rows across 15 scenarios: supplier,
invoice, and invoice-line fields match the current corpus after the `cmo-*` to
`sup-*` identifier mapping, as do the cited section text, classification, and
normalized references. The reproducible mapping audit is
`modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3\historical-corpus-mapping-audit.json`.

Without changing the original files, a new candidate was generated at
`modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3\corpus-aligned-candidate\`.
All eight offline preflight checks pass against its prepared splits, including
exact source-section verification. The report is
`corpus-aligned-candidate\preflight.json`. Its
`ready_to_run_meter` remains `false`: the historical support labels and
source-specific roles are unresolved, all candidate references remain
`pending_human_review`, and there is no real-output calibration or remote
grader acceptance yet. The builder script is
`rebuild_corpus_aligned_candidate.py`; the original datasets and earlier v3
candidate are unchanged. No model call, upload, deployment, job, or spend was
made for this corpus-aligned run.

### Provisional job recipe

`mai2-alaska-e6` preserves Alaska's verified recipe unchanged, including
`eval_samples: 50`. `mai2-waypoint-local` changes that value to **16**, the
validation row count; it otherwise starts from e6:

- model `mai-code-2-flash-2026-11-17`; `trainingType: developerTier`;
  seed 1266282111
- 3 epochs, learning-rate multiplier 2, compute multiplier 1, eval interval 2,
  16 eval samples and low reasoning effort
- Python grader `image_tag: 2025-05-08`, provisional threshold 0.9 inside the
  grader only, and no `response_format`

The grader-only threshold is an **explicit provisional choice** because that
was Alaska e6's shape; the earlier MAI-1.1 job used both grader and
reinforcement placements. Local checks verify placement and propagation, not
which MAI-2 configuration Foundry accepts. Resolve placement and threshold
with remote validation and real outputs before submission. The generated
`contract-policy-expert-rft-job.submit-template.json` contains file-ID
placeholders, not uploaded files or a submitted job. Omitting response format
means JSON shape relies on the prompt and grader.

Alaska also saw transient submit HTTP 500s, rejected checkpoint continuation,
and resubmissions after a backend recipe change. Preserve every attempt and do
not assume retries or checkpoint continuation are safe.

### Cloud facts (read-only check, 2026-11-24)

Account: seth@notareal.co, tenant `dfa98250-28be-4cda-b270-45c05319c07c`. The
default subscription has no AI Services accounts. Subscription
`ME-Caldova42003915-annekrupke-1` has `aif-caldova` (swedencentral).

- The model list shows `mai-code-2-flash` 2026-11-17 as Preview in swedencentral
  and eastus, with `devTierFineTune`, `globalFineTune` and `blossomFineTune`
  capabilities and a per-example limit of 196,608 tokens.

| Region | DeveloperTier fine-tune | `GlobalStandard.mai-code-2-flash-finetune` | `GlobalStandard.mai-code-2-flash` (base serving) |
|---|---|---|---|
| swedencentral | 0 / 2000 | 110 / 2000 | 100 / 100 (full at check time; see update below) |
| eastus | 0 / 2000 | 600 / 2000 | 100 / 100 (full) |

- Base and tuned serving use **separate meters**. The full base meter
  (`GlobalStandard.mai-code-2-flash`, 100/100 in swedencentral) blocks only a
  new **base** MAI-2 evaluation deployment. It does not block a GlobalStandard
  tuned MAI-2 deployment, which draws on
  `GlobalStandard.mai-code-2-flash-finetune` (110/2000 used in swedencentral).
  The DeveloperTier fine-tune meter is a third, separate meter (0/2000 used in
  swedencentral).
- In swedencentral the base meter was fully consumed by an existing base
  deployment (`caldova-recovery-base-v1` in `meridian-foundry-42cwgm`) that
  serves another current demo. Don't delete it based on its name.
- **Update (2026-11-24, user-approved):** the coordinator changed only the
  capacity of that deployment, from 100 to 10 units (100k to 10k TPM). That frees
  90 base-serving units in swedencentral for Waypoint evals.
  Tuned quota stays unchanged, with 1,890 units of headroom. This change
  started no training or eval deployment.
- **Live read-only recheck (2026-11-24):** subscription usage confirms
  `AIServices.GlobalStandard.mai-code-2-flash` at 10/100,
  `AIServices.GlobalStandard.mai-code-2-flash-finetune` at 110/2000, and
  `AIServices.DeveloperTier.mai-code-2-flash-finetune` at 0/2000.
  `aif-caldova` (`rg-caldova`) has no MAI-2 deployment yet; the existing
  `caldova-recovery-base-v1` remains at capacity 10 in
  `meridian-foundry-42cwgm` (`rg-meridian`). The current catalog still lists
  `mai-code-2-flash` version `2026-11-17` in swedencentral, with a
  per-example limit of 196,608 tokens.
- **After the evals finish:** split the swedencentral base meter **50/50**
  between the two resources (`caldova-recovery-base-v1` back up to 50, and the
  Waypoint eval deployment at 50). Do this as part of the tuning
  handoff.
- Neither the catalog listing nor these quota meters proves a job will be
  accepted. A real job is the only confirmation.

### Pricing assumptions

Source: public Azure Retail Prices API (`productName eq 'MAI Models'`,
swedencentral), rechecked 2026-11-24; listed prices are effective
2026-11-01. These are **retail list prices**, not negotiated rates, and MAI-2
is Preview, so prices may change.

| MAI-2 meter | List price |
|---|---|
| Fine-tuned GlobalStandard input / output | $0.05 / $0.25 per 1M tokens |
| Fine-tuned GlobalStandard cached input | $0.01 per 1M tokens |
| Fine-tuned GlobalStandard hosting | $1.60 per hour |
| Base GlobalStandard input / output | $0.05 / $0.25 per 1M tokens |
| Base GlobalStandard cached input | $0.005 per 1M tokens |
| RFT training, Developer / Global / Data Zone | $40 / $80 / $88 per hour |

- The base rates are now present in the current retail API results; earlier
  notes that no base serving meter was listed are stale.
- The $0.20 input / $1.20 output figures quoted elsewhere are MAI-1.1 Flash base
  meters, not MAI-2.

Calculate cost from measured uncached input, cached input and billed output
tokens at the applicable prices; do not double-count reasoning tokens if the
provider includes them in output. Add all deployment hosting hours, separately
metered training time, and the actual teacher/base costs. The retrieved prices
are not a quote: negotiated rates, teacher model/region, usage, training
duration and taxes are unknown. As arithmetic only, two DeveloperTier training
hours plus three tuned-hosting hours at the current list rates would be
$80 + $4.80 = $84.80, **before** inference and other charges. Set a spend cap
only after estimating the intended run.

### Offline rehearsal

The following can be run separately for local diagnostics even while preflight
is blocked. They create plans and a gold-answer ceiling only. The absent teacher
and base files are intentional; do not create fake outputs to make the plan pass.

```powershell
uv run --no-sync caliber grader gold-outputs --dataset "$o\validation.jsonl" `
  --out "$o\validation-gold-output-items.jsonl"
uv run --no-sync caliber grader calibrate --dataset "$o\validation.jsonl" `
  --outputs "$o\validation-gold-output-items.jsonl" --grader $g --json |
  Set-Content -Encoding utf8 "$o\validation-gold-calibration.json"
uv run --no-sync caliber grader model-output-plan --dataset "$o\validation.jsonl" `
  --grader $g --gold-outputs "$o\validation-gold-output-items.jsonl" `
  --teacher-outputs "$o\validation-teacher-output-items.jsonl" `
  --base-outputs "$o\validation-base-output-items.jsonl" --json |
  Set-Content -Encoding utf8 "$o\calibration-plan.json"
uv run --no-sync caliber eval plan --dataset "$o\eval.jsonl" --grader $g `
  --model mai-code-2-flash-base --json | Set-Content -Encoding utf8 "$o\baseline-eval-plan.json"
uv run --no-sync caliber eval plan --dataset "$o\eval.jsonl" --grader $g `
  --model mai-code-2-flash-tuned-pending --json |
  Set-Content -Encoding utf8 "$o\tuned-eval-plan.json"
uv run --no-sync caliber eval plan --dataset "$o\challenge.jsonl" --grader $g `
  --model mai-code-2-flash-base --json | Set-Content -Encoding utf8 "$o\candidate-eval-plan.json"
uv run --no-sync caliber rft plan --train "$o\train.jsonl" --validation "$o\validation.jsonl" `
  --grader $g --base-model mai-code-2-flash-2026-11-17 --suffix cpe-mai2-prep --json |
  Set-Content -Encoding utf8 "$o\training-plan.json"
```

In the recorded pre-boundary-check rehearsal the 16 gold rows scored 1.0, while
`calibration-plan.json` correctly reported `ready_for_threshold_selection:
false` and both real-output captures missing. `eval plan` checks the local
dataset and three reference scores; it does not run an agent or enforce matched
tools. The 1.0 reference score is not a safety result. The generic calibration
planner supports an unavailable-base waiver for other workflows; **do not use
that waiver for this MAI-2 comparison**.

### Gated baseline → calibration → training → evaluation

Nothing below is authorized by the offline preflight. Use a new run directory
and preserve every request, response, attempt and failure.

1. **Review and freeze.** Align the reward and separately versioned references
   with the evidence-only boundary. Have a policy owner independently review
   each underlying scenario, candidate answer and source, correct or reject
   unsupported labels, and add separately reviewed training examples for the
   missing categories. Preserve the originals. Re-run preparation, audit and
   preflight; freeze the reviewed held-out files and their SHA-256 hashes.
   Preregister the quality band, safety gates, comparison arms, sampling, token
   limits and retry policy before inspecting held-out results.
2. **Authorize and baseline.** Recheck region, model, quota and current prices
   without prompting for an unexpected login. Obtain explicit budget approval
   for each remote step. Capture base MAI-2 and teacher outputs on the
   **validation** rows with the same developer prompt, schema instruction,
   retrieved context, tool path and run settings. Save raw attempts as
   separate, uniquely named files. Capture per-row IDs, output, usage, elapsed
   milliseconds, configuration, model/deployment version and any error. Never
   fill missing output or usage with a fabricated value.
3. **Calibrate on validation only.** Use the exact captured paths with
   `caliber grader model-output-plan`, then inspect false positives and false
   negatives with `caliber grader calibrate` and `caliber grader
   threshold-report`. The calibrator records per-row scores and preserves
   `usage` and `latency_ms` when present. It marks incomplete, duplicate,
   unrecognized or positional-only IDs not ready; every output must match one
   dataset ID. Retain the full raw files, including failed attempts. Choose a
   threshold only after reviewing real base and teacher outputs; do not use
   holdout outcomes for calibration.
4. **Validate and package.** After separately authorized remote grader
   validation, compare all six suite results with local scores. Resolve any
   mismatch and confirm threshold placement with the service. Freeze a new
   manifest and job template with the selected, reviewed settings; rerun
   preflight. The local wrapper check does not substitute for this step.
5. **Train only after approval.** With a separately approved spend cap and
   confirmed current prices/model support, upload the reviewed train and
   validation files, wait for their processed states, substitute their IDs into
   the frozen template, and submit. Keep IDs and request/response artifacts in
   ignored `runs\` storage. Poll with a bound; do not overwrite attempts or
   assume a failed submission is safe to retry. Select checkpoints using
   validation data, not held-out scores.
6. **Evaluate after training.** Compare base MAI-2, tuned MAI-2, tuned MAI-1.1
   and the optimized teacher on the same frozen held-out rows. Use the same
   schema/developer prompt, retrieved content and tool path, reasoning setting
   and `max_completion_tokens` of 8192; record model-specific differences that
   prevent a true match. Use five runs per arm, retaining every partial,
   failed and repeated attempt rather than replacing poor results. Report each
   arm's distribution and denominator for v2 scores, pass rate, JSON validity,
   wrong/missing IDs, supports and citations, evidence gaps, and boundary
   violations; require zero boundary violations. Report input, output and
   reasoning tokens, p50/p95 latency, missing telemetry and measured cost.
   Report the original eval and reviewed challenge separately. Promote only
   within the preregistered quality band and with lower measured cost.
7. **Restore capacity.** After evals, coordinate the requested 50/50 split of
   the two Sweden Central base-serving resources. Do not remove the other
   deployment; tuned serving uses its separate quota meter.

Historical MAI-1.1's reported five 24/24 runs are selected: run 4 initially
scored 23/24 and was replaced by a 24/24 rerun. Those prompts also exposed
decision hints, so the old numbers are not apples-to-apples with the cleaned
prompts. A perfect 24-case result does not prove generalization or that MAI-2
can improve only cost/speed.

The agent's existing `modules\agents\contract-policy-expert\eval.yaml:8-9`
points to the **training** split for rubric generation; do not use it unchanged
as the held-out comparison. The local plans above point to the separate
prepared 24-row eval and six-row, still-unreviewed challenge files. Neither
becomes an independently reviewed holdout until the stated review and freeze.

### Live MAI-2 baseline and grader validation (2026-11-24)

The MAI-1.1-style one-epoch package is
`modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3\corpus-aligned-candidate\package-v4-mai11-v4\`.
It uses the 22-row validation split, low reasoning, DeveloperTier, learning-rate
multiplier 2, compute multiplier 1, evaluation interval 5, batch size `-1`,
seed `1266282111`, and provisional threshold `0.9` in both placements. Its
manifest remains `ready_for_live_submit: false`.

Matched live captures for all 22 validation rows are preserved under
`modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3\corpus-aligned-candidate\live-calibration-20261124T232249Z\`
for base `mai-code-2-flash` and teacher `gpt-6-astra`. All 44 outputs parsed as
JSON. Both arms scored exactly
`0.40` on every row; neither had a passing row at thresholds `0.5` through
`0.95`, so there is no useful threshold or base-model failure band. On each
arm, only 11/22 rows matched the expected support categories. More importantly,
all 44 outputs hit the grader's `MISSING_GAP_CAP` of `0.40`: each reference
expects one broad `unsupported` entry, while base outputs list 2-6 specific
gaps and teacher outputs list 2-5. The grader also applies lexical gap checks.
This punishes some answers for listing specific verification gaps and means the
current reward cannot safely guide RFT; do not lower the threshold to make the
package appear ready.

The packaged grader was separately validated remotely on all six positive and
negative cases, matching the local expected scores: gold `1.0`, wrong support
`0.4`, wrong invoice `0.35`, fabricated citation `0.35`, boundary violation
`0.2`, and empty output `0.0`. This confirms grader execution, not that the
reference labels or their gap semantics are correct.

The final offline report,
`modules\evals\runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3\corpus-aligned-candidate\preflight-v4-mai11-postcalibration-final.json`,
passes all eight local checks but correctly keeps `ready_to_run_meter: false`;
it made no live calls. For this v4 candidate, preflight used
`--source-root runs\rft\contract-policy-expert-mai2\local-ready-20261124-v3`
because its provenance points into `mapped-source` under that tree, not
`datasets`.
The warning that the 30-row combined eval/challenge set is coarse remains.
`UV_OFFLINE=1 uv run --no-sync pytest -q` passes 103 tests, and Ruff passes.
No training files were uploaded and no RFT job was submitted.

**Next gate:** have a domain owner review the v4 support and missing-evidence
references, then align the grader's gap semantics with the required evidence
contract without rewarding invented gaps. Re-freeze the reviewed splits and
rerun base/teacher calibration; only proceed to training if the reward has a
meaningful failure band and threshold placement, model support, quota, current
prices, and the spend/cleanup plan are rechecked.
