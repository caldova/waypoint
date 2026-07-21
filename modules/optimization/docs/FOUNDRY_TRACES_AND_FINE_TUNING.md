# Foundry traces and fine-tuning roadmap

> [!IMPORTANT]
> The current target is `contract-policy-expert`, using Foundry-native
> evaluations and Agent Optimizer with Caliber datasets, graders, calibration,
> and RFT/RLE planning. References to `assurance-analyst` and
> `foundryiq-expert` below are retained historical run and artifact names, not
> active runtime agents.

Caliber should become the flywheel between production Forge agents, Foundry
traces, curated eval datasets, graders, and fine-tuned model deployments.

## Target flywheel

```text
Forge hosted FoundryIQ agent
  -> Foundry-generated rubric/eval assets
  -> baseline eval and Caliber output-item export
  -> Foundry Agent Optimizer for hosted-agent accuracy
  -> reviewed optimizer candidate applied in Forge after approval
  -> Foundry/App Insights traces and Forge eval assets
  -> trace harvest candidates and golden-case coverage
  -> human curation into Caliber eval datasets
  -> baseline evaluation and grader calibration
  -> Foundry RFT job to preserve optimized behavior on a cheaper model
  -> checkpoint/model deployment cost/quality decision
  -> before/after evaluation
  -> Forge agent update when approved
```

Caliber should treat agent improvement as a sequenced quality/cost loop:

1. **Foundry rubric generation and baseline eval first.** Use
   `azd ai agent eval generate` to let Foundry generate rubric/evaluator assets
   for Forge's hosted `contract-policy-expert`; review those assets before
   treating them as durable gates.
2. **Agent Optimizer for accuracy.** Use Foundry Agent Optimizer to improve the
   hosted agent's instructions and non-model assets, then apply the selected
   candidate locally in Forge only after review.
3. **RFT for cost.** Fine-tune only after optimizer establishes the quality
   target. The RFT goal is to preserve optimized `contract-policy-expert`
   behavior on a cheaper model, not to bypass optimizer.

## Trace harvesting rules

Use the Microsoft Foundry trace and eval-datasets workflows as the operating
model.

Important rules to preserve in Caliber:

- Always resolve agent name, environment, project endpoint, subscription, and
  App Insights resource before querying traces.
- Always show KQL to the user before running it.
- Always scope trace queries to a time range. Default to the last 7 days for
  harvesting.
- For hosted agents, start from `requests` rows scoped by Foundry agent name,
  then join spans by operation ID or parent ID.
- Evaluation results live in `customEvents` with
  `name == "gen_ai.evaluation.result"`.
- Trace spans live in `dependencies`.
- Join eval results and spans with `customDimensions["gen_ai.response.id"]`.
- Do not use `parse_json(customDimensions)` in App Insights KQL;
  `customDimensions` is already dynamic.
- Never auto-promote harvested traces into a dataset. Human review is required.

### Querying a hosted-agent trace by trace ID

When the user gives a concrete trace/request ID, first confirm whether the
telemetry is in the Log Analytics workspace that backs the Foundry/Application
Insights setup. Do not assume an `az monitor app-insights query` against the
component will see every workspace-backed `App*` table row.

Use the workspace query path when the workspace is known:

```powershell
az monitor log-analytics workspace show `
  --resource-group <resource-group> `
  --workspace-name <log-analytics-workspace-name> `
  --query customerId `
  --output tsv

az monitor log-analytics query `
  --workspace <workspace-customer-id> `
  --analytics-query "<KQL below>" `
  --output json
```

Use this KQL shape for a request/trace ID lookup. If PowerShell or Azure CLI
quoting mangles the query, avoid `let` and inline the trace ID as a single-
quoted string, or send the same query through the Log Analytics REST API.

```kusto
let traceId = "<trace-id>";
union isfuzzy=true withsource=SourceTable
    AppRequests,
    AppDependencies,
    AppTraces,
    AppExceptions,
    AppEvents,
    AppGenAIContent
