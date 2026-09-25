# Contract Policy Expert Foundry Optimizer replay

Use this runbook to repeat the CPE optimizer demo in another tenant,
subscription, or production Foundry project.

The story is intentionally simple:

1. Start from `.agent_configs\baseline`, the weak but plausible CPE baseline.
2. Run five deployed-agent baseline evals against the same held-out test data.
3. Run Foundry Agent Optimizer from that baseline.
4. Preserve the winning candidate in `.agent_configs\optimized`.
5. Deploy the winning candidate.
6. Run five deployed-agent optimized evals against the same held-out test data.

Do not mix this with the fine-tuning workstream. This story tunes agent assets
only: instructions and tool descriptions.

## Source layout

The checked-in source now has exactly the two story configs:

| Path | Purpose |
| --- | --- |
| `.agent_configs\baseline` | The mediocre demo baseline. It is intentionally invoice-first and under-grounded while still functional. |
| `.agent_configs\optimized` | The best candidate from the production optimizer run, preserved for replay or promotion. |

Keep `.agent_configs\baseline` as the story baseline. If you need to deploy the
optimized agent again, copy the optimized files into the active baseline folder
only for the deployment step, then restore `.agent_configs\baseline` afterward.

## Production Caldova artifact trail

| Artifact | Value |
| --- | --- |
| Foundry project endpoint | `https://aif-caldova.services.ai.azure.com/api/projects/ai-project-caldova` |
| Agent | `contract-policy-expert` |
| Agent/eval model | `gpt-6-astra` |
| Optimizer reflection model | `gpt-5.5` |
| Rubric evaluator | `contract-policy-expert-generated-rubric`, version `13` |
| Held-out dataset | `contract-policy-expert-test-foundry-eval`, version `2.0` |
| Baseline eval group | `contract-policy-expert-baseline` / `eval_2d5a13a976c14355aee3317f87e5e171` |
| Baseline hosted-agent version | `6` |
| Optimizer job | `opt_2fb58fc1723e461d9a1496907d029ac8` |
| Winning candidate | `candidate_14` / `cand_opt_2fb58fc1723e461d9a1496907d029ac8_0014` |
| Winning candidate eval run | `evalrun_8f66da78b917482682045dcdc6c39951` |
| Optimized hosted-agent version | `7` |
| Optimized eval group | `contract-policy-expert-optimized` / `eval_9421539dcd754815b8c5443bca0e971c` |

The optimizer train score improved from `0.455684` to
`0.8000013333333332`. The deployed held-out eval story improved from a noisy
mediocre baseline to consistently perfect optimized runs:

| Group | Runs |
| --- | --- |
| `contract-policy-expert-baseline` | 16/24, 15/24, 11/24, 14/24, 18/24 |
| `contract-policy-expert-optimized` | 24/24, 24/24, 24/24, 24/24, 24/24 |

All final baseline and optimized runs had `0` errored rows.

## Dataset scope

Use only the main CPE invoice-assurance dataset family for this replay:

| Split | File | Rows | Purpose |
| --- | --- | ---: | --- |
| Train | `modules\evals\datasets\contract-policy-expert\contract-policy-expert-train.jsonl` | 80 | Optimizer candidate generation |
| Validation | `modules\evals\datasets\contract-policy-expert\contract-policy-expert-validation.jsonl` | 16 | Candidate sanity check when supported |
| Test | `contract-policy-expert-test-foundry-eval`, version `2.0` in Foundry | 24 | Named before/after demo evals |

The old `contract-policy-expert-contracts-*` dataset family belongs to a
different contract-clause narrative. Do not use it for this invoice-assurance
story.

## Replay checklist

Run from `modules\agents\contract-policy-expert` after selecting the target
tenant, subscription, azd environment, and Foundry project.

1. Confirm `.agent_configs\baseline` is active and deploy it.
2. Verify `contract-policy-expert-generated-rubric` exists in the target
   project, or generate it from `eval.yaml`.
3. Verify the held-out test dataset is registered as
   `contract-policy-expert-test-foundry-eval`, version `2.0`, or register an
   equivalent target-tenant version from the canonical test split.
