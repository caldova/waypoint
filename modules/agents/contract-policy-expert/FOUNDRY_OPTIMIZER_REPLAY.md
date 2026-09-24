# Contract Policy Expert Foundry Optimizer replay

Use this runbook to repeat the CPE optimizer demo in another tenant,
subscription, or production Foundry project.

The goal is to reproduce the same story:

1. Generate a CPE-specific rubric evaluator.
2. Start from the weak but functional CPE baseline.
3. Evaluate the weak baseline.
4. Run Foundry Agent Optimizer.
5. Deploy the better CPE assets.
6. Run the same generated-rubric eval on the improved deployed CPE.

Do not mix this with the later fine-tuning workstream. This run tunes agent
assets only: instructions and tool descriptions.

## Dataset scope

Use only the main CPE invoice-assurance dataset family for this replay:

| Split | File | Rows | Purpose |
| --- | --- | ---: | --- |
| Train | `modules\evals\datasets\contract-policy-expert\contract-policy-expert-train.jsonl` | 80 | Optimizer candidate generation |
| Validation | `modules\evals\datasets\contract-policy-expert\contract-policy-expert-validation.jsonl` | 16 | Candidate sanity check / selection when the optimizer path supports validation |
| Test | `modules\evals\datasets\contract-policy-expert\contract-policy-expert-eval.jsonl` | 24 | Named before/after demo evals |

These splits are supplier holdouts, not random row splits:

- train: `cmo-001` through `cmo-010`
- validation: `cmo-011`, `cmo-012`
- test/eval: `cmo-013`, `cmo-014`, `cmo-015`

The old `contract-policy-expert-contracts-*` dataset family is retired for this
CPE red-thread demo. It belongs to a different contract-clause narrative. Do not
use query-shaped workaround files either. If Foundry needs a narrower input
shape, generate Foundry-facing files from these three canonical splits and keep
their source lineage explicit.

## Fast replay checklist

Use this when rerunning the demo in the same or another Foundry project.

1. Deploy the intentionally weak baseline CPE.
2. Generate or verify the generated rubric evaluator.
3. Generate the query-shaped held-out test file from the canonical test split.
4. Run `contract-policy-expert-baseline` five times with
   `scripts\run-foundry-precomputed-eval.py`.
5. Run Agent Optimizer against the train split.
6. Preserve the winning candidate as a named `.agent_configs\optimized-*`
   snapshot, then copy it into `.agent_configs\baseline`.
7. Deploy the optimized CPE.
8. Run `contract-policy-expert-optimized` five times with the same generated
   rubric and same held-out test split.
9. Present the five baseline runs and five optimized runs as the before/after
   story; keep optimizer candidate runs as supporting evidence.

The reference Caldova before/after result is:

| Eval | Hosted-agent version | Result |
| --- | ---: | ---: |
| `contract-policy-expert-baseline` | `12` | 3 passed / 21 failed / 24 total |
| `contract-policy-expert-optimized` | `13` | 21 passed / 3 failed / 24 total |

For final demo evidence, regenerate responses for every repeat run. Do not
create five runs by regrading the same uploaded response Data asset. Regrading a
single response asset is useful for judge-stability debugging, but it does not
show end-to-end agent repeatability.

## Known good reference run

This was the first successful run in the Caldova project.

| Field | Value |
| --- | --- |
| Project endpoint | `https://ai-account-wfckthnpbzzia.services.ai.azure.com/api/projects/caldova-agents` |
| Optimizer job | `opt_58bea824c02e420992e28cee71f281b9` |
| Eval definition | `eval_20b2995b658a4506919b39aa6a4ad300` |
| Rubric evaluator | `contract-policy-expert-generated-rubric`, version `7` |
| Dataset size used | 15 train examples |
| Agent under optimization | `gpt-6-astra`, model version `2026-09-03` |
| Generated-rubric judge/eval model | `gpt-6-astra`, model version `2026-09-03` |
| Optimizer reflection model | `gpt-5.5`, model version `2026-04-24` |
| Baseline eval run | `evalrun_c9625d5a3ade48bea4cfefd2993bac22` |
| Best candidate eval run | `evalrun_d2a14edd2f4046678a134d6918c0f997` |
| Baseline result | 2 passed / 13 failed / 15 total, avg score `0.3779` |
| Best result | 15 passed / 0 failed / 15 total, avg score `0.8203` |
| Best candidate | `cand_opt_58bea824c02e420992e28cee71f281b9_0003` |

