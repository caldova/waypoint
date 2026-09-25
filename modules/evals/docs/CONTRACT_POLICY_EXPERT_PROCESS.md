# Contract-policy-expert optimization and FT process

This is the Caliber-owned process for Forge's hosted
`contract-policy-expert` FoundryIQ lane.

Today's sequence is:

1. Generate rubrics with Foundry.
2. Run evals against the generated rubric.
3. Use Foundry Agent Optimizer to improve hosted-agent accuracy.
4. Use FT/RFT to move the optimized behavior to a cheaper model for cost.

`contract-policy-expert` is the only active agent for this rubric/eval/FT lane.
The previous `assurance-analyst` work is calibration history only.

## Ownership split

| Area | Owner |
| --- | --- |
| Hosted runtime source | Forge |
| FoundryIQ/toolbox/runtime wiring | Forge |
| Seed datasets | Caliber |
| Foundry-generated rubric/evaluator lineage | Caliber |
| Eval output-items and result analysis | Caliber |
| Agent Optimizer run metadata and candidate comparison | Caliber |
| Applying optimizer candidates to source | Forge, after review |
| FT/RFT candidate data and cost/quality promotion criteria | Caliber |

## Current baseline

Generated rubric/evaluator:

```text
contract-policy-expert-foundryiq-calibration
version: 1
```

Baseline eval:

```text
eval: eval_15237abd970943a190f090d4dd6184e7
run:  evalrun_a0f4a64c65714b188321d5ed880eed71
```

Result:

```text
24 total
19 passed
5 failed
0 errored
pass rate: 79.2%
```

Caliber output-items export:

```text
runs\eval-results\contract-policy-expert\output-items.jsonl
```

Deterministic grader calibration against this run:

```text
min: 0.788
avg: 0.813
max: 0.85
```

The deterministic grader is currently less discriminating than the
Foundry-generated rubric at the failure boundary, so it should not be used as the
RFT reward gate unchanged.

## 1. Build Caliber datasets

Use Ledgerfield as the read-only data source:

```powershell
$Caliber = "C:\path\to\caliber"
$Ledgerfield = "C:\path\to\ledgerfield"
$Agent = "contract-policy-expert"

Set-Location $Caliber

uv run caliber datasets contract-policy build `
  --ledgerfield-path $Ledgerfield `
  --agent $Agent `
  --variants-per-scenario 8 `
  --json
```

Expected committed dataset paths:

```text
datasets\contract-policy-expert\contract-policy-expert-train.jsonl
datasets\contract-policy-expert\contract-policy-expert-validation.jsonl
datasets\contract-policy-expert\contract-policy-expert-eval.jsonl
```

For Foundry eval generation, stage the CPE eval split under ignored `runs\`
storage:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-foundryiq-eval-input.jsonl
```

This avoids the `messages` data-mapping validation issue seen when sending the
chat-format training rows directly to the generated evaluator.

## 2. Generate the Foundry rubric/evaluator

Use `azd ai agent eval generate`; do not hand-write rubric dimensions in
Caliber.

```powershell
$Caliber = "C:\path\to\caliber"
$Forge = "C:\path\to\forge"
$ProjectEndpoint = "<foundry-project-endpoint>"
$Agent = "contract-policy-expert"
$RunDir = "$Caliber\runs\eval-results\$Agent"

Set-Location $Forge

azd ai agent eval generate `
  --agent $Agent `
  --project-endpoint $ProjectEndpoint `
  --dataset "$RunDir\$Agent-foundryiq-eval-input.jsonl" `
  --gen-instruction-file "$Forge\agents\$Agent\prompt.md" `
  --eval-model gpt-5.5 `
  --max-samples 15 `
  --name "$Agent-foundryiq-calibration" `
  --out-file "$RunDir\$Agent-foundryiq-calibration.eval.yaml" `
  --no-prompt `
  -o json
```

Current generated rubric dimensions:

| Weight | Dimension |
| ---: | --- |
| 10 | `evidence_grounding_and_citation` |
| 6 | `retrieval_tool_discipline` |
| 5 | `retrieval_query_specificity` |
| 5 | `json_evidence_contract_compliance` |
| 5 | `role_scope_and_read_only_behavior` |
| 4 | `gap_and_conflict_reporting` |
| 3 | `information_governance` |
| 5 | `general_quality` |

## 3. Run the baseline eval

```powershell
$Caliber = "C:\path\to\caliber"
$Forge = "C:\path\to\forge"
$Agent = "contract-policy-expert"
$RunDir = "$Caliber\runs\eval-results\$Agent"

Set-Location $Forge

azd ai agent eval run `
  --config "$RunDir\$Agent-foundryiq-calibration.eval.yaml" `
  --name "$Agent-foundryiq-calibration-run" `
  --no-wait `
  --no-prompt `
  -o json
```

Inspect a completed run:

```powershell
azd ai agent eval show <eval-id> `
  --eval-run-id <run-id> `
  --out-file "$RunDir\$Agent-foundryiq-calibration-run.json" `
  --no-prompt `
  -o json
```

Export output-items for Caliber analysis:

```powershell
Set-Location $Caliber

uv run caliber eval export-output-items `
  --project-endpoint $ProjectEndpoint `
  --eval-id <eval-id> `
  --run-id <run-id> `
  --out "$RunDir\output-items.jsonl" `
  --json
```

Calibrate the deterministic grader:

```powershell
uv run caliber grader calibrate `
  --dataset "$Caliber\datasets\$Agent\$Agent-eval.jsonl" `
  --outputs "$RunDir\output-items.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --json
```

## 4. Make Forge optimizer-ready

This is a Forge runtime-source change, scoped to:

```text
agents\contract-policy-expert
```

Required Forge changes:

1. Add dependency:

   ```text
   azure-ai-agentserver-optimization
   ```

2. Import optimizer config:

   ```python
   from azure.ai.agentserver.optimization import load_config
   ```

3. In `main.py`, use optimizer config for model and instructions:

   ```python
   config = load_config()
   model = config.model
   instructions = config.compose_instructions()
   ```

4. Use `model` in `FoundryChatClient(...)`.
5. Use `instructions` for both the hosted Responses `Agent` and the
   `/api/messages` teammate clone.
6. Preserve existing Responses host, toolbox MCP wiring, evidence tools, activity
   protocol, telemetry, and `default_options`.
7. Create baseline config beside `agent.yaml`:

   ```text
   agents\contract-policy-expert\.agent_configs\baseline\metadata.yaml
   agents\contract-policy-expert\.agent_configs\baseline\instructions.md
   ```

8. `metadata.yaml` should point to `instructions.md` and an existing model
   deployment:

   ```yaml
   model: gpt-5.5
   instruction_file: instructions.md
   ```

9. `instructions.md` should contain the reviewed current `prompt.md`
   instructions.

Caliber has sent this request to the Forge PR session.

## 5. Run Foundry Agent Optimizer

After Forge is optimizer-ready, run optimizer against the active generated
rubric/evaluator and the deployed optimizer-ready hosted version.

Hosted runtime versions used in the current optimizer experiments:

| Experiment | Hosted version | Runtime shape |
| --- | ---: | --- |
| Prompt-only optimizer | 3 | Baseline instructions only in optimizer request |
| Procedural-context optimizer | 18 | Deployed Forge runtime loads baseline skills and appends procedural bodies |

```yaml
agent:
  name: contract-policy-expert
  kind: hosted
  version: "3"
  model: gpt-5.5
  config: .agent_configs\baseline\metadata.yaml
options:
  eval_model: gpt-5.5
  optimization_model: gpt-5.5
```

The current `azd ai agent optimize` preview has two important gotchas:

1. It does not support `--target`; let the optimizer infer target attributes.
2. In multi-agent Forge projects, passing `--agent` bypasses local project
   resolution, so the CLI cannot resolve `.agent_configs\baseline` in
   non-interactive mode. If this is fixed upstream, prefer the CLI path below.

