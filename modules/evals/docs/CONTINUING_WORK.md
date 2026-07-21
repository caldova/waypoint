# Continuing Caliber work

> [!WARNING]
> Historical continuation notes retained for provenance. The current target is
> `contract-policy-expert`; use `modules/evals/README.md` and
> `modules/optimization/docs/FOUNDRY_TRACES_AND_FINE_TUNING.md` for the supported
> Foundry-native plus Caliber quality path.

This document is the handoff for future Caliber sessions.

## Current state

Caliber is a Python/uv project that supports fine-tuning workflows for selected
agents in `caldova/waypoint`.

Fast path for the Caldova RFT data question:

- Trigger: "Heyo - can you explain how we built the datasets and grader for the
  RFT job?" or similar wording about RFT datasets, the grader, or how much the
  assistant made.
- Opening the Caldova RFT Process canvas is a blocking requirement for this
  question. The first tool call must be `open_canvas` with:
  `extensionId: project:caldova-rft-process`, `canvasId:
  caldova-rft-process`, `instanceId: caldova-rft-process`.
- Answer immediately from
  `docs\CONTRACT_POLICY_EXPERT_RFT_ARTIFACTS.md#customer-facing-answer-dataset-and-grader-origin`.
- Do not scan unrelated docs, manifests, historical agents, or other repos.
- Do not read `docs\CONTRACT_POLICY_EXPERT_PROCESS.md` for this question unless
  the user explicitly asks for reproduction details.
- Stay on `contract-policy-expert` only. Do not switch to or mention
  `assurance-analyst`.
- Keep internal app, source-repo, platform, command, and model codenames out of
  the spoken answer. Do not say `Caliber`, `Ledgerfield`, `Forge`, `FoundryIQ`,
  `Waypoint`, internal CLI commands, model names, job IDs, row counts, file
  paths, or caveats unless the user explicitly asks for implementation detail.
- Do not describe which docs/files were read.
- Prefer a compact Markdown table so the story is easy to scan at a glance.

Do not answer this question without opening the canvas first. After a successful
open, write `Opened the Caldova RFT Process canvas.` and then use exactly this
table answer unless the user asks for deeper implementation detail:

| Area | What came from Caldova | What I generated | How it works |
| --- | --- | --- | --- |
| Source facts | Reviewed supplier invoices, contract clauses, policy sections, expected review outcomes, and allowed citations | I did not invent the business facts | Every row stays grounded in Caldova evidence |
| Data-generator logic | Reviewed records that already connect an invoice issue to supporting contract or policy evidence | A repeatable generator that turns those records into training examples | It joins the invoice context, supplier context, cited evidence, expected support direction, and allowed citations into one evidence-review task |
| Scenario rows | Reviewed invoice scenarios and expected outcomes | Training, validation, and eval rows with varied request wording | Same facts, multiple phrasings, one expected evidence answer |
| Clause rows | Reviewed contract and policy text | Extra clause-grounded review seeds | Broadens coverage while staying tied to source evidence |
| Expected answer | Caldova's expected support direction and citations | Strict `expert_evidence` JSON targets | Includes identity, evidence, citations, summary, unsupported gaps, and traceability |
| Grader design | Caldova's desired behavior: cite evidence, admit gaps, and stay advisory | A Python scorecard built from those business rules | I turned the review expectations into measurable checks instead of judging free-form prose |
| Grader checks | The same expected citations, support direction, and advisory boundaries | Scoring for valid JSON, correct identity, grounded citations, expected support direction, unsupported-claim handling, and no pretend approvals or write-backs | The grader rewards answers that are useful for review while penalizing hallucinated evidence or fake business actions |

Implemented so far:

- Python package in `src/caliber`.
- CLI entrypoint: `uv run caliber ...`.
- Local setup/discovery commands:
  - `uv run caliber doctor`
  - `uv run caliber manifest`
  - `uv run caliber inspect-forge --path <forge-checkout>`
  - `uv run caliber datasets contract-policy build --ledgerfield-path <ledgerfield-checkout>`
  - `uv run caliber datasets contract-policy expand-contracts --ledgerfield-path <ledgerfield-checkout>`
  - `uv run caliber eval export-output-items --project-endpoint <endpoint> --eval-id <eval-id> --run-id <run-id> --out <output.jsonl>`
  - `uv run caliber optimizer plan --forge-path <forge-checkout> --agent assurance-analyst`