## Prerequisites in the target tenant

Run these checks before starting.

1. Sign in to the target tenant and subscription.

   ```powershell
   az login --tenant <tenant-id>
   az account set --subscription <subscription-id>
   azd auth login
   ```

2. Confirm the deployed Foundry project endpoint.

   ```powershell
   $ProjectEndpoint = "<target-foundry-project-endpoint>"
   ```

3. Confirm the target project has model deployments for both roles.

   - Agent under optimization: `gpt-6-astra`
   - Generated-rubric judge/eval model: `gpt-6-astra`
   - Optimizer reflection model: `gpt-5.5` or another model allowed by Agent
     Optimizer

   In the reference run, `gpt-6-astra` worked as the hosted agent model under
   optimization and as the generated-rubric judge/eval model. It failed only
   for `optimization_model`, the optimizer reflection role. Keep the CPE agent
   and judge/eval model on Astra and use `gpt-5.5` only for reflection.

4. Confirm local tool versions. The reference run used:

   ```text
   azd 1.32.0
   azure.ai.agents azd extension 1.0.0-beta.16
   azure.ai.projects azd extension 1.0.0-beta.11
   Python 3.13.7
   azure-ai-projects 2.7.0
   azure-ai-agentserver-optimization 1.0.0b1
   azure-identity 1.26.0b2
   ```

5. Confirm the signed-in user or service principal can call the Foundry project
   and Responses APIs. The reference run needed permissions that covered:

   - `Microsoft.CognitiveServices/accounts/OpenAI/responses/write`
   - project-level agent/eval operations

   If rubric generation fails with a missing `responses/write` action, fix RBAC
   before changing eval or optimizer payloads.

## Step 0. Confirm the weak baseline is active

The demo intentionally starts from a weak but plausible CPE baseline:

- `.agent_configs\baseline\instructions.md`
- `.agent_configs\baseline\tools.json`
- `toolbox.py` tool descriptions

The original stronger assets are preserved under:

- `.agent_configs\reference-good\`

The optimized candidate from the reference run is preserved under:

- `.agent_configs\optimized-candidate-3\`

To reset the local source to the weak demo baseline, restore the weak baseline
files before deploying. To promote the preserved optimized candidate without
rerunning the optimizer, copy the candidate snapshot into the active baseline
config:

```powershell
Copy-Item .\.agent_configs\optimized-candidate-3\instructions.md `
  .\.agent_configs\baseline\instructions.md -Force

Copy-Item .\.agent_configs\optimized-candidate-3\tools.json `
  .\.agent_configs\baseline\tools.json -Force
```

Before running production replay, confirm the deployed CPE version was built
from the weak baseline. Otherwise the before score will not tell the demo story.

## Step 1. Generate the rubric evaluator in the target project

Run from `modules\agents\contract-policy-expert`.

```powershell
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"

.\scripts\run-foundry-optimizer-demo.ps1 `
  -ProjectEndpoint $ProjectEndpoint `
  -EvalModel gpt-6-astra `
  -OptimizerModel gpt-5.5 `
  -SkipOptimize
```

This runs:

- `azd ai agent eval generate`
- local rubric asset validation through Caliber

Expected local outputs:

- `eval.yaml`
- `evaluators\contract-policy-expert-generated-rubric\rubric_dimensions.json`

After generation, verify `eval.yaml` contains the target tenant evaluator
version:

```powershell
Select-String -Path .\eval.yaml -Pattern "evaluators:","name:","version:"
```

Do not assume the evaluator version will be `7` in another tenant.

## Step 1a. Register the CPE datasets in Foundry

For production replay, register the canonical train, validation, and test
datasets in the target Foundry project instead of relying on inline data.

Register:

- `contract-policy-expert-train`
- `contract-policy-expert-validation`
- `contract-policy-expert-test`

Use the three canonical files from the dataset scope section. Capture the
registered dataset names and versions in the run notes. The named baseline and
optimized evals should use the registered test dataset.

For the portal-visible precomputed-response eval path, also generate the
query-shaped test file from the canonical test split:

```powershell
uv --directory ..\..\evals run caliber datasets contract-policy foundry-eval-input `
  --source datasets\contract-policy-expert\contract-policy-expert-eval.jsonl `
  --out ..\agents\contract-policy-expert\.foundry\datasets\contract-policy-expert-test-foundry-eval\contract-policy-expert-eval-foundry.jsonl `
  --json
```