```powershell
$Caliber = "C:\path\to\caliber"
$Forge = "C:\path\to\forge"
$ProjectEndpoint = "<foundry-project-endpoint>"
$Agent = "contract-policy-expert"
$RunDir = "$Caliber\runs\eval-results\$Agent"

Set-Location "$Forge\agents\$Agent"

azd ai agent optimize `
  --project-endpoint $ProjectEndpoint `
  --eval-model gpt-5.5 `
  --optimize-model gpt-5.5 `
  --no-wait `
  --no-prompt `
  -o json
```

Because the installed CLI could not resolve the multi-service Forge context
non-interactively, the first live optimizer job was submitted through the same
Foundry optimization API used by the CLI. The request used:

```text
agent: contract-policy-expert
agent_version: 3
rubric/evaluator: contract-policy-expert-foundryiq-calibration version 1
eval_model: gpt-5.5
optimization_model: gpt-5.5
max_candidates: 5
baseline model: gpt-5.5
baseline system_prompt: Forge .agent_configs\baseline\instructions.md
train_dataset: inline Caliber query-shaped eval rows, registered by Foundry as opt-inline-31b0d53d4cef4475913ef4de8448573a version 1
```

When the CLI cannot resolve instructions, submit the saved optimizer payload
directly through the Foundry optimizer API instead of guessing more `eval.yaml`
shapes. The service contract is:

```text
POST <project-endpoint>/agent_optimization_jobs?api-version=v1
Authorization: access token minted for https://ai.azure.com/.default
Foundry-Features: AgentsOptimization=V2Preview
Content-Type: application/json
body: { "inputs": <OptimizeRequest> }
```

For procedural skill optimization, each skill in
`inputs.options.optimization_config.skills` must use this shape:

```json
{
  "name": "retrieval-discipline",
  "description": "Short stable description.",
  "body": "Full SKILL.md body."
}
```

Do not send skill bodies under `content`; the service validates `description`
and `body` as required strings.

To activate every optimizer target in one run, the deployed Forge runtime must:

1. Prefer `config.model` over `AZURE_AI_MODEL_DEPLOYMENT_NAME`, so
   `model_search_space` candidates actually change the model used during
   candidate evaluation and after local apply.
2. Call `config.apply_tool_descriptions(tools)` after constructing runtime tools.
3. Include `.agent_configs\baseline\tools.json` and reference it from
   `metadata.yaml` with `tools_file: tools.json`.
4. Include `optimization_config.model_search_space`, `system_prompt`, `tools`,
   and `skills` in the direct optimizer payload.

PowerShell submit pattern:

```powershell
$TokenJson = azd auth token --scope "https://ai.azure.com/.default" -o json --no-prompt | ConvertFrom-Json
$Token = if ($TokenJson.token) { $TokenJson.token } else { $TokenJson.accessToken }
$Headers = @{
  Authorization = ("Bearer " + $Token)
  "Content-Type" = "application/json"
  "Foundry-Features" = "AgentsOptimization=V2Preview"
}
$Uri = "$ProjectEndpoint/agent_optimization_jobs?api-version=v1"
Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -InFile $PayloadPath
```

PowerShell status pattern:

```powershell
$Uri = "$ProjectEndpoint/agent_optimization_jobs/${JobId}?api-version=v1"
Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers
```

Current prompt-only optimizer job:

```text
job: opt_182bc0626ed04f55bb5e2f04e9cc74a1
status: succeeded
```

This first optimizer job is the **prompt-only** optimizer test. Its submitted
`optimization_config` exposed the baseline `system_prompt` and model only, so
Foundry can rewrite instructions but does not have optimizer-visible procedural
skills, tool descriptions, or model-search candidates to mutate.

Run a second **procedural-context** optimizer test after Forge adds baseline
skills under:

```text
agents\contract-policy-expert\.agent_configs\baseline\skills\
```

Suggested skill split:

| Skill | Purpose |
| --- | --- |
| `retrieval-discipline` | Query `knowledge_base` first with invoice, supplier, contract, SKU, lot, rate-card, and policy identifiers; use local fallback only when MCP retrieval is unavailable; return empty evidence instead of guessing. |
| `read-only-evidence-contract` | Enforce FoundryIQ-only behavior, strict evidence JSON, cited claims, classification/confidence/source refs, and no approve/reconcile/writeback actions. |