| where TimeGenerated > ago(30d)
| where OperationId == traceId
    or ParentId == traceId
    or Id == traceId
    or tostring(Properties) has traceId
    or tostring(Message) has traceId
    or tostring(Name) has traceId
| project
    TimeGenerated,
    SourceTable,
    AppRoleName,
    OperationId,
    ParentId,
    Id,
    Name,
    Success,
    ResultCode,
    DurationMs,
    Target,
    Data,
    Message,
    Properties
| order by TimeGenerated asc
```

PowerShell REST fallback that preserves the KQL body exactly:

```powershell
$workspace = "<workspace-customer-id>"
$traceId = "<trace-id>"
$kql = @"
union isfuzzy=true withsource=SourceTable AppRequests, AppDependencies, AppTraces, AppExceptions, AppEvents, AppGenAIContent
| where TimeGenerated > ago(30d)
| where OperationId == '$traceId'
    or ParentId == '$traceId'
    or Id == '$traceId'
    or tostring(Properties) has '$traceId'
    or tostring(Message) has '$traceId'
    or tostring(Name) has '$traceId'
| project TimeGenerated, SourceTable, AppRoleName, OperationId, ParentId, Id, Name, Success, ResultCode, DurationMs, Target, Data, Message, Properties
| order by TimeGenerated asc
"@
$token = az account get-access-token --resource https://api.loganalytics.io --query accessToken -o tsv
$body = @{ query = $kql } | ConvertTo-Json
Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.loganalytics.io/v1/workspaces/$workspace/query" `
  -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
  -Body $body
```

Read the timeline from the inbound `AppRequests`/`AppTraces` rows outward:
identify the hosted-agent name and version, then inspect tool/dependency spans
for inner failures. A trace can have an overall successful response while a
nested dependency, such as an invoice lookup or retrieval call, returns an
authorization or data-access failure. In that case, report both facts clearly:
the agent invocation succeeded, but the evidence available to the agent may
have been incomplete.

## Caliber storage model

Caliber is not itself a Forge hosted-agent root, so avoid writing `.foundry/`
metadata into Forge unless the user explicitly asks.

The current first Forge hosted FoundryIQ candidate is tracked in `uv run caliber
manifest --json`:

- Agent: `contract-policy-expert`
- Current Forge implementation: hosted `agents/contract-policy-expert` from
  `caldova/waypoint#24`.
- Current deployment shape: azd `azure.ai.agent` hosted service using the
  Responses protocol. `assurance-orchestrator` calls it through
  `FOUNDRYIQ_EXPERT_ENDPOINT`.
- Caliber owns datasets, Foundry-generated rubric/evaluator lineage, eval run
  analysis, optimizer/RFT candidate outputs, and promotion metadata. Forge owns
  runtime source and consumes only promoted/canonical gates.
- Existing `assurance-analyst` artifacts in this branch are preserved as
  calibration and roadmap context.
- Current retrieval-backed eval reference: Forge merge `57c5b4e` and adaptation
  `cd94d6b`, lineage `contract-policy-expert:12`, suite
  `contract-policy-evidence-compliance-live`, dataset
  `contract-policy-evidence-compliance` version `6.0`, evaluator version `6`.
  The per-sample output/tool traces available today are from the predecessor
  `foundryiq-expert` hosted run, not branch-native `assurance-analyst`.
  Branch-native outputs should be generated after prompt-agent deploy, eval
  update, and eval rerun.
  For calibration, export eval output-items because summary JSON only contains
  metadata/counts; output-items contain `sample.input`, `sample.output`,
  `results`, and usage metadata.
