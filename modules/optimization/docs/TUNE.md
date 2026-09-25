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
$RftBaseModel = "MAI-Code-1-Flash"
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
| Calibration threshold | Recalibrate `pass_threshold` against current v2 baseline/teacher outputs; do not inherit the historical threshold. |
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
| Model-output calibration plan | Score available gold/teacher output-items and record why MAI/base output capture is not applicable when the base model is only available as an RFT target. | Passed for pre-submit threshold selection. Gold ceiling and strict-contract `gpt-6-astra` teacher outputs are scored; `MAI-Code-1-Flash` base outputs are explicitly waived because the model is available as an RFT target, not as a serving deployment. |
| No-submit integration preflight | Check Azure auth, package artifacts, project endpoint, Python grader source, and base-model naming without upload/import/job submission. | Passed for the Python-grader path. Azure auth can mint an `https://ai.azure.com` bearer token, the target project endpoint is configured, the files/jobs list routes are reachable, package artifacts are present, and `BLOSSOM_GRADER_ENDPOINT` / `BLOSSOM_GRADER_SECRET` are not required unless falling back to an endpoint grader. Saved in `runs\rft\contract-policy-expert-v2-mai\integration-preflight.json`. |
| Live-submit gate | Package manifest must stay `ready_for_live_submit: false` until current lineage, Python grader validation, model support, and spend approval are complete. | Correctly blocked. |
| Python grader | Package the deterministic grader as inline `grader.type: python` source with `grade(sample, item) -> float`; validate it through the Foundry grader-run route before any upload or job submit. | Passed. Packaged as the primary dry-run payload; local tests cover exact contract parity, committed dataset target parity, bad citations, fake action penalties, and generated grader-run request shape. The project grader-run POST returned reward `1.0`. |
| Endpoint grader fallback | Keep an endpoint wrapper available only if the preview RFT route rejects `grader.type: python`. | Scaffold packaged as `contract-policy-expert-rft-blossom-endpoint-grader.py`; not an active blocker for the Python-grader path. |
| Response schema | Generate the exact `response_format.json_schema` for `expert_evidence` and verify it matches grader expectations. | Passed for the packaged strict `expert_evidence` schema. |
| Grader-run what-if | Build a request for `POST /openai/v1/fine_tuning/alpha/graders/run` using the packaged Python grader, first validation item, and gold expected answer as the `model_sample` string. | Passed. Saved request and result in `runs\rft\contract-policy-expert-v2-mai\`; Foundry returned HTTP 200 with reward `1.0` and no grader errors. |
| Current teacher evidence | Capture current v2 teacher outputs for the 16-row RFT validation split using the same strict `expert_evidence` response format as the dry-run RFT payload. | Passed for `gpt-6-astra`. `runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-output-items.jsonl` has 16 matched rows; calibration avg `0.915`, min `0.889`, max `0.969`, and candidate threshold `0.9`. A separate 24-row optimized Foundry eval export exists as held-out context only because it has zero ID overlap with the RFT validation split. |
| Frozen dry-run payload | Regenerate the package with the provisional `pass_threshold` included in the exact no-submit job spec. | Passed. `contract-policy-expert-rft-job.dry-run.json` now includes `model: MAI-Code-1-Flash`, `grader.type: python`, inline grader source, strict `expert_evidence` response schema, and `pass_threshold: 0.9`; file fields remain upload placeholders. |
| File registration | Upload/import train and validation JSONL, poll both `file-...` IDs to `processed`, and capture status details. | Passed. Training file `file-b7a342162cc7477c8e71da1bc5486e9c` and validation file `file-8aeb467e8a304099895df211c06bb738` are both `processed`; saved in `contract-policy-expert-rft-file-upload-result.json`. |
| Exact Blossom payload | Generate and review the final `POST /openai/v1/fine_tuning/jobs` JSON with model, file IDs, Python grader source, `pass_threshold`, and response schema. | Submitted after explicit approval. The clean submit payload removes review-only status/metadata and endpoint fallback, adds `trainingType: globalStandard`, and leaves epochs unset so Foundry uses its RFT defaults. Submit and status responses are stored only in ignored `runs\` artifacts. |

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

The allowlisted lower-cost model for this lane is `MAI-Code-1-Flash`. Keep this
exact model name in the dry-run package and final Blossom payload unless the
target project allowlist changes.

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

Current status: the plan is ready for pre-submit threshold selection with an
explicit MAI/base-output waiver. `MAI-Code-1-Flash` is available to us as an RFT
target, not as a deployable serving model, so pre-RFT base-output capture is not
applicable. The captured evidence is:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-gold-output-items.jsonl
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-output-items.jsonl
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-optimized-teacher-calibration.json
runs\eval-results\contract-policy-expert\contract-policy-expert-validation-mai-base-capture-blocker.json
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

Use `0.9` as the provisional `pass_threshold` candidate if the goal is to teach
the lower-cost model the current gold recovery stance. A lower threshold such as
`0.85` would pass all strict teacher rows and would not pressure this behavior.
The base-model comparison moves to post-RFT checkpoint/model evaluation because
the untuned MAI base is not directly callable in this project.

No-submit integration preflight:

```powershell
uv run caliber rft integration-preflight `
  --package-dir runs\rft\contract-policy-expert-v2-mai `
  --base-model MAI-Code-1-Flash `
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
RFT base model: MAI-Code-1-Flash
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
   `trainingType: globalStandard`, `method.type: reinforcement`, grader config,
   `pass_threshold`, and strict `response_format`.
6. Get explicit spend approval with the exact payload and expected monitoring
   plan visible.
7. Submit once, capture the returned job ID, then monitor bounded
   `/fine_tuning/jobs/{job_id}`, `/events`, and `/checkpoints` until terminal
   state.
8. Deploy only a selected checkpoint/model to a review endpoint and compare it
   against the current v2 `gpt-6-astra` teacher with the same held-out eval.

Live submission note: the first POST without `trainingType` was rejected before
job creation because the MAI target does not support the default Standard
training type. The accepted payload uses `trainingType: globalStandard`.
Epochs were intentionally left unset; the accepted job response shows Foundry's
RFT defaults, including `n_epochs: -1` (automatic/default), `eval_interval: 5`,
`eval_samples: 1`, `compute_multiplier: 1`, and
`learning_rate_multiplier: 2`. The current job status is recorded in ignored run
state, not committed documentation.

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