The runtime already uses `load_config().compose_instructions()`, so once the
baseline config has `skills\...\SKILL.md` files, Agent Optimizer can attempt
`skill_*` strategies in a follow-up run. Keep this as a separate optimizer job
from the prompt-only run so Caliber can compare: baseline, prompt-only optimizer,
and procedural-skill optimizer.

Procedural-context optimizer job:

```text
job: opt_fff465f7706e4de4a9ac24b1e0177e1e
status: deleted from Foundry data plane after artifact recovery
deployed hosted version: 18
max_candidates: 10
optimization_config: system_prompt + 2 skills
skills: retrieval-discipline, read-only-evidence-contract
failure: Optimization succeeded but result persistence failed
```

Clean weak-baseline demo optimizer job:

```text
job: opt_c14090aa4e3142ba98a09a6d2a3921fe
status: deleted from Foundry data plane after cancellation
deployed hosted version: 49
max_candidates: 10
optimization_config: weak system_prompt + 2 weak skills
skills: retrieval-discipline, read-only-evidence-contract
```

Full-surface weak-baseline demo optimizer job:

```text
job: opt_be11872f07684ae1a1ad03a0fa56853b
status: deleted from Foundry data plane after artifact recovery
failure: Optimization succeeded but result persistence failed
deployed hosted version: 52
max_candidates: 10
optimization_config: weak system_prompt + 2 weak skills + 2 weak tools + model_search_space
tools: toolbox, gather_foundry_evidence
model_search_space: gpt-5-mini, gpt-4.1
baseline model: gpt-5.5
```

Final full-surface signal:

```text
baseline score: 0.4863
baseline pass rate: 37.5%
best candidate: candidate_6 / cand_26ff05b5446441b0afd55712bbc4746c
best candidate score: 0.6790
best candidate pass rate: 100%
best evaluated mutation pattern: system_prompt and skills
tool candidate: candidate_8 / cand_f6ca5f60997545088353005148ef57a8, score 0.6560
model candidate: candidate_9 / cand_28684effc9954011b4dd575a00dab1a8, model gpt-5-mini, score 0.6540
dominant failure mode: ad hoc JSON instead of the strict expert_evidence schema
```

Before deletion, the data-plane candidate routes exposed recoverable
`config.json` and `results.json` for every candidate.
No lower-level `/events`, `/logs`, `/operations`, `/errors`, or `/diagnostics`
route was available for this optimizer job; each returned `404`.

Engineering confirmed the persistence failure root cause: the optimization
completed, but writing the combined result document to Cosmos DB failed with
HTTP 413 because the candidate payload exceeded the 2 MB item limit.

To avoid result-persistence failures, first run a smaller continuation job from
a compact middle candidate:

```text
continuation job: opt_c9a31d40e8344d19878eaf835277b068
status: succeeded
max_candidates: 5
prompt/skill seed: opt_fff465f7706e4de4a9ac24b1e0177e1e candidate_5 / cand_b659a05f17934e5a957edcaac483574f
tool seed: opt_be11872f07684ae1a1ad03a0fa56853b candidate_8 / cand_f6ca5f60997545088353005148ef57a8
payload size: about 201 KB
model_search_space: gpt-5-mini, gpt-4.1
```

That setup proved the smaller 5-candidate shape could persist successfully, but
its baseline was too strong for the demo. The accepted golden optimization run
is the follow-up weak-baseline run:

```text
golden optimization run: opt_994a956b2d6e49939506323a15dfc5d2
status: succeeded
max_candidates: 5
runtime source: Forge hosted version 52
baseline: cand_bc834224066e45d8938aa2fa738a9720, score 0.5084, pass rate 50%
candidate_1: cand_ff59c418490e4fd9bd3380d8e8e2a732, score 0.8159
candidate_2: cand_270e4602da7b41aeb47c82d3cfbbdd01, score 0.8379
candidate_3: cand_9f784632464f4155a7f532b37288806f, score 0.8344
best: candidate_4 / cand_6bf6980ed16f4538ba0faf8935d93c01, score 0.8521, pass rate 100%
best strategy: skills + system_prompt
score lift: +0.3437
```