- Agent source: `agents/contract-policy-expert/`
- Instructions: `agents/contract-policy-expert/prompt.md`
- Local eval config generated by Foundry/azd into ignored Caliber `runs\`
  storage before promotion.
- Golden cases:
  `agents/assurance-analyst/datasets/contract-policy-evidence-compliance/contract-policy-evidence-compliance_dg.jsonl`
- Pacioli lane compatibility: `foundryiq`
- Grounding target: `knowledge_base___knowledge_base_retrieve`
  through the `kb-mcp-connection` contract/policy knowledge-base MCP connection.
  Plain RFT rows should embed retrieved evidence snippets; tool-augmented rows
  should preserve the retrieval call trace once that route is available.
- Selection reason: best current candidate for improving grounded
  contract/policy reasoning over retrieved KB results, rather than only prompt
  formatting.

Do not run live optimizer or fine-tuning commands until the generated datasets,
rubrics, grader behavior, and baseline evaluations are reviewed. Caliber should
keep generated artifacts out of Forge unless the user explicitly asks to apply a
reviewed change there.

### Foundry-native eval exercise

Forge successfully exercised the Foundry-native eval path for the lineage
`contract-policy-expert` target on branch `<agent-fleet-branch>` at
commit `0bbc6df`. This used the Foundry-native evaluation path. Caliber treats
that run as calibration lineage; new branch-native runs should target
`assurance-analyst`.

Context:

- Project endpoint: provide via `AZURE_AI_PROJECT_ENDPOINT` or
  `--project-endpoint`; do not commit tenant-specific endpoint values.
- Agent target used in the lineage exercise: `contract-policy-expert`
- Eval/generation model: `gpt-5.5`
- Source seed: `evals\cases\contract-policy-expert_golden.jsonl`
- Dataset caveat: Forge golden rows use `prompt`, while `azd ai agent eval`
  generated completions with `{{item.query}}`; the exercise used a scratch
  query-shaped JSONL dataset with the same four golden cases.

Command shape that worked:

```powershell
$env:AZURE_AI_PROJECT_ENDPOINT = "<foundry-project-endpoint>"
azd ai agent eval init `
  --agent contract-policy-expert `
  --project-endpoint $env:AZURE_AI_PROJECT_ENDPOINT `
  --dataset <query-shaped-golden-jsonl> `
  --gen-instruction-file agents\contract-policy-expert\prompt.md `
  --eval-model gpt-5.5 `
  --max-samples 15 `
  --name contract-policy-expert-foundry-smoke `
  --out-file <scratch-or-review-path>\contract-policy-foundry-eval.yaml `
  --no-prompt `
  --output json
```

Generated local review artifacts in the Forge worktree:

- `.agent_configs\baseline\metadata.yaml`
- `.agent_configs\baseline\instructions.md`
- `evaluators\contract-policy-expert-foundry-smoke\rubric_dimensions.json`

Generated rubric dimensions:

| Dimension | Weight |
| --- | ---: |
| `grounded_claim_fidelity` | 10 |
| `source_ref_specificity` | 6 |
| `retrieval_tool_gating` | 6 |
| `identifier_complete_retrieval_query` | 4 |
| `json_evidence_contract_compliance` | 5 |
| `role_boundary_and_plane_isolation` | 5 |
| `conservative_uncertainty_handling` | 4 |
| `general_quality` | 5 |

Eval run command that worked:

```powershell
azd ai agent eval run `
  --config <scratch-or-review-path>\contract-policy-foundry-eval.yaml `
  --name contract-policy-expert-foundry-smoke-run `
  --no-wait `
  --no-prompt `
  --output json
```

Eval result:

- Eval ID: `eval_5c1129b324c1438393fad9a498dc8700`
- Run ID: `evalrun_6e424b69d02448f9bbea8ea544857331`
- Status: `completed`
- Counts: 4 total, 4 passed, 0 failed, 0 errored, 0 skipped
- Report URL omitted because it contains tenant-specific resource identifiers.

Optimizer command shape attempted after the successful eval:

```powershell
azd ai agent optimize `
  --agent contract-policy-expert `
  --project-endpoint $env:AZURE_AI_PROJECT_ENDPOINT `
  --config <scratch-or-review-path>\contract-policy-foundry-eval.yaml `
  --eval-model gpt-5.5 `
  --target instruction `
  --no-wait `
  --no-prompt `
  --output json
```

The optimizer submit failed before producing an operation ID:

```text
HTTP 400: options.optimizationModel is required
```

Forge tried adding `options.optimization_model: gpt-5.5`, camelCase
`optimizationModel`, and a temporary repo-root `eval.yaml`; azd
`v0.1.34-preview` still submitted without `options.optimizationModel`. No
candidate IDs were produced, and nothing was applied or deployed.

The route was retried after upgrading the Foundry azd extension from
`azure.ai.agents 0.1.34-preview` to `0.1.41-preview` and upgrading azd from
`1.25.6` to `1.26.0`. The newer CLI exposes the documented
`--optimize-model` flag and accepts generated eval assets, but still refuses to
submit because `assurance-analyst` is not optimizer-ready in source:

```text
ERROR: instruction is required for optimization.

Provide it via one of:
  1. Set agent.config in eval.yaml to point to a config dir with metadata.yaml
  2. Set instruction in eval.yaml (agent section): inline string or file reference
  3. Run without --no-prompt to enter it interactively
```

Docs checked:

- Agent Optimizer overview: instruction tuning activates when the hosted agent
  has an `instructions.md` file in the baseline config directory, and the
  optimizer requires `options.optimization_model` / `--optimize-model`.
- Make your hosted agent optimizer-ready: add
  `azure-ai-agentserver-optimization`, create `.agent_configs\baseline\` beside
  the agent project, and call `load_config()` at startup so optimization
  candidates can override instructions/model during evaluation.
- Create optimizer dataset: `azd ai agent eval generate` can create a runnable
  `eval.yaml`, but `azd ai agent optimize` still depends on the hosted agent
  being optimizer-ready.

One additional evaluator-generation operation was created while testing the
current CLI shape:
`evaluatorgen-assurance-analyst-contract-grounding-rubric-optimizer-v1-a04fb179`
(`succeeded`). No optimizer operation ID or candidate IDs were created.

Current credible route before RFT:

1. Patch the shared Forge prompt so invoice-assurance evidence tasks return the
   strict Caliber evidence JSON contract (`agent`, `plane`, `output_type`,
   `correlation`, `evidence`, `unsupported`, and `summary`). Keep concise
   human-readable status answers only for pure Waypoint status questions.
2. Scaffold hosted Agent Optimizer support in Forge for `assurance-analyst`:
   add `azure-ai-agentserver-optimization`, call `load_config()` in `main.py`,
   and create `.agent_configs\baseline\metadata.yaml` plus `instructions.md`
   from the reviewed prompt. This is required before a non-interactive
   optimizer job can be created.
3. Use the reviewed rubric eval config as the optimizer dataset/evaluator input,
   run `azd ai agent optimize` with an existing supported optimization model
   deployment, apply the selected candidate locally, then review the Forge diff
   before deploy.
4. Rerun the contract-grounding rubric and Caliber grader calibration. Submit RFT
   only if the remaining failures are grounded reasoning/citation failures rather
   than prompt-contract or tool-description issues.

Caliber can inspect this readiness without touching Forge:

```powershell
uv run caliber optimizer plan `
  --forge-path C:\path\to\forge `
  --agent assurance-analyst `
  --dataset datasets\assurance-analyst\assurance-analyst-eval.jsonl `
  --eval-config runs\eval-results\assurance-analyst\assurance-analyst-contract-grounding-rubric.eval.yaml `
  --json
```

Recommended local storage:

```text
runs/
  optimizer/
    <agent>/
      generated-<date>/              # ignored, raw azd/Foundry generated suites/rubrics
      baseline-<date>.json           # ignored, raw optimizer/baseline output
  traces/
    <agent>/
      candidates-<date>.jsonl        # ignored, unreviewed trace harvest
      harvest-<date>.json             # ignored, raw exported query rows
  eval-results/
    <agent>/
      <model>-<date>.json             # ignored generated eval output
datasets/
  <agent>/
    <agent>-seed-v1.jsonl             # committed only when intentionally curated
    <agent>-traces-v1.jsonl           # committed/reviewed dataset
graders/
  <agent>/
    <agent>_grader.py
optimizer/
  <agent>/
    intent.json                       # committed generation source and review intent
    reviewed/                         # committed only after human review
      evaluator-v1.json
      eval.yaml
      baseline-summary-v1.json
```

If a workflow needs Foundry-registered evaluation suites or datasets, write a
Caliber manifest first, then ask before syncing to Foundry or touching Forge's
own `.foundry/` cache.

## Candidate trace row shape

Trace candidates should keep enough lineage for audit and replay:

```json
{
  "messages": [
    {"role": "user", "content": "original user request"}
  ],
  "expected": {
    "text": "",
    "labels": []
  },
  "expected_tools": [],
  "metadata": {
    "source": "foundry_trace",
    "agent": "<forge-agent-name>",
    "environment": "<env>",
    "conversationId": "<conversation-id>",
    "responseId": "<response-id>",
    "harvestRule": "error|latency|low_eval|sample",
    "timeRange": "last 7 days",
    "reviewStatus": "candidate"
  }
}
```

Curated rows should change `reviewStatus` to `approved` and add expected
outcomes, labels, tool expectations, or rubric metadata.

## Fine-tuning workflow requirements

Before submitting any real model fine-tuning job:

1. Run the matching non-model optimization path for the target Forge agent where
   applicable: azd/Foundry rubric and evaluator generation, human review of
   generated assets, evaluator/baseline eval, optimizer or prompt-agent asset
   update, local source review, and approved Forge update. For direct `azd ai
   agent optimize`, confirm the selected target is a Python hosted azd service or
   approved hosted harness.
2. Run a baseline eval on the optimized Forge agent or selected base model.
3. Validate dataset format and train/validation/eval splits.
4. Calibrate graders so the base model has a meaningful failure rate; avoid
   graders that always pass or always fail.
5. Measure quality, latency, and token cost together.
6. Treat checkpoint selection as an evaluation decision, not an automatic final
   model choice.
7. Deploy a fine-tuned model only after held-out evals show improvement.

For `contract-policy-expert`, the accepted optimizer quality target is
`opt_994a956b2d6e49939506323a15dfc5d2`:

```text
baseline: cand_bc834224066e45d8938aa2fa738a9720, score 0.5084
candidate_1: cand_ff59c418490e4fd9bd3380d8e8e2a732, score 0.8159
candidate_2: cand_270e4602da7b41aeb47c82d3cfbbdd01, score 0.8379
candidate_3: cand_9f784632464f4155a7f532b37288806f, score 0.8344
peak: cand_6bf6980ed16f4538ba0faf8935d93c01, score 0.8521
```

Use that hill climb as the RFT handoff: the peak `gpt-5.5` candidate is the
quality target, and the fine-tuned cheaper model must preserve that behavior
while reducing measured eval cost.

For `assurance-analyst`, start with Ledgerfield clause-grounded scenarios and
Forge's retrieval-backed `contract-policy-evidence-compliance` eval as held-out
coverage, then curate trace candidates around
`knowledge_base___knowledge_base_retrieve` calls. Preserve retrieved
evidence with each candidate row so graders can check policy correctness,
citation/grounding support, and refusal boundaries before rows are promoted into
committed Caliber datasets.