Keep this generated file under `.foundry\datasets\`; the canonical source of
truth remains `modules\evals\datasets\contract-policy-expert\contract-policy-expert-eval.jsonl`.

## Step 2. Validate local eval assets

Run from the repo root.

```powershell
uv --directory modules\evals run caliber eval validate-assets `
  --eval-config ..\agents\contract-policy-expert\eval.yaml `
  --json
```

Expected result:

```json
{ "ok": true }
```

If this fails, fix local paths or generated rubric assets before submitting an
optimizer job.

## Step 3. Run the named baseline evals

Run five named evals against the deployed weak CPE using the held-out test split.

Use the same eval family name and unique run/Data versions:

```text
contract-policy-expert-baseline
```

The current reliable portal path is a precomputed-response replay:

1. Read the query-shaped held-out test data.
2. Invoke the deployed hosted CPE through its Responses endpoint.
3. Write eval-shaped rows with `query`, `response`, `expected_behavior`,
   `tool_calls`, and `tool_definitions`.
4. Upload those rows as a new Foundry Data asset version.
5. Create a portal eval run whose JSONL source points at that uploaded Data
   asset.

Run from `modules\agents\contract-policy-expert`:

```powershell
uv run python .\scripts\run-foundry-precomputed-eval.py `
  --project-endpoint $ProjectEndpoint `
  --output .foundry\results\contract-policy-expert-baseline-precomputed.jsonl `
  --eval-name contract-policy-expert-baseline `
  --run-name contract-policy-expert-baseline-run-1 `
  --dataset-name contract-policy-expert-baseline-responses `
  --dataset-version baseline-run-1
```

Repeat the command five times, changing both `--output`, `--run-name`, and
`--dataset-version` each time. Each repeat must invoke the deployed CPE again
and produce fresh responses:

```text
baseline-run-1
baseline-run-2
baseline-run-3
baseline-run-4
baseline-run-5
```

`eval.yaml` remains the optimizer/train config. `eval.baseline.yaml` remains the
documented native target config, but the Caldova replay currently uses the
precomputed-response script because the native `azure_ai_agent` target adapter
accepted the registered test Data asset and agent version but stayed in progress
at `0/0` item results. Direct Responses calls to the same hosted CPE succeeded,
and the uploaded-Data JSONL replay completed in the portal.

The uploaded eval-shaped Data asset is the source for the portal run. Its run
payload uses:

```json
{
  "data_source": {
    "type": "jsonl",
    "source": {
      "type": "file_id",
      "id": "azureai://accounts/.../data/contract-policy-expert-baseline-responses/versions/..."
    }
  }
}
```

Before a production demo, run a one-row smoke with `--limit 1`, confirm the
portal run completes, delete the smoke eval, and then run the five full 24-row
baseline repeats.

Smoke command:

```powershell
uv run python .\scripts\run-foundry-precomputed-eval.py `
  --project-endpoint $ProjectEndpoint `
  --output .foundry\results\contract-policy-expert-baseline-precomputed-smoke.jsonl `
  --eval-name contract-policy-expert-baseline-smoke `
  --run-name contract-policy-expert-baseline-smoke `
  --dataset-name contract-policy-expert-baseline-responses-smoke `
  --dataset-version smoke-1 `
  --limit 1
```

Delete the smoke eval before running the demo baseline so the portal stays
clean. The reference project used:

```powershell
$Token = az account get-access-token --scope https://ai.azure.com/.default --query accessToken -o tsv
$Headers = @{ Authorization = "Bearer $Token" }
Invoke-WebRequest -Method Delete `
  -Headers $Headers `
  -Uri "$ProjectEndpoint/openai/v1/evals/<smoke-eval-id>"
```

Record:

- eval definition ID
- eval run ID
- pass/fail counts
- generated-rubric average score
- report URL

This is the first artifact the demo audience should see in Foundry.