Treat `opt_994a956b2d6e49939506323a15dfc5d2` as the clean golden optimization
run: it has persisted `succeeded` lineage, starts from a realistic weak baseline
around 50%, shows the visible hill climb
`0.5084 -> 0.8159 -> 0.8379 -> 0.8344 -> 0.8521`, and avoids the Cosmos DB
HTTP 413 result-persistence failure seen in the larger 10-candidate runs.

Additional 60%-baseline rerun:

```text
continuation job: opt_673c376685644c5f88e33406ac2828e8
status: failed; deleted from Foundry data plane after review
max_candidates: 5
seed: opt_be11872f07684ae1a1ad03a0fa56853b candidate_1 / cand_3d1b0cad37204aad84c5bb4b1461a6fd
seed score: 0.6237
seed pass rate: 100%
payload size: about 181 KB
model_search_space: gpt-5-mini, gpt-4.1
intent: start from a middling baseline with enough room for a visible climb while avoiding Cosmos DB HTTP 413 persistence failures.
```
Use this signal to harden RFT prep before live submission. The deterministic
RFT grader should reward the strict `expert_evidence` JSON contract, required
evidence item metadata (`claim`, `supports`, `source_ref`, `classification`,
`confidence`), and explicit `unsupported[]` gap reporting. It should penalize
custom JSON shapes, missing `invoice_id`, missing citations/classifications,
final invoice decisions, recovery/dispute execution, and Waypoint writes.

For the current v2 Blossom/MAI path, treat
`graders\contract-policy-expert\contract_policy_evidence_grader.py` as the
reference implementation. It should be augmented before live submission rather
than reused unchanged:

- wrap it as a Blossom endpoint grader that maps Blossom's request body into the
  grader's `sample` and `item` inputs and returns a numeric `score`;
- keep the endpoint self-contained, with no dependency on local Caliber imports;
- align the Blossom `response_format.json_schema` with the grader's required
  `expert_evidence` fields;
- add v2-specific checks for retrieval discipline, cited-source availability,
  no invented write/recovery actions, and current `contract-policy-expert`
  identity/correlation fields;
- return or log per-dimension diagnostics for pre-submit calibration, even if
  the live Blossom endpoint response is just `{ "score": <number> }`;
- recalibrate `pass_threshold` against current v2 baseline/optimized outputs.

Caliber stores the local request and status snapshots under ignored run storage:

```text
runs\optimizer\contract-policy-expert\optimizer-submit-request.json
runs\optimizer\contract-policy-expert\optimizer-submit-response.json
runs\optimizer\contract-policy-expert\optimizer-status-opt_182bc0626ed04f55bb5e2f04e9cc74a1.json
runs\optimizer\contract-policy-expert\optimizer-submit-request-procedural-10.json
runs\optimizer\contract-policy-expert\optimizer-submit-response-procedural-10.json
runs\optimizer\contract-policy-expert\optimizer-status-opt_fff465f7706e4de4a9ac24b1e0177e1e.json
runs\optimizer\contract-policy-expert\optimizer-submit-request-full-surface-v52.json
runs\optimizer\contract-policy-expert\optimizer-submit-response-full-surface-v52.json
runs\optimizer\contract-policy-expert\optimizer-status-opt_be11872f07684ae1a1ad03a0fa56853b.json
```

Monitor:

```powershell
azd ai agent optimize status <operation-id> --watch
```

Do not deploy directly from optimizer. Apply the selected candidate locally, then
review the Forge diff:

```powershell
azd ai agent optimize apply --candidate <candidate-id>
```

After approval, Forge can deploy the optimized source. Caliber then reruns the
same `contract-policy-expert-foundryiq-calibration` eval and compares baseline
versus optimized behavior.

