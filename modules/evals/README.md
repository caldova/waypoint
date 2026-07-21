# Caliber evaluations

Caliber is Waypoint's shared evaluation and fine-tuning support package. It
combines Foundry-native evaluation with local datasets, deterministic graders,
calibration, telemetry harvesting, and RFT/RLE planning.

The current quality target is the hosted `contract-policy-expert`. Historical
`assurance-analyst` artifacts are calibration history, not an active runtime
target.

## Monorepo inputs

| Input | Path |
| --- | --- |
| Hosted agent source and eval contracts | `modules/agents` |
| Contract, policy, invoice, and scenario corpus | `modules/corpus` |
| Shared Caliber package, datasets, and graders | `modules/evals` |
| Optimization plans and promotion artifacts | `modules/optimization` |

Caliber reads these paths and writes generated run artifacts only under ignored
output directories.

## Setup

```bash
cd modules/evals
uv sync
uv run caliber doctor
uv run caliber manifest
```

## Quality workflow

1. Build reviewed train, validation, and evaluation datasets from the corpus.
2. Generate and run the Foundry-native baseline evaluation.
3. Export Foundry output items.
4. Calibrate deterministic Caliber graders.
5. Run Foundry Agent Optimizer and review candidate changes.
6. Use Caliber RFT/RLE planning only after the quality target is stable.
7. Re-evaluate before promotion.

Example planning commands from the repository root:

```bash
uv --directory modules/evals run caliber datasets contract-policy build \
  --ledgerfield-path modules/corpus \
  --agent contract-policy-expert \
  --variants-per-scenario 8

uv --directory modules/evals run caliber optimizer plan \
  --forge-path modules/agents \
  --agent contract-policy-expert \
  --dataset modules/evals/datasets/contract-policy-expert/contract-policy-expert-eval.jsonl

uv --directory modules/evals run caliber rft plan \
  --train modules/evals/datasets/contract-policy-expert/contract-policy-expert-train.jsonl \
  --validation modules/evals/datasets/contract-policy-expert/contract-policy-expert-validation.jsonl \
  --grader modules/evals/graders/contract-policy-expert/contract_policy_evidence_grader.py \
  --base-model <candidate-model> \
  --project-endpoint <foundry-project-endpoint>
```

RFT commands validate and package inputs before any cloud submission. A plan or
package is not evidence that a model was trained or promoted.

## Layout

```text
modules/evals/
├── src/caliber/   # Python package and CLI
├── datasets/      # reviewed seed and evaluation JSONL
├── graders/       # deterministic reward and quality graders
├── docs/          # process and historical continuation notes
├── runs/          # generated eval/job artifacts, ignored
└── outputs/       # generated artifacts, ignored
```

## Guardrails

- Keep train, validation, and evaluation splits separate.
- Preserve stable source references in grounded examples.
- Keep generated output and tenant-specific IDs out of git.
- Review optimizer candidates before changing runtime agent instructions.
- Treat historical agent names and runs as provenance only.
- P2M is retired; do not reintroduce it as an evaluation path.

See
[Foundry traces and fine-tuning](../optimization/docs/FOUNDRY_TRACES_AND_FINE_TUNING.md)
and
[contract-policy-expert process](docs/CONTRACT_POLICY_EXPERT_PROCESS.md).
