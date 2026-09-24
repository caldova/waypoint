# OBSERVE: datasets to rubrics to evals

OBSERVE is the quality-discovery part of the Caliber loop for a Forge hosted
agent. It turns source datasets into a Foundry-generated rubric/evaluator,
runs a baseline eval, exports per-sample output-items, and calibrates Caliber's
deterministic grader against the observed outputs.

Use `docs\TUNE.md` for the optimizer and RFT handoff steps that follow this
baseline observation work.

## What this covers

1. Build Caliber datasets from a read-only data source.
2. Generate a Foundry rubric/evaluator from those datasets.
3. Run a baseline eval against a deployed Forge hosted agent.
4. Export Foundry output-items back into Caliber.
5. Calibrate Caliber's deterministic grader against the eval outputs.

## Inputs

Set these values for the environment you are working in:

```powershell
$Caliber = "<path-to-caliber>"
$Forge = "<path-to-forge>"
$Ledgerfield = "<path-to-ledgerfield>"
$ProjectEndpoint = "<foundry-project-endpoint>"
$EvalModel = "<deployed-eval-model>"
$Agent = "contract-policy-expert"
$DatasetDir = "$Caliber\datasets\$Agent"
$RunDir = "$Caliber\runs\eval-results\$Agent"
```

Keep generated eval runs, output-items, and local run snapshots under ignored
`runs\` storage. Do not commit tenant-specific endpoints, local worktree paths,
or live eval/run IDs.

## Step 1 - Refresh local references

```powershell
git -C $Caliber fetch --all --prune
git -C $Forge fetch --all --prune
git -C $Ledgerfield fetch --all --prune
```

Expected result: remote refs refresh cleanly.

## Step 2 - Validate Caliber

```powershell
Set-Location $Caliber
uv sync
uv run caliber doctor --json
uv run caliber manifest --json
```

Expected result: `doctor` and `manifest` both succeed.

## Step 3 - Build scenario-derived datasets

```powershell
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

## Step 4 - Stage eval-generation input

```powershell
New-Item -ItemType Directory -Force $RunDir | Out-Null
Copy-Item "$DatasetDir\$Agent-eval.jsonl" `
  "$RunDir\$Agent-foundryiq-eval-input.jsonl" `
  -Force
```

Expected ignored output:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-foundryiq-eval-input.jsonl
```

## Step 5 - Generate Foundry rubric/eval config

Run the rubric/eval generation from Forge so the generated evaluator sees the
agent prompt and deployed agent context:

```powershell
Set-Location $Forge
azd ai agent eval generate `
  --agent $Agent `
  --project-endpoint $ProjectEndpoint `
  --dataset "$RunDir\$Agent-foundryiq-eval-input.jsonl" `
  --gen-instruction-file "$Forge\agents\$Agent\prompt.md" `
  --eval-model $EvalModel `
  --max-samples 15 `
  --name "$Agent-foundryiq-calibration" `
  --out-file "$RunDir\$Agent-foundryiq-calibration.eval.yaml" `
  --no-prompt `
  -o json
```

Expected ignored output:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-foundryiq-calibration.eval.yaml
```

Review the generated rubric dimensions before running the eval. For
`contract-policy-expert`, the useful rubric shape should cover evidence
grounding, retrieval discipline, query specificity, JSON contract compliance,
read-only behavior, gap/conflict reporting, information governance, and general
quality.

## Step 7 - Run baseline eval

```powershell
Set-Location $Forge
azd ai agent eval run `
  --config "$RunDir\$Agent-foundryiq-calibration.eval.yaml" `
  --name "$Agent-foundryiq-calibration-run" `
  --no-wait `
  --no-prompt `
  -o json
```

Record the returned eval ID and run ID in local ignored notes or shell
variables, not in committed docs:

```powershell
$EvalId = "<eval-id>"
$BaselineRunId = "<eval-run-id>"
```

## Step 8 - Inspect completed eval run

```powershell
Set-Location $Forge
azd ai agent eval show $EvalId `
  --eval-run-id $BaselineRunId `
  --out-file "$RunDir\$Agent-foundryiq-calibration-run.json" `
  --no-prompt `
  -o json
```

Expected ignored output:

```text
runs\eval-results\contract-policy-expert\contract-policy-expert-foundryiq-calibration-run.json
```

## Step 9 - Export output-items to Caliber

```powershell
Set-Location $Caliber
uv run caliber eval export-output-items `
  --project-endpoint $ProjectEndpoint `
  --eval-id $EvalId `
  --run-id $BaselineRunId `
  --out "$RunDir\output-items.jsonl" `
  --json
```

Expected ignored output:

```text
runs\eval-results\contract-policy-expert\output-items.jsonl
```

## Step 10 - Calibrate deterministic grader

```powershell
uv run caliber grader calibrate `
  --dataset "$DatasetDir\$Agent-eval.jsonl" `
  --outputs "$RunDir\output-items.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --json
```

Use this result to decide whether the deterministic grader is aligned enough
with the Foundry-generated rubric to support RFT reward design.

## Output contract for OBSERVE

After this flow, Caliber should have:

- Durable dataset rows under `datasets\contract-policy-expert\*.jsonl`
- Generated eval config under ignored `runs\eval-results\contract-policy-expert\`
- Baseline eval summary under ignored `runs\eval-results\contract-policy-expert\`
- Per-sample output-items under ignored `runs\eval-results\contract-policy-expert\`
- A deterministic grader calibration summary for the baseline run