## 6. FT/RFT for cost optimization

FT/RFT happens after optimizer. The goal is to preserve optimized behavior on a
cheaper model, not to replace the optimizer. For the current v2 lane, use the
checked-in `contract-policy-expert` `gpt-6-astra` baseline/optimized configs as
the teacher source and choose the lower-cost RFT base model only after current
Foundry model support is verified. Historical `o4-mini` job IDs below are
reference-only and are not proof of a current v2 RFT candidate.

Plan the RFT job:

```powershell
$Caliber = "C:\path\to\caliber"
$ProjectEndpoint = "<foundry-project-endpoint>"
$Agent = "contract-policy-expert"
$RftBaseModel = "MAI-Code-1-Flash"
$DatasetDir = "$Caliber\datasets\$Agent"

Set-Location $Caliber

uv run caliber rft plan `
  --train "$DatasetDir\$Agent-train.jsonl" `
  --validation "$DatasetDir\$Agent-validation.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --base-model $RftBaseModel `
  --project-endpoint $ProjectEndpoint `
  --suffix "$Agent-cost" `
  --json
```

Package local RFT artifacts while the optimizer runs:

```powershell
uv run caliber rft package `
  --train "$DatasetDir\$Agent-train.jsonl" `
  --validation "$DatasetDir\$Agent-validation.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --agent $Agent `
  --base-model $RftBaseModel `
  --suffix "$Agent-cost" `
  --optimizer-job-id <optimizer-job-id> `
  --json
```

This writes ignored, reviewable packaging artifacts:

```text
runs\rft\contract-policy-expert\contract-policy-expert-rft-train.jsonl
runs\rft\contract-policy-expert\contract-policy-expert-rft-validation.jsonl
runs\rft\contract-policy-expert\contract-policy-expert-rft-grader.py
runs\rft\contract-policy-expert\contract-policy-expert-rft-job.dry-run.json
runs\rft\contract-policy-expert\manifest.json
```

The package is intentionally marked `ready_for_live_submit: false` until the
optimizer candidate is selected, applied after review, the calibration eval is
rerun, RFT base-model support is verified, and live RFT spend is explicitly
approved. A normal serving deployment of the selected RFT base model is not
required before submission, but current Foundry RFT support must be verified in
the target project before any live job is submitted.

For expanded RFT review packaging, concatenate the reviewed scenario and
contract-clause source rows into ignored `runs\rft\<agent>-expanded\` source
files, then run `caliber rft package` against those combined source files. The
current generated expanded package shape is 236 train rows and 46 validation
rows before live-submission gates.

Before submitting a real FT/RFT job:

1. Review the optimized-agent eval result.
2. Decide the accepted quality band versus the optimized hosted agent.
3. Calibrate or replace the deterministic grader so it matches the Foundry rubric
   failure boundary.
4. Package and load-test the v2 Blossom endpoint grader, including credential
   handling via headers rather than grader URL query parameters.
5. Submit FT/RFT only when the cheaper model has a clear cost target and a
   reviewed reward/eval gate.

Historical live RFT submission for the accepted golden candidate:

```text
project endpoint: https://ai-account-wi2egf4sh4hfq.services.ai.azure.com/api/projects/ai-project-forge
model: o4-mini-2025-04-16
job: ftjob-0265d673736e496dbd360530958c6149
status at submit: pending
training file: file-4272b94eaf5a476e95248922c36bc1b0
validation file: file-5bd1f7647832481a92a2ec9ab9fe99a7
package: runs\rft\contract-policy-expert-expanded
```

Treat that submission as historical evidence only. For v2, create a fresh
package, fresh current lineage snapshot, and fresh submit record from the
currently deployed `contract-policy-expert` source and eval assets.

## Promotion criteria

Promote a cheaper FT/RFT model only if:

1. It stays within the accepted quality band of the optimized hosted
   `contract-policy-expert`.
2. It materially improves cost.
3. It passes the same Foundry-generated rubric/eval gate.
4. Caliber records the eval IDs, run IDs, output-items, grader thresholds, and
   promotion decision.