The local Ledgerfield data operation is `caliber datasets contract-policy build`.
It reads the Ledgerfield checkout, extracts scenario-linked invoice lines plus
contract/policy Markdown sections, and writes Caliber-owned JSONL splits under
`datasets\assurance-analyst\`. Use `--variants-per-scenario` to create
deterministic prompt variants for each scenario; variants change request wording
and metadata only, preserving the same expected grounded evidence. This command
does not call the Foundry control plane or data plane.

Use a meaningful Foundry eval suite name for this lane:
`assurance-analyst-contract-grounding-rubric`. Generate rubric-based evaluator
assets from the deployed prompt agent with `azd ai agent eval init`, then review
the generated rubric before treating it as durable. Store local generated configs,
operation IDs, raw invocations, and output-items under ignored
`runs\eval-results\assurance-analyst\`.

```powershell
azd ai agent eval init `
  --project-endpoint <foundry-project-endpoint> `
  --agent assurance-analyst `
  --dataset runs\eval-results\assurance-analyst\assurance-analyst-prompt-eval-input.jsonl `
  --gen-instruction-file C:\path\to\forge\agents\assurance-analyst\prompt.md `
  --eval-model gpt-5.5 `
  --name assurance-analyst-contract-grounding-rubric `
  --out-file runs\eval-results\assurance-analyst\assurance-analyst-contract-grounding-rubric.eval.yaml `
  --no-wait `
  --no-prompt `
  --output json