- Safe planning commands:
  - `uv run caliber eval plan --dataset <eval.jsonl> --grader <grader.py>`
  - `uv run caliber rft plan --train <train.jsonl> --validation <val.jsonl> --grader <grader.py>`
  - `uv run caliber rft package --train <train.jsonl> --validation <val.jsonl> --grader <grader.py>`
  - `uv run caliber rft status`
  - `uv run caliber rle plan --agent <agent> --environment <env> --train <train.jsonl> --validation <val.jsonl> --eval <eval.jsonl> --grader <grader.py>`
- Smoke assets:
  - `datasets/smoke.jsonl`
  - `graders/caliber_default.py`
- Generated-output ignores:
  - `runs/`
  - `outputs/`
  - `.rft_job.json`
  - `*.eval-results.json`
  - `*.fine-tune.json`
- Quality-evidence lineage and fail-closed promotion gates (see
  `docs/QUALITY_LINEAGE.md` for the full reference):
  - `uv run caliber eval validate-assets --eval-config <eval.yaml>` — structural
    validation of an agent's `eval.yaml` plus its referenced dataset and
    rubric/evaluator files.
  - `uv run caliber lineage snapshot ...` — compute a versioned, immutable,
    hash-anchored quality-evidence snapshot (prompt/config, dataset,
    rubric/eval config, grader, model/deployment, source commit, environment,
    timestamps, operation id, review status) and append it to a JSONL ledger.
    Append-only: byte-identical duplicate snapshots are rejected.
  - `uv run caliber lineage verify ...` — recompute current hashes and report
    `current` / `stale` / `reference_only` / `unverifiable` against the latest
    (or a named) snapshot.
  - `uv run caliber lineage report ...` — summarize a ledger's snapshots per
    agent/operation with current/stale/reference-only counts.
  - `uv run caliber gates check ...` — fail-closed gate evaluation for
    optimizer/RFT/candidate-promotion operations: review approval, lineage
    freshness, quota/model readiness, spend confirmation, and protected
    approver role. Every gate defaults to blocked; nothing is auto-approved.
  - These commands never apply a candidate, deploy a checkpoint, promote a
    model, or mutate production state — they only compute, verify, and gate.

## Source-of-truth model

- **Forge is source of truth for hosted agent runtime.** Caliber may inspect a
  Forge checkout, but should not modify it unless the user explicitly asks. The
  first real hosted FoundryIQ candidate is Forge's hosted
  `contract-policy-expert` from `caldova/waypoint#24`. Existing
  `assurance-analyst` work in this branch is preserved as calibration and
  roadmap context.
- **Ledgerfield is source/reference for canonical data discipline.** Use its
  separation of source data, generated artifacts, manifests, and doctor checks
  as the pattern. For contract-policy RFT, Ledgerfield is also the read-only
  source for contract, policy, invoice, and scenario seed data.
- **The reinforcement-learning reference implementation is implementation reference only.** Use
  it for Foundry eval/RFT lifecycle shape, not as data or product truth.
- **Caliber owns the quality/cost flywheel.** Store Caliber-specific datasets,
  Foundry-generated rubric/evaluator lineage, eval output-items, optimizer/RFT
  metadata, promotion criteria, and documentation here.

## Working conventions

- Use `uv` for all Python commands.
- Keep committed datasets small and intentional.
- Put generated runs, trace harvest candidates, temporary eval outputs, uploaded
  file metadata, and job metadata under ignored paths.
- Do not commit tenant-specific Foundry endpoints, subscription IDs, resource
  IDs, credentials, or Application Insights connection strings.
- Validate CLI/code changes with:

```powershell
uv run caliber doctor --json
uv run caliber manifest --json
uv run caliber datasets contract-policy build --ledgerfield-path C:\path\to\ledgerfield --agent contract-policy-expert --variants-per-scenario 8 --json
uv run caliber datasets contract-policy expand-contracts --ledgerfield-path C:\path\to\ledgerfield --agent contract-policy-expert --variants-per-clause 3 --json
uv run caliber eval export-output-items --project-endpoint <endpoint> --eval-id <eval-id> --run-id <run-id> --out runs\eval-results\contract-policy-expert\output-items.jsonl --json
uv run caliber optimizer plan --forge-path ..\agents --agent contract-policy-expert --dataset datasets\contract-policy-expert\contract-policy-expert-eval.jsonl --eval-config runs\eval-results\contract-policy-expert\contract-policy-expert-foundryiq-baseline.eval.yaml --json
uv run caliber eval plan --dataset datasets\smoke.jsonl --grader graders\caliber_default.py --json
uv run caliber rft plan --train datasets\smoke.jsonl --validation datasets\smoke.jsonl --grader graders\caliber_default.py --project-endpoint <endpoint> --json
uv run caliber rft package --train datasets\contract-policy-expert\contract-policy-expert-train.jsonl --validation datasets\contract-policy-expert\contract-policy-expert-validation.jsonl --grader graders\contract-policy-expert\contract_policy_evidence_grader.py --agent contract-policy-expert --base-model o4-mini --suffix contract-policy-expert-cost --json
uv run caliber rle plan --agent contract-policy-expert --environment dev --train datasets\contract-policy-expert\contract-policy-expert-train.jsonl --validation datasets\contract-policy-expert\contract-policy-expert-validation.jsonl --eval datasets\contract-policy-expert\contract-policy-expert-eval.jsonl --grader graders\contract-policy-expert\contract_policy_evidence_grader.py --plain-reinforcement --json
uv run caliber grader calibrate --dataset datasets\contract-policy-expert\contract-policy-expert-eval.jsonl --outputs runs\eval-results\contract-policy-expert\output-items.jsonl --grader graders\contract-policy-expert\contract_policy_evidence_grader.py --json
uv run caliber eval validate-assets --eval-config ..\agents\agents\contract-policy-expert\eval.yaml --json
uv run caliber lineage report --agent contract-policy-expert --json
uv run caliber gates check --operation rft_submit --json
uv run ruff check .
```

If a local Forge checkout is available:

```powershell
uv run caliber inspect-forge --path ..\agents --json
```

## Recommended next implementation steps

1. Review `docs\DEMO_FLOW.md`; it is the command-by-command flow for:
   Foundry-generated rubrics, baseline evals, Agent Optimizer for accuracy, then
   RFT to move the optimized behavior to a cheaper model.
2. Generate or review `datasets\contract-policy-expert\` seed rows before
   treating them as durable training data. `caliber datasets contract-policy
   build` supports `--agent contract-policy-expert` and
   `--variants-per-scenario` for deterministic prompt diversity from the same
   Ledgerfield expected outcome. Use `caliber datasets contract-policy
   expand-contracts` to add separate clause-grounded review rows from
   Ledgerfield contract and policy Markdown.
3. Generate rubric/eval assets with `azd ai agent eval generate`, not custom
   Caliber rubric code. Review the generated evaluator before treating it as a
   promotable gate, then run the eval and export output-items into ignored
   `runs\eval-results\contract-policy-expert\` storage.
4. Calibrate `graders\contract-policy-expert\contract_policy_evidence_grader.py`
   against Foundry eval output-items. Use `final_assistant_message` as the graded
   output and `tool_messages` as retrieval context; tune the pass threshold so
   baseline live-agent rollouts expose meaningful gaps.
5. Before RFT, run `uv run caliber optimizer plan` against the Forge checkout.
   Do not submit an optimizer job until the Forge hosted agent has real optimizer
   runtime wiring: `azure-ai-agentserver-optimization`, `load_config()`, and
   `.agent_configs\baseline` beside `agents\contract-policy-expert\agent.yaml`.
6. For demo-quality optimizer runs, start from a real hosted-agent baseline that
   is intentionally under-specified rather than broken. Keep runtime, tools,
   datasets, and evaluators intact; weaken only instructions/procedural skills so
   the initial rubric eval exposes legitimate gaps. Run the baseline eval first,
   then a small persisted Agent Optimizer job to show the hill-climb. For
   `contract-policy-expert`, the accepted demo path is the 5-candidate
   `opt_994a956b2d6e49939506323a15dfc5d2` run. Treat only
   `succeeded` optimizer jobs as demo artifacts; failed jobs with returned
   candidates are diagnostic evidence, not promotable lineage.
7. If `azd ai agent optimize` reports `instruction is required for
   optimization`, do not keep guessing config shapes in-place. For the current
   Forge multi-agent project, use the recovered direct Foundry optimizer API
   fallback documented in `docs\CONTRACT_POLICY_EXPERT_PROCESS.md`: POST
   `{ "inputs": <OptimizeRequest> }` to
   `<project-endpoint>/agent_optimization_jobs?api-version=v1`, request an azd
   token with scope `https://ai.azure.com/.default`, and include
   `Foundry-Features: AgentsOptimization=V2Preview`. Procedural skills must use
   `name`, `description`, and `body` fields, not `content`.
