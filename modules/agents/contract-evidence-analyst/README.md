# contract-evidence-analyst

Independent hosted agent for the baseline → Agent Optimizer → MAI-2 RFT pipeline. It is separate from
`contract-policy-expert` and its story assets: it has its own azd project (`azure.yaml`), its own env
(`contract-evidence-analyst`), its own benchmark and its own grader.

The agent reviews one supplier invoice line against the supplied contract/policy/record excerpts. It returns only
the evidence-only JSON defined by the task (`modules/evals/src/caliber/contract_evidence_benchmark.py`,
`TASK_CONTRACT`). It never makes or recommends a payment decision. The user message is the benchmark `task`
verbatim. Only instructions, model and reasoning effort vary between versions, and there are no tools.

| Arm | Config | Model |
|---|---|---|
| baseline | `.agent_configs/baseline` (deliberately minimal, honest starter prompt) | `gpt-6-astra` |
| optimized | `releases/optimized/baseline` (applied optimizer candidate) | `gpt-6-astra` |
| mai2-base | `releases/mai2-base/baseline` (optimized prompt) | `mai-code-2-flash-base` |
| mai2-rft | `releases/mai2-rft/baseline` (optimized prompt) | tuned MAI-2 deployment |

`agent_config.load()` fails at startup if the resolved config or model differs from what the version declares.
There are no silent fallbacks to baseline.

## Commands

```powershell
# Local tests (from this folder)
uv sync; uv run pytest -q
uv run python -m castia optimize --check          # FREE offline baseline drift check
uv run python -m castia optimize run --dry-run    # FREE payload preview

# Deploy one arm as a new pinned version (billable hosting)
./scripts/deploy_version.ps1 -Release baseline -ReasoningEffort low

# Evals (from modules/evals); records keep every attempt, graded with the frozen grader v1
uv run python -m caliber.contract_evidence_eval optimizer-data
uv run python -m caliber.contract_evidence_eval run --arm baseline --version 1 --model gpt-6-astra --split dev_eval --runs 5
uv run python -m caliber.contract_evidence_eval summarize --arm baseline --split dev_eval
```

## Data boundaries

- Benchmark: `modules/evals/datasets/contract-evidence-analyst/benchmark-v1` (train 146 / validation 33 /
  dev_eval 38 / final_test 44). Labels are rule-derived and synthetic, with `review_status: pending_human_review`.
- The optimizer sees 20 stratified train rows plus 15 validation rows (`optimizer/`).
- RFT uses train and validation.
- Model and checkpoint selection uses dev_eval.
- `final_test` is used once per arm, at the end, and never for selection.
