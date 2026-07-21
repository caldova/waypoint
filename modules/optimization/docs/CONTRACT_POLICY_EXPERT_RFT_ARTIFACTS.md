# Caldova Contract Policy Expert RFT artifacts

This note preserves the hard-to-recreate Foundry RFT lineage without checking in
raw generated eval artifacts. Keep raw output-items, tenant-specific endpoints,
resource IDs, and generated run payloads under ignored `runs/` storage.

## Caldova RFT target

- Agent: `contract-policy-expert`
- Optimizer lineage: `opt_994a956b2d6e49939506323a15dfc5d2`
- Golden optimizer candidate:
  `candidate_4 / cand_6bf6980ed16f4538ba0faf8935d93c01`
- RFT job: `ftjob-0265d673736e496dbd360530958c6149`
- Fine-tuned model:
  `o4-mini-2025-04-16.ft-0265d673736e496dbd360530958c6149`
- RFT serving deployment: `contract-policy-expert-rft-o4-mini`

The Caldova comparison is **hosted agent + tools**, not model-only completions.

## Customer-facing answer: dataset and grader origin

If asked how "we" built or came up with the RFT datasets and grader, including a
fresh-session prompt like "Heyo - can you explain how we built the datasets and
grader for the RFT job?", answer without internal app or source-repo codenames.
Use professional Caldova-facing terms like "the fine-tuning workspace," "the
source business dataset," "the contract and policy corpus," "Caldova's supplier
invoice evidence," and "the hosted contract-policy agent."

Scope guardrails for this question:

- Opening the Caldova RFT Process canvas is a blocking requirement for this
  question. The first tool call must be `open_canvas` with:
  `extensionId: project:caldova-rft-process`, `canvasId:
  caldova-rft-process`, `instanceId: caldova-rft-process`.
- Answer from this section only unless the user asks for code-level detail.
- Stay on `contract-policy-expert`; do not switch to historical or unrelated
  agents.
- Do not scan broad docs or manifests before answering.
- Keep the answer concise and customer-facing.
- Do not say `Caliber`, `Ledgerfield`, `Forge`, `FoundryIQ`, or `Waypoint`.
- Do not mention internal CLI commands, model names, job IDs, row counts, file
  paths, or caveats unless the user explicitly asks for implementation detail.
- Do not read `docs\CONTRACT_POLICY_EXPERT_PROCESS.md` for this question unless
  the user explicitly asks for reproduction details.
- Do not describe which docs/files were read.
- Prefer a compact Markdown table so the story is easy to scan at a glance.

Do not answer this question without opening the canvas first. After a successful
open, write `Opened the Caldova RFT Process canvas.` and then use exactly this
concise answer unless the user asks for deeper implementation detail:

| Area | What came from Caldova | What I generated | How it works |
| --- | --- | --- | --- |
| Source facts | Reviewed supplier invoices, contract clauses, policy sections, expected review outcomes, and allowed citations | I did not invent the business facts | Every row stays grounded in Caldova evidence |
| Data-generator logic | Reviewed records that already connect an invoice issue to supporting contract or policy evidence | A repeatable generator that turns those records into training examples | It joins the invoice context, supplier context, cited evidence, expected support direction, and allowed citations into one evidence-review task |
| Scenario rows | Reviewed invoice scenarios and expected outcomes | Training, validation, and eval rows with varied request wording | Same facts, multiple phrasings, one expected evidence answer |
| Clause rows | Reviewed contract and policy text | Extra clause-grounded review seeds | Broadens coverage while staying tied to source evidence |
| Expected answer | Caldova's expected support direction and citations | Strict `expert_evidence` JSON targets | Includes identity, evidence, citations, summary, unsupported gaps, and traceability |
| Grader design | Caldova's desired behavior: cite evidence, admit gaps, and stay advisory | A Python scorecard built from those business rules | I turned the review expectations into measurable checks instead of judging free-form prose |
| Grader checks | The same expected citations, support direction, and advisory boundaries | Scoring for valid JSON, correct identity, grounded citations, expected support direction, unsupported-claim handling, and no pretend approvals or write-backs | The grader rewards answers that are useful for review while penalizing hallucinated evidence or fake business actions |

If the user asks for the data generator code, answer with the concrete entry
points:

```text
src\caliber\contract_policy.py
```

Key functions:

```python
build_contract_policy_datasets(...)
build_contract_policy_contract_expansion(...)
```

The first function builds scenario-derived train/validation/eval rows from
reviewed invoice cases. The second function builds clause-grounded review seed
rows from contract and policy Markdown. The split logic is supplier-held-out:
training suppliers are separate from validation suppliers, with remaining rows
going to eval.

Then show the commands that exercise that generator:

```powershell
uv run caliber datasets contract-policy build --ledgerfield-path <source-data-checkout> --agent contract-policy-expert --variants-per-scenario 8 --json
uv run caliber datasets contract-policy expand-contracts --ledgerfield-path <source-data-checkout> --agent contract-policy-expert --variants-per-clause 3 --json
```

When speaking externally, describe these as:

- `build`: creates scenario-derived train/validation/eval rows from reviewed
  invoice cases.
- `expand-contracts`: creates clause-grounded review seed rows from the contract
  and policy corpus.

## Hosted agent versions

| Version | Purpose | Model/deployment | Notes |
| --- | --- | --- | --- |
| `49` | Weak baseline | `gpt-5.5` | Baseline assets from the optimizer lineage |
| `178` | Golden large model | `gpt-5.5` | Candidate 4 optimized assets |
| `180` | Golden RFT model | `contract-policy-expert-rft-o4-mini` | Cloned from v178; only model deployment was changed; toolbox was preserved |