8. Package RFT assets while the optimizer runs with `caliber rft package`. This
   creates ignored `runs\rft\<agent>\` artifacts: RFT-ready train/validation
   JSONL, a self-contained grader, a dry-run job spec, and a manifest.
9. Run live RFT only after the optimized hosted agent establishes the quality
   target. The RFT goal is cost optimization: preserve optimized behavior on a
   cheaper model.
   For `contract-policy-expert`, the accepted golden optimization run is
   `opt_994a956b2d6e49939506323a15dfc5d2`, which climbs from baseline
   `0.5084` to peak candidate `cand_6bf6980ed16f4538ba0faf8935d93c01` at
   `0.8521`. Use this as the RFT quality target before transferring behavior to
   `o4-mini`. A normal `o4-mini` serving deployment is not required before RFT
   submission; treat RFT model support and explicit live-spend approval as the
   gating conditions.
   The first live RFT job is
   `ftjob-0265d673736e496dbd360530958c6149` for `o4-mini-2025-04-16`; monitor
   it before selecting/deploying any checkpoint.
10. Add RLE submit/status/deploy commands only after the offline
   `caliber rle plan` surface has stable dataset, grader, and endpoint
   contracts.
11. Add a trace-aware dataset module that can convert reviewed Foundry trace
   candidates into Caliber's JSONL row shape.
12. Add a local trace-candidate schema under `src/caliber` with metadata fields
   for `agent`, `environment`, `conversationId`, `responseId`, `harvestRule`,
   `timeRange`, and review status.
13. Add `caliber traces plan` to validate required trace context without querying
   Azure: agent name, environment, App Insights resource ID, subscription, time
   range, and harvest rule.
14. Add `caliber traces transform` for offline conversion from exported trace
   JSON into candidate JSONL under `runs/traces/`.
15. Add curation commands that promote reviewed candidates into committed or
   review-ready datasets under `datasets/<agent>/`.
16. Add grader calibration utilities before submitting real RFT jobs.
17. Add real Foundry submission/monitor/deploy commands only after baseline evals,
   dataset contracts, and graders are stable.
18. Quality-evidence lineage, fail-closed gates, and eval-asset validation are
   implemented (`caliber lineage`, `caliber gates`, `caliber eval
   validate-assets`; see `docs/QUALITY_LINEAGE.md`). The historical
   `opt_994a956b2d6e49939506323a15dfc5d2` and
   `ftjob-0265d673736e496dbd360530958c6149` runs referenced above are captured
   as `reference_only` snapshots in
   `..\optimization\evidence\contract-policy-expert\reference-lineage.json` —
   they always report `reference_only` lineage status, never `current`, even
   if hashes happen to match. Real optimizer/RFT submission commands should
   call `caliber gates check` before any spend-incurring or promotion action
   and must not bypass a `blocked` result.