4. Run five sequential baseline evals in `contract-policy-expert-baseline`.
5. Submit a fresh optimizer job from the mediocre baseline:

   ```powershell
   uv run python .\scripts\submit-foundry-optimizer-sdk.py `
     --project-endpoint $ProjectEndpoint `
     --eval-model gpt-6-astra `
     --optimization-model gpt-5.5 `
     --max-candidates 15 `
     --wait
   ```

6. Record the optimizer job ID, baseline score, best candidate ID, best
   candidate score, best candidate eval run ID, and mutation keys.
7. Fetch the winning candidate payload and write its `system_prompt` and `tools`
   mutations to `.agent_configs\optimized`.
8. Copy `.agent_configs\optimized\instructions.md` and
   `.agent_configs\optimized\tools.json` into `.agent_configs\baseline` only for
   deployment, validate the active config loads one tool, then deploy the
   optimized CPE.
9. Restore `.agent_configs\baseline` to the mediocre baseline in source.
10. Run five sequential optimized evals in `contract-policy-expert-optimized`
    against the same rubric and held-out dataset.

## Native eval REST shape

The reliable production path used native server-side Foundry evals:

- Create the eval with `data_source_config.type = custom`.
- Create each run with `data_source.type = azure_ai_target_completions`.
- Set `target.type = azure_ai_agent`.
- Set `target.name = contract-policy-expert`.
- Pin `target.version` to the deployed baseline or optimized version.
- Use the dataset source:

  ```text
  azureai://accounts/aif-caldova/projects/ai-project-caldova/data/contract-policy-expert-test-foundry-eval/versions/2.0
  ```

`azure_ai_target_completions` is valid as the run `data_source.type`, not as the
eval `data_source_config.type`.

## Perils and fixes

### Keep the baseline genuinely mediocre

The before score only tells the story if the deployed baseline was built from
the early prototype baseline. A too-strong baseline hides the optimizer lift; a
too-broken baseline produces a cartoonish `0/24` result. The final baseline is
intentionally weak but plausible.

### Do not leave the optimized candidate in active baseline source

Deploying the optimized candidate requires copying optimized assets into the
active baseline folder because the loader expects the parent `.agent_configs`
layout. After deployment, restore `.agent_configs\baseline` so source remains:

```text
baseline = mediocre story baseline
optimized = best candidate
```

### Run eval repeats sequentially

Concurrent native eval runs caused errored rows during the production replay.
Sequential runs completed cleanly and produced the final stage evidence. For
demo-quality artifacts, run baseline and optimized repeats one at a time.

### Set `--max-candidates` when submitting the job

Optimizer jobs cannot be extended after completion. To explore more candidates,
submit a new pristine job from the intended baseline with the desired
`--max-candidates` value.

### Clear stale optimizer state before a pristine rerun

Do not mix old local `.foundry\results` payloads, old candidate folders, or old
azd optimizer state into a new story run. Capture old evidence separately, then
submit a fresh job and record the new IDs.

### Validate `tools.json` after materializing a candidate

PowerShell can accidentally unwrap a one-element JSON array when writing
`tools.json`. Validate before deploy:

```powershell
uv run python -c "from pathlib import Path; from castia import load_agent_config; c=load_agent_config(Path('.agent_configs')); print({'instructions': bool(c.instructions), 'tools': len(c.tool_definitions or [])})"
```

Expected `tools` is `1`.

### Prefer direct REST when `azd ai agent eval run` reuses stale eval IDs

In this session, `azd ai agent eval run` was unreliable because it reused
stale/deleted eval IDs internally. Direct REST eval creation and run submission
were used for the final production artifacts.

### Treat eval DELETE responses carefully

Eval/run DELETE endpoints can return success-shaped payloads with
`"deleted": false` while subsequent list calls show the item hidden or cleared.
Use the follow-up list result as the source of truth.

### Keep model roles separate

`gpt-6-astra` worked as the hosted-agent model and generated-rubric judge/eval
model. Use `gpt-5.5` for optimizer reflection unless the target project has
another known optimizer-supported reflection model.

### Foundry storage must be reachable

Rubric generation and eval storage need project storage reachability. The
infrastructure now enables storage `publicNetworkAccess` for this demo path. If
a target tenant has private networking or selected networks only, validate
Foundry storage access before debugging evaluator payloads.

## Presenting the evidence

Lead with the like-for-like deployed-agent comparison:

```text
Same generated rubric.
Same held-out dataset.
Same agent model.
Same generated-rubric judge/eval model.
Fresh deployed-agent responses in every repeat.
Changed assets: instructions and tool descriptions.
```

Then show:

1. `contract-policy-expert-baseline`: five clean but mediocre runs.
2. `opt_2fb58fc1723e461d9a1496907d029ac8`: optimizer process and winning
   candidate.
3. `contract-policy-expert-optimized`: five clean 24/24 runs.