Reference Caldova first baseline result:

| Field | Value |
| --- | --- |
| Eval definition | `eval_511340e70c8949749bb38cdd9e923e6f` |
| Eval run | `evalrun_709d16ab3c9a4fbf94a20c757882a71d` |
| Uploaded response Data asset | `contract-policy-expert-baseline-responses`, version `baseline-20260924-fileid-1` |
| Result | 3 passed / 21 failed / 24 total |
| Report URL | <https://ai.azure.com/nextgen/r/m_L8s3oGRQu5dJFUQ6RR5g,rg-caldova-agents,,ai-account-wfckthnpbzzia,caldova-agents/build/evaluations/eval_511340e70c8949749bb38cdd9e923e6f/run/evalrun_709d16ab3c9a4fbf94a20c757882a71d> |

## Step 4. Submit the optimizer job

Use the SDK submitter or the equivalent registered-dataset optimizer request. It
reads the generated evaluator name/version from
`eval.yaml`, keeps the agent under optimization on Astra, uses Astra for the
generated-rubric judge/eval model when passed with `--eval-model`, and defaults
the optimizer reflection model to `gpt-5.5`.

Run from `modules\agents\contract-policy-expert`.

```powershell
uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint $ProjectEndpoint `
  --eval-model gpt-6-astra `
  --optimization-model gpt-5.5 `
  --max-candidates 4 `
  --max-items 15 `
  --wait
```

Capture the printed optimizer job ID. If the initial poller does not return an
ID, list recent jobs:

```powershell
uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint $ProjectEndpoint `
  --list `
  --limit 5
```

Then inspect the job:

```powershell
uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint $ProjectEndpoint `
  --status-job-id <optimizer-job-id>
```

Record:

- optimizer job ID
- baseline score
- best candidate ID
- best candidate score
- baseline eval run ID
- best candidate eval run ID
- mutation keys, usually `system_prompt` and `tools`

The optimizer's baseline and candidate eval runs are supporting evidence. The
final demo proof still comes from the named baseline eval and named optimized
eval on the deployed agent.

## Step 5. Export optimizer candidate eval runs

The optimizer job creates a real eval run for the baseline and for each
candidate. Export the baseline and best candidate run details for supporting
evidence.

Create an evidence folder outside source control:

```powershell
$EvidenceDir = "$env:TEMP\cpe-optimizer-evidence"
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
```

Export the baseline run:

```powershell
azd ai agent eval show <eval-id> `
  --eval-run-id <baseline-eval-run-id> `
  --project-endpoint $ProjectEndpoint `
  --out-file "$EvidenceDir\baseline.json" `
  -o json
```

Export the best candidate run:

```powershell
azd ai agent eval show <eval-id> `
  --eval-run-id <best-candidate-eval-run-id> `
  --project-endpoint $ProjectEndpoint `
  --out-file "$EvidenceDir\candidate-best.json" `
  -o json
```

For the reference run, this produced:

| Run | Eval run | Result |
| --- | --- | --- |
| Baseline | `evalrun_c9625d5a3ade48bea4cfefd2993bac22` | 2 passed / 13 failed / 15 total |
| Candidate 3 | `evalrun_d2a14edd2f4046678a134d6918c0f997` | 15 passed / 0 failed / 15 total |

## Step 6. Apply and deploy the best candidate

Only do this after reviewing the candidate diff.

Preferred flow:

```powershell
azd ai agent optimize apply --candidate <best-candidate-id>
git --no-pager diff
azd deploy
```

If the optimizer job was submitted through the SDK fallback, `azd ai agent
optimize apply` may not see the job in local azd state. In that case, fetch the
candidate payload from the project API, write the candidate's `system_prompt`
and `tools` mutations into `.agent_configs\baseline`, and preserve a reusable
snapshot such as `.agent_configs\optimized-candidate-3`.

Reference materialization flow:

```powershell
$JobId = "opt_58bea824c02e420992e28cee71f281b9"
$CandidateId = "cand_opt_58bea824c02e420992e28cee71f281b9_0003"
$Token = az account get-access-token --scope https://ai.azure.com/.default --query accessToken -o tsv
$Headers = @{ Authorization = "Bearer $Token" }
$Candidate = Invoke-WebRequest `
  -Headers $Headers `
  -Uri "$ProjectEndpoint/agent_optimization_jobs/$JobId/candidates/$CandidateId?api-version=v1" `
  | Select-Object -ExpandProperty Content `
  | ConvertFrom-Json

New-Item -ItemType Directory -Force -Path .\.agent_configs\optimized-candidate-3 | Out-Null
$Candidate.mutations.system_prompt |
  Set-Content -Encoding UTF8 .\.agent_configs\optimized-candidate-3\instructions.md

@($Candidate.mutations.tools) |
  ConvertTo-Json -Depth 100 |
  Set-Content -Encoding UTF8 .\.agent_configs\optimized-candidate-3\tools.json

Copy-Item .\.agent_configs\optimized-candidate-3\instructions.md `
  .\.agent_configs\baseline\instructions.md -Force

Copy-Item .\.agent_configs\optimized-candidate-3\tools.json `
  .\.agent_configs\baseline\tools.json -Force
```

PowerShell can unwrap a one-element JSON array when writing `tools.json`. If the
validation below reports `tools: 0`, rewrite the file with Python so the outer
array is preserved:

```powershell
python -c "import json, pathlib; root=pathlib.Path('.'); c=json.loads((root/'.foundry/results/candidate_3_payload.json').read_text(encoding='utf-8-sig')); tools=c['mutations']['tools']; tools=tools if isinstance(tools, list) else [tools]; (root/'.agent_configs/optimized-candidate-3/tools.json').write_text(json.dumps(tools, indent=2, ensure_ascii=False)+'\n', encoding='utf-8'); (root/'.agent_configs/baseline/tools.json').write_text(json.dumps(tools, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')"
```

Validate that the active config loads one tool before deploying:

```powershell
uv run python -c "from pathlib import Path; from castia import load_agent_config; c=load_agent_config(Path('.agent_configs')); print({'model': str(c.model), 'instructions': bool(c.instructions), 'tools': len(c.tool_definitions or [])})"
```

Expected:

```text
{'model': 'gpt-6-astra', 'instructions': True, 'tools': 1}
```

After deploy, record the new active CPE agent version. The Caldova replay
deployed candidate 3 as active hosted-agent version `13`.

## Step 7. Run the named optimized eval

Run the same generated-rubric eval against the improved deployed CPE using the
same held-out test split. As with baseline, run five repeats and regenerate
responses for every repeat.

Use the same eval family name and unique run/Data versions:

```text
contract-policy-expert-optimized
```

Run from `modules\agents\contract-policy-expert`:

```powershell
uv run python .\scripts\run-foundry-precomputed-eval.py `
  --project-endpoint $ProjectEndpoint `
  --output .foundry\results\contract-policy-expert-optimized-precomputed.jsonl `
  --eval-name contract-policy-expert-optimized `
  --run-name contract-policy-expert-optimized-run-1 `
  --dataset-name contract-policy-expert-optimized-responses `
  --dataset-version optimized-run-1 `
  --timeout 240
```

Repeat the command five times, changing both `--output`, `--run-name`, and
`--dataset-version` each time:

```text
optimized-run-1
optimized-run-2
optimized-run-3
optimized-run-4
optimized-run-5
```

Record:

- eval definition ID
- eval run ID
- pass/fail counts
- generated-rubric average score
- report URL

Reference Caldova first optimized result:

| Field | Value |
| --- | --- |
| Optimizer job | `opt_58bea824c02e420992e28cee71f281b9` |
| Candidate | `candidate_3` / `cand_opt_58bea824c02e420992e28cee71f281b9_0003` |
| Preserved optimized config | `.agent_configs\optimized-candidate-3` |
| Active hosted-agent version | `13` |
| Eval definition | `eval_4a62cf93925c41619ba335646737ad91` |
| Eval run | `evalrun_7293ceed0f484fbd84418427efec299c` |
| Uploaded response Data asset | `contract-policy-expert-optimized-responses`, version `optimized-20260924-fileid-1` |
| Result | 21 passed / 3 failed / 24 total |
| Report URL | <https://ai.azure.com/nextgen/r/m_L8s3oGRQu5dJFUQ6RR5g,rg-caldova-agents,,ai-account-wfckthnpbzzia,caldova-agents/build/evaluations/eval_4a62cf93925c41619ba335646737ad91/run/evalrun_7293ceed0f484fbd84418427efec299c> |

## Step 8. Present the demo evidence

For the demo, the clean story is the named deployed-agent before/after eval
families:

```text
Same generated rubric.
Same registered test dataset.
Same agent model.
Same generated-rubric judge/eval model.
Fresh agent responses generated for every repeat run.

