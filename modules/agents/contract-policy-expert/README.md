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
descriptions. The stronger pre-demo configuration is preserved in
`.agent_configs\reference-good` for rollback and comparison.
The reference optimized candidate is preserved in
`.agent_configs\optimized-candidate-3` so the improved CPE can be replayed or
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
  --max-candidates 4 `
  --max-items 15
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

The first successful generated-rubric optimizer run in the Caldova project was
`opt_58bea824c02e420992e28cee71f281b9`. It completed four candidates and raised
the generated-rubric average score from `0.3779` for the weak baseline to
`0.8203` for `candidate_3`
(`cand_opt_58bea824c02e420992e28cee71f281b9_0003`), mutating the system prompt
and tool descriptions.

The same optimizer job also produced explicit generated-rubric eval runs that
can be used as the demo's before/after evidence without applying or deploying
the candidate first:

| Run | Eval run | Agent version | Generated-rubric result | Avg score |
| --- | --- | --- | --- | --- |
| Baseline | `evalrun_c9625d5a3ade48bea4cfefd2993bac22` | `12` | 2 passed / 13 failed / 0 errored / 15 total | `0.3779` |
| Candidate 3 | `evalrun_d2a14edd2f4046678a134d6918c0f997` | `draft-1790271309857` | 15 passed / 0 failed / 0 errored / 15 total | `0.8203` |

Both runs use eval definition `eval_20b2995b658a4506919b39aa6a4ad300` and the
same generated rubric, `contract-policy-expert-generated-rubric`.

The lower-level REST fallback is documented in
`modules\evals\docs\CONTRACT_POLICY_EXPERT_PROCESS.md`; it posts the optimizer
request to `<project-endpoint>/agent_optimization_jobs?api-version=v1` with
`Foundry-Features: AgentsOptimization=V2Preview`.