```

This rubric route helps fine-tuning, but it is not itself training data. Use it
to baseline the prompt agent, find grounded-reasoning and citation failures,
calibrate `graders\assurance-analyst\assurance_evidence_grader.py`, select
held-out eval cases, and decide whether the remaining failures justify RFT
instead of prompt/tool changes. Do not use generated rubrics as reward graders
until they are reviewed and aligned with the deterministic Caliber grader.

Current route status:

- Suite name: `assurance-analyst-contract-grounding-rubric`.
- Input data: `runs\eval-results\assurance-analyst\assurance-analyst-prompt-eval-input.jsonl`
  from the held-out `datasets\assurance-analyst\assurance-analyst-eval.jsonl`.
- Submitted from the Forge azd root with generated local artifacts redirected to
  Caliber ignored `runs\` storage.
- Evaluator generation operation:
  `evaluatorgen-assurance-analyst-contract-grounding-rubric-v2-9f38cf1d`
  (`succeeded`).
- Baseline eval group: `eval_781387f48ae541c4baf0e7963c7905a5`.
- Baseline run: `evalrun_3af04c6d8a1e49dcb7d274a7891a38f8`.
- Baseline run name: `assurance-analyst-contract-grounding-rubric-baseline`.
- Baseline status: `Completed`, with `24 total`, `4 passed`, `20 failed`, and
  `0 errored` reported by `azd ai agent eval show`.
- Generated config:
  `runs\eval-results\assurance-analyst\assurance-analyst-contract-grounding-rubric.eval.yaml`.
- Exported output-items:
  `runs\eval-results\assurance-analyst\output-items.jsonl` with 24 rows.
- Generated baseline agent config copied to
  `runs\eval-results\assurance-analyst\agent-configs\baseline\`.
- Forge scratch `.agent_configs\` output from `azd` was removed after copying so
  Forge remains a read-only reference checkout for this Caliber session.
- Local prompt-agent capture calibration:
  `uv run caliber grader calibrate --dataset datasets\assurance-analyst\assurance-analyst-eval.jsonl --outputs runs\eval-results\assurance-analyst\live-prompt-agent\raw-invocations.jsonl --grader graders\assurance-analyst\assurance_evidence_grader.py --json`.
  The 24-row held-out capture scored min `0.15`, max `0.43`, avg `0.322`, with
  no default threshold from `0.5` to `0.95` producing a useful pass rate. This is
  a calibration finding: the live prompt-agent output is semantically grounded
  but does not yet match the stricter Caliber RFT JSON contract for
  `agent`/`plane`/`output_type`/correlation shape. Review whether the RFT target
  should train toward the strict Caliber evidence contract, or whether the grader
  should intentionally accept the deployed prompt-agent schema before submitting
  any tuning job.
- Completed Foundry output-item calibration:
  `uv run caliber grader calibrate --dataset datasets\assurance-analyst\assurance-analyst-eval.jsonl --outputs runs\eval-results\assurance-analyst\output-items.jsonl --grader graders\assurance-analyst\assurance_evidence_grader.py --json`.
  After normalizing Foundry's string-encoded `output_text` content wrapper, the
  24-row export scored min `0.0`, max `0.43`, avg `0.069`. Default thresholds
  `0.5` through `0.95` produced `0.0` pass rate; lower threshold probes produced
  pass rates of `0.25` at `0.05`/`0.1`/`0.15` and `0.083` at `0.2` through
  `0.4`. This confirms a pre-RFT no-go for the strict Caliber contract: fix the
  prompt/schema and hosted optimizer readiness first, then rerun rubric and
  calibration.

When exporting output-items, do not grade every message in `sample.output` as
assistant text. Use the last assistant message as the final answer and preserve
tool-role messages as evidence traces for grounding checks.

For branch-native `assurance-analyst` calibration, first produce a fresh
prompt-agent eval from the Forge worktree:

```powershell
python scripts\deploy_prompt_agents.py --project-endpoint <endpoint> --agent assurance-analyst --output-json
azd ai agent eval init --project-endpoint <endpoint> --agent assurance-analyst --dataset <query-shaped-jsonl> --gen-instruction-file agents\assurance-analyst\prompt.md --eval-model gpt-5.5 --name assurance-analyst-contract-grounding-rubric --out-file <ignored-caliber-runs-path>\assurance-analyst-contract-grounding-rubric.eval.yaml --no-wait --no-prompt --output json
azd ai agent eval run --config <ignored-caliber-runs-path>\assurance-analyst-contract-grounding-rubric.eval.yaml --name assurance-analyst-contract-grounding-rubric-baseline --no-prompt
```

If the merged eval config still has `agent.kind: hosted`, change it to `prompt`
before the branch-native eval run.

## Planned CLI surface

Proposed commands:

```powershell
uv run caliber traces plan --agent <agent> --environment <env> --rule low_eval --days 7
uv run caliber traces transform --input runs\traces\<agent>\harvest.json --out runs\traces\<agent>\candidates.jsonl
uv run caliber traces curate --input runs\traces\<agent>\candidates.jsonl --out datasets\<agent>\<agent>-traces-v1.jsonl
uv run caliber datasets contract-policy build --ledgerfield-path <ledgerfield-checkout> --variants-per-scenario 8
uv run caliber eval export-output-items --project-endpoint <endpoint> --eval-id <eval-id> --run-id <run-id> --out runs\eval-results\<agent>\output-items.jsonl
uv run caliber optimizer plan --forge-path <forge-checkout> --agent <agent> --dataset datasets\<agent>\<agent>-eval.jsonl --eval-config runs\eval-results\<agent>\<suite>.eval.yaml
uv run caliber grader calibrate --dataset datasets\<agent>\<agent>-traces-v1.jsonl --grader graders\<agent>\<agent>_grader.py
uv run caliber grader calibrate --dataset datasets\<agent>\<agent>-eval.jsonl --outputs runs\eval-results\<agent>\output-items.jsonl --grader graders\<agent>\<agent>_grader.py
uv run caliber rle plan --agent <agent> --environment <env> --train datasets\<agent>\<agent>-train.jsonl --validation datasets\<agent>\<agent>-val.jsonl --eval datasets\<agent>\<agent>-eval.jsonl --grader graders\<agent>\<agent>_grader.py
uv run caliber eval run --dataset datasets\<agent>\<agent>-traces-v1.jsonl --grader graders\<agent>\<agent>_grader.py --target hosted
uv run caliber rft submit --train datasets\<agent>\<agent>-train.jsonl --validation datasets\<agent>\<agent>-val.jsonl --grader graders\<agent>\<agent>_grader.py
```

Keep `plan` and `transform` available offline so the repo remains useful even
when Azure access is unavailable.