contract-policy-expert-baseline: five fresh-response runs
contract-policy-expert-optimized: five fresh-response runs
Changed assets: instructions and tool descriptions
```

Report each run's pass count plus a summary such as min/median/max. Keep
optimizer candidate evals and any same-response regrade batches as supporting
evidence, not the final proof.

## Known issues and fixes

### Native hosted-agent eval target hangs at `0/0`

The intended baseline/optimized eval path is:

```text
registered Foundry Data asset
-> Foundry eval
-> hosted CPE target
-> generated rubric judge
```

In the Caldova replay, the native hosted-agent target adapter accepted the test
Data asset and the CPE agent target, but the run stayed in progress with `0/0`
item results. Pinning the active hosted-agent version did not fix it. Direct
Responses calls to the same deployed CPE completed for the exact held-out test
rows, so this was not an agent outage or bad dataset.

Use the precomputed-response replay until the native `azure_ai_agent` target
adapter is reliable for this flow:

```text
canonical held-out test split
-> query-shaped Foundry eval input
-> deployed CPE Responses calls
-> eval-shaped response JSONL
-> uploaded Foundry Data asset
-> portal eval using data_source.source.file_id
-> generated rubric judge
```

The important payload shape is:

```json
{
  "data_source": {
    "type": "jsonl",
    "source": {
      "type": "file_id",
      "id": "azureai://accounts/.../data/.../versions/..."
    }
  }
}
```

Do not use `data_source.file_id` directly. That shape may create a run but later
fails with `The data field is a required input in the evaluation request body`.

### `azd ai agent optimize --config eval.yaml` asks for instructions

Observed behavior:

```text
instruction is required for optimization
```

This happened even though `eval.yaml` and
`.agent_configs\baseline\metadata.yaml` pointed at the baseline instructions.
When prompts were enabled, the CLI asked how to provide instructions, but this
environment could not answer the prompt:

```text
The handle is invalid
```

Use `scripts\submit-foundry-optimizer-sdk.py` for noninteractive replay.

### `gpt-6-astra` rejected as optimizer reflection model

Observed behavior: Astra worked as the hosted agent model under optimization,
and as the generated-rubric judge/eval model, but the optimizer service rejected
`gpt-6-astra` for `optimization_model`, the reflection role.

Use `gpt-5.5` for `--optimization-model` unless the target project has another
known allowed optimizer model.

### Poller does not print a job ID

If the SDK submit output has a null or missing job ID, list recent jobs:

```powershell
uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint $ProjectEndpoint `
  --list `
  --limit 5
```

Then inspect the newest queued or running job with `--status-job-id`.

### `azd deploy` says infrastructure has not been provisioned

This can happen when the local azd environment lacks deployment bindings even
though the hosted CPE already exists in the Foundry project. Do not run
`azd provision` just to recover this state unless the target project genuinely
needs new infrastructure.

Bind the local azd environment to the existing project, then redeploy:

```powershell
azd env set AZURE_SUBSCRIPTION_ID "<subscription-id>"
azd env set AZURE_RESOURCE_GROUP "<resource-group>"
azd env set AZURE_LOCATION "<region>"
azd env set AZURE_TENANT_ID "<tenant-id>"
azd env set AZURE_AI_PROJECT_ENDPOINT $ProjectEndpoint
azd env set AZURE_AIPROJECT_ENDPOINT $ProjectEndpoint
azd env set FOUNDRY_PROJECT_ENDPOINT $ProjectEndpoint
azd env set AZURE_AI_PROJECT_ID "<project-arm-id>"
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME "gpt-6-astra"
azd env set TOOLBOX_CONTRACT_TOOLBOX_MCP_ENDPOINT "<toolbox-mcp-endpoint-or-empty>"

azd deploy --no-prompt
```

After deploy, verify the active version:

```powershell
azd ai agent show contract-policy-expert --output json
```
