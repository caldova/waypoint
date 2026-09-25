# contract-policy-expert

FoundryIQ-only contract and policy expert for Teams-facing Q&A and optimization.
It answers from the `contracts-kb` evidence plane through
`knowledge_base_retrieve` and remains strictly read-only.

This agent is intentionally separate from the full `contract-agent`: its eval and
fine-tuning target is grounded answer quality, not workflow orchestration or
writeback behavior.

The default `.agent_configs\baseline` is the early-prototype baseline used for
the Foundry Agent Optimizer demo. It is intentionally sparse but still functional
so the optimizer can improve real agent assets: instructions and tool
descriptions. The reference optimized candidate from the production run is
preserved in `.agent_configs\optimized` so the improved CPE can be replayed or
promoted without rerunning the optimizer.

`eval.yaml` points at the shared `modules/evals/datasets/contract-policy-expert`
splits and is refreshed by `azd ai agent eval generate` so the workstream uses a
Foundry-generated rubric evaluator as the headline scorecard.

## Local development

```powershell
cd modules\agents\contract-policy-expert
copy .env.example .env
uv sync
uv run python main.py
```

Set the Foundry project/model values and a FoundryIQ toolbox endpoint before
testing live retrieval.

## Foundry Optimizer demo workflow

For a complete production replay checklist, use
`FOUNDRY_OPTIMIZER_REPLAY.md`.

Run these commands from this folder after selecting the correct azd environment
and confirming the deployed CPE service is reachable.

```powershell
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"

azd ai agent eval generate --reset-defaults `
  --dataset ../../evals/datasets/contract-policy-expert/contract-policy-expert-train.jsonl `
  --gen-instruction-file ./eval-generation-instructions.md `
  --eval-model <eval-model-deployment> `
  --name contract-policy-expert-generated-rubric

azd ai agent optimize --optimize-model <optimizer-model-deployment>
```

Or use the checked workflow script:

```powershell
.\scripts\run-foundry-optimizer-demo.ps1 `
  -ProjectEndpoint <foundry-project-endpoint> `
  -EvalModel <eval-model-deployment> `
  -OptimizerModel <optimizer-model-deployment>
```

Before applying a candidate, review the generated rubric and the optimizer diff.
The demo score should come from the generated rubric evaluator. The deterministic
CPE grader in `modules\evals\graders\contract-policy-expert` is a secondary
sanity check, not the primary optimizer evidence.

If `azd ai agent optimize` reports `instruction is required for optimization`
even though `.agent_configs\baseline\metadata.yaml` and `eval.yaml` point at the
baseline instructions, use the SDK fallback:

```powershell
uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint <foundry-project-endpoint> `
  --eval-model gpt-6-astra `
  --optimization-model gpt-5.5 `
  --max-candidates 15
```

The SDK path keeps `gpt-6-astra` as both the hosted agent model under
optimization and the generated-rubric judge/eval model. `gpt-5.5` is only the
optimizer reflection model because the optimizer service rejected
`gpt-6-astra` for `optimization_model` in the reference run. Use these helper
commands to recover and inspect jobs:

```powershell
uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint <foundry-project-endpoint> `
  --list

uv run python .\scripts\submit-foundry-optimizer-sdk.py `
  --project-endpoint <foundry-project-endpoint> `
  --status-job-id <optimizer-job-id>
```

The production optimizer story run in the Caldova project was
`opt_2fb58fc1723e461d9a1496907d029ac8`. It completed 15 candidates and selected
`candidate_14` (`cand_opt_2fb58fc1723e461d9a1496907d029ac8_0014`), improving the
training score from `0.455684` to `0.8000013333333332` by mutating the system
prompt and tool descriptions.

The stage evidence is the like-for-like deployed-agent eval comparison:

| Run | Eval run | Agent version | Generated-rubric result | Avg score |
| --- | --- | --- | --- | --- |
| Baseline | Five runs in `contract-policy-expert-baseline` | `6` | 16/24, 15/24, 11/24, 14/24, 18/24; 0 errored | varies |
| Optimized | Five runs in `contract-policy-expert-optimized` | `7` | 24/24 on all five runs; 0 errored | maxed |

Both eval groups use the same held-out dataset
`contract-policy-expert-test-foundry-eval` version `2.0` and generated rubric
`contract-policy-expert-generated-rubric` version `13`.

The lower-level REST fallback is documented in
`modules\evals\docs\CONTRACT_POLICY_EXPERT_PROCESS.md`; it posts the optimizer
request to `<project-endpoint>/agent_optimization_jobs?api-version=v1` with
`Foundry-Features: AgentsOptimization=V2Preview`.
