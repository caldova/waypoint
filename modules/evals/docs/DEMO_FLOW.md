# Caliber demo flow

This flow shows the intended Caliber sequence for Forge's hosted
`contract-policy-expert` FoundryIQ candidate:

1. Use Foundry eval generation to create rubric/eval assets.
2. Run baseline evals against the hosted agent.
3. Tune the hosted agent with Agent Optimizer to improve accuracy.
4. Use RFT to move the optimized behavior to a cheaper model for cost.

Caliber owns datasets, generated eval configs, output-items, evaluator lineage,
optimizer/RFT run metadata, and promotion records. Forge remains the runtime
source of truth and consumes only reviewed, promoted gates.

Do not commit tenant-specific Foundry endpoints, subscription IDs, resource IDs,
uploaded-file metadata, optimizer job state, or generated run outputs.

## Variables

```powershell
$Caliber = "C:\path\to\caliber"
$Forge = "C:\path\to\forge"
$Ledgerfield = "C:\path\to\ledgerfield"
$ProjectEndpoint = "<foundry-project-endpoint>"
$EvalModel = "gpt-6-astra"
$OptimizationModel = "gpt-5.5"
$RftBaseModel = "MAI-Code-1-Flash"
$Agent = "contract-policy-expert"
$DatasetDir = "$Caliber\datasets\$Agent"
$RunDir = "$Caliber\runs\eval-results\$Agent"
```

## 1. Build the Caliber seed datasets

```powershell
uv run caliber datasets contract-policy build `
  --ledgerfield-path $Ledgerfield `
  --agent $Agent `
  --variants-per-scenario 8 `
  --json
```

Expected durable outputs:

```text
datasets\contract-policy-expert\contract-policy-expert-train.jsonl
datasets\contract-policy-expert\contract-policy-expert-validation.jsonl
datasets\contract-policy-expert\contract-policy-expert-eval.jsonl
```

## 2. Generate Foundry rubric/eval assets

Use Foundry to generate the rubric evaluator and eval config. Caliber should keep
the generated config and lineage under ignored `runs\` storage until reviewed.

```powershell
New-Item -ItemType Directory -Force $RunDir | Out-Null

azd ai agent eval generate `
  -C $Forge `
  --agent $Agent `
  --project-endpoint $ProjectEndpoint `
  --dataset "$DatasetDir\$Agent-eval.jsonl" `
  --gen-instruction-file "$Forge\agents\$Agent\prompt.md" `
  --eval-model $EvalModel `
  --max-samples 15 `
  --name "$Agent-foundryiq-baseline" `
  --out-file "$RunDir\$Agent-foundryiq-baseline.eval.yaml" `
  --no-wait `
  --no-prompt `
  -o json
```

Review the generated rubric dimensions before treating the evaluator as a
promotable quality gate.

## 3. Run the baseline eval

```powershell
azd ai agent eval run `
  -C $Forge `
  --config "$RunDir\$Agent-foundryiq-baseline.eval.yaml" `
  --name "$Agent-foundryiq-baseline-run" `
  --no-wait `
  --no-prompt `
  -o json
```

After the run completes, export per-sample output-items for Caliber calibration:

```powershell
uv run caliber eval export-output-items `
  --project-endpoint $ProjectEndpoint `
  --eval-id <eval-id> `
  --run-id <run-id> `
  --out "$RunDir\output-items.jsonl" `
  --json
```

## 4. Calibrate the deterministic grader

```powershell
uv run caliber grader calibrate `
  --dataset "$DatasetDir\$Agent-eval.jsonl" `
  --outputs "$RunDir\output-items.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --json
```

The grader should be strict enough to expose baseline gaps before optimizer work.

## 5. Plan Agent Optimizer readiness

```powershell
uv run caliber optimizer plan `
  --forge-path $Forge `
  --agent $Agent `
  --dataset "$DatasetDir\$Agent-eval.jsonl" `
  --eval-config "$RunDir\$Agent-foundryiq-baseline.eval.yaml" `
  --json
```

Do not submit an optimizer job until the Forge hosted agent is optimizer-ready:
the hosted source needs optimization SDK wiring, `load_config()`, and baseline
instruction/config files as required by Foundry Agent Optimizer.

## 6. Tune the hosted agent for accuracy

Run Agent Optimizer only after the rubric/eval assets are reviewed and the hosted
agent is optimizer-ready.

```powershell
azd ai agent optimize `
  -C $Forge `
  --agent $Agent `
  --project-endpoint $ProjectEndpoint `
  --config "$RunDir\$Agent-foundryiq-baseline.eval.yaml" `
  --eval-model $EvalModel `
  --optimize-model $OptimizationModel `
  --target instruction `
  --no-wait `
  --no-prompt `
  -o json
```

When the optimizer run completes, apply the selected candidate locally in Forge
for review, then redeploy only after approval.

## 7. Re-run evals after optimizer

```powershell
azd ai agent eval run `
  -C $Forge `
  --config "$RunDir\$Agent-foundryiq-baseline.eval.yaml" `
  --name "$Agent-foundryiq-optimized-run" `
  --no-wait `
  --no-prompt `
  -o json
```

Export output-items again and compare baseline versus optimized behavior. The
optimized run becomes the quality target for cheaper-model RFT.

## 8. Plan RFT for cost optimization

Use the accepted optimizer run as the transition point from accuracy to cost.
The table below is the historical Caldova review shape; for current v2 work,
replace it with fresh current optimizer/eval lineage from the deployed
`contract-policy-expert` that is actually present in the target Foundry project.
Do not reuse the historical fine-tuned model or deployment as the v2 candidate
unless a new eval proves it is attached to the current v2 source and behavior.

| Step | Run/candidate | Score | Meaning |
|---|---|---:|---|
| Baseline | `opt_994a956b2d6e49939506323a15dfc5d2` / `cand_bc834224066e45d8938aa2fa738a9720` | `0.5084` | Start low enough to show learning signal |
| Climb 1 | `cand_ff59c418490e4fd9bd3380d8e8e2a732` | `0.8159` | Optimizer makes the first major quality jump |
| Climb 2 | `cand_270e4602da7b41aeb47c82d3cfbbdd01` | `0.8379` | Search finds a stronger candidate |
| Explore | `cand_9f784632464f4155a7f532b37288806f` | `0.8344` | Slight regression shows hill climbing is search, not a straight line |
| Peak | `cand_6bf6980ed16f4538ba0faf8935d93c01` | `0.8521` | Historical optimized behavior target |

RFT starts from the peak. It should preserve the optimized behavior while moving
serving economics to a supported lower-cost RFT base model.

```powershell
uv run caliber rft plan `
  --train "$DatasetDir\$Agent-train.jsonl" `
  --validation "$DatasetDir\$Agent-validation.jsonl" `
  --grader "$Caliber\graders\$Agent\contract_policy_evidence_grader.py" `
  --base-model $RftBaseModel `
  --project-endpoint $ProjectEndpoint `
  --suffix "$Agent-cost" `
  --json
```

Submit a live RFT job only after the optimized hosted agent establishes the
quality target and the training/validation rows are reviewed. The RFT goal is not
to discover better behavior than the optimizer; it is to preserve the optimized
behavior on a cheaper model.

## 9. Evaluate and promote

After deploying a fine-tuned checkpoint to a review deployment, run the same eval
suite against:

```text
baseline hosted agent
optimized hosted agent
fine-tuned cheap-model candidate
```

Promote only if the cheaper fine-tuned model stays within the accepted quality
band of the optimized hosted agent and materially improves cost.