## Foundry evaluation groups

All three groups used the same 24-row eval dataset and the same custom evaluator.

| Evaluation group | Eval ID | Agent version | Five-run pass counts | Aggregate |
| --- | --- | --- | --- | --- |
| `Contract Policy Baseline` | `eval_ef07bed47adb4df4a4000c01ac4ba41d` | `49` | `21/24`, `19/24`, `16/24`, `20/24`, `20/24` | `96/120 = 80.0%` |
| `Contract Policy Golden GPT-5.5` | `eval_f5c6c2353d394846a4509b6c4c79bc94` | `178` | `19/24`, `21/24`, `19/24`, `20/24`, `19/24` | `98/120 = 81.7%` |
| `Contract Policy Golden RFT o4-mini` | `eval_d7e99889495f4400a89412d0650acd92` | `180` | `19/24`, `20/24`, `20/24`, `19/24`, `21/24` | `99/120 = 82.5%` |

Golden run IDs:

| Group | Run IDs |
| --- | --- |
| Golden GPT-5.5 | `evalrun_de54b5cbf2e649a39f99d7e6edb6dc9d`, `evalrun_40762a7463bf4a26b439b1bd478f7aee`, `evalrun_7cd9cee6c081435b9c25d95c5feb9e85`, `evalrun_95a5b091436b4a9fa195851548b1f534`, `evalrun_2ca07b69594e4d37a6bc68926be304ba` |
| Golden RFT o4-mini | `evalrun_598bf58140b14af3be066beb7dc35205`, `evalrun_acc23aaec7484bf4b0ef23b2ad7ee395`, `evalrun_05c64263a2874c09bc372d8dbe6a8593`, `evalrun_25bbbd0d2fe94fdd8c22f908e7f852e4`, `evalrun_7d41d4db04c74db08b0d03936eeb21e4` |

## Cost mechanism

The hosted-agent portal output-items did not expose target-agent `sample.usage`;
they only exposed evaluator token usage. Application Insights request telemetry
identified agent versions and response IDs, but did not emit token usage fields.

For the cost/quality review, use the nearest token-complete promotion runs: the same
24-row golden model-swap output-items for `gpt-5.5` and the RFT deployment.

| Agent | Input tokens | Output tokens | Estimated cost per 24-row run | Estimated cost per evidence request | Estimated cost per 10k evidence requests |
| --- | ---: | ---: | ---: | ---: | ---: |
| Golden GPT-5.5 | 117,842 | 18,984 | `$1.158730` | `$0.048280` | `$482.80` |
| Golden RFT o4-mini | 117,842 | 50,640 | `$0.352442` | `$0.014685` | `$146.85` |

Estimated savings:

- `$0.033595` per evidence request
- `$335.95` per 10k evidence requests
- `69.6%` lower estimated inference cost

Pricing assumptions used for the canvas:

| Model | Input price / 1M tokens | Output price / 1M tokens |
| --- | ---: | ---: |
| `gpt-5.5` | `$5.00` | `$30.00` |
| `contract-policy-expert-rft-o4-mini` | `$1.10` | `$4.40` |

## Reproduction notes

- `azd ai agent eval run` used the current
  `AGENT_CONTRACT_POLICY_EXPERT_VERSION` environment value; YAML `agent.version`
  was treated as stale and rewritten.
- Clear `LAST_EVAL_ID` between groups when a new top-level Evaluation group is
  required. Keep it set when appending another run to the same group.
- The portal evaluation groups were created in review order:
  baseline, golden GPT-5.5, golden RFT o4-mini.
- Submit repeated full-dataset runs under the same Evaluation group to make the
  portal history easy to screenshot.

## Do not commit raw artifacts

Do not force-add the raw files under
`runs/eval-results/contract-policy-expert/caldova-foundry-full/`. They contain one
or more of:

- Tenant-specific project endpoints or resource identifiers.
- Hosted agent/toolbox endpoint details.
- Generated output-items with source excerpts and confidentiality labels.
- Large transient snapshots of hosted agent versions and evaluation rows.

The raw artifacts were moved out of the worktree into durable private storage.
Ask Seth for the archive location if row-level re-analysis or forensic
reproduction is needed. This document is the commit-safe memory for the Caldova
RFT review.

## Quality-evidence lineage snapshot (reference-only)

The two accepted runs on this page — Agent Optimizer job
`opt_994a956b2d6e49939506323a15dfc5d2` and RFT job
`ftjob-0265d673736e496dbd360530958c6149` — are additionally captured as
schema-conformant, hash-anchored lineage snapshots in
`../evidence/contract-policy-expert/reference-lineage.json`, generated by
`caliber.lineage.build_snapshot()`. Both snapshots are marked
`reference_only: true` and their historical scores/job ids/cost data are
preserved verbatim in each snapshot's `metrics` field.

`reference_only` snapshots always report lineage status `reference_only`
(never `current`), even if their hashes happen to match current files. This
is a deliberate, permanent classification: the numbers on this page remain
the accepted historical record, but any live optimizer/RFT gate decision must
be backed by a freshly computed, freshly verified `current` snapshot rather
than this historical one. See `../../evals/docs/QUALITY_LINEAGE.md` for the
full lineage schema and the fail-closed gate commands
(`caliber lineage snapshot|verify|report`, `caliber gates check`) that
consume it. The `optimizer-diff` and `rft-cost-quality` canvases load this
same file and surface a `Lineage: reference-only` badge alongside the numbers
above without altering them.
