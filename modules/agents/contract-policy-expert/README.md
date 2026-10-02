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

## Foundry monitoring and Insights setup

Use this checklist when the Foundry **Monitor** and **Insights** tabs look empty
for this hosted agent.

### Hosted retrieval and tool calls

The hosted agent must have the same toolbox endpoint resolution that local runs
use. Keep these values in the deployed hosted environment:

```yaml
FOUNDRY_PROJECT_ENDPOINT: ${FOUNDRY_PROJECT_ENDPOINT}
TOOLBOX_NAME: contract-toolbox
TOOLBOX_CONTRACT_TOOLBOX_MCP_ENDPOINT: ${TOOLBOX_CONTRACT_TOOLBOX_MCP_ENDPOINT}
AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED: "true"
```

After deployment, smoke test through the Responses protocol with a prompt that
requires FoundryIQ retrieval. App Insights should show:

- a request or dependency named `tools/call contracts-kb-mcp___knowledge_base_retrieve`;
- a dependency named `execute_tool contracts-kb-mcp___knowledge_base_retrieve`;
- the MCP dependency for `/toolboxes/contract-toolbox/mcp`.

If answers are grounded but the **Tool calls** tile is empty, query App Insights
for `contracts-kb-mcp___knowledge_base_retrieve` before changing code. Castia's
tool loop already emits `execute_tool` spans when the model calls the function.
The Azure CLI query command applies its own one-hour window unless `--offset` or
explicit start/end times are passed, even when the KQL uses `ago(...)`.

```powershell
az monitor app-insights query `
  --subscription $env:AZURE_SUBSCRIPTION_ID `
  --app <app-insights-name> `
  --resource-group $env:AZURE_RESOURCE_GROUP `
  --offset 4h `
  --analytics-query @'
dependencies
| where timestamp > ago(4h)
| extend cd = todynamic(customDimensions)
| where * has "contract-policy-expert" or * has "contracts-kb-mcp"
| summarize count() by operation=tostring(cd["gen_ai.operation.name"]), type
| order by operation asc
'@
```

The Caldova hosted smoke run emitted `execute_tool` spans with type
`GenAI | microsoft.foundry`. If raw App Insights traces show those rows but the
Foundry chart is empty, wait for the Monitor aggregate to catch up before
changing instrumentation.

Foundry can also show the tools connected to a run from the available-tool
metadata, not just from completed calls. Check that `invoke_agent` spans carry
`gen_ai.tool.definitions`, and that each executed tool span carries
`gen_ai.operation.name = execute_tool` plus `gen_ai.tool.name`. The hosted
version `12` smoke run has both:

- `gen_ai.tool.definitions` on `invoke_agent contract-policy-expert:12`;
- `gen_ai.tool.name = contracts-kb-mcp___knowledge_base_retrieve` on
  `execute_tool contracts-kb-mcp___knowledge_base_retrieve`.

### Evaluation chart data

Run a Foundry eval after deployment so the **Monitor** tab has chart data:

```powershell
cd modules\agents\contract-policy-expert
$env:AZURE_DEV_USER_AGENT = "microsoft_foundry_skill"

azd ai agent eval run `
  --agent contract-policy-expert `
  --project-endpoint $env:FOUNDRY_PROJECT_ENDPOINT `
  --config eval.baseline.yaml `
  --name contract-policy-expert-monitor-baseline
```

The baseline config points at registered dataset
`contract-policy-expert-test-foundry-eval` version `2.0` and rubric
`contract-policy-expert-generated-rubric` version `13`. In the Caldova project,
the monitor seed run on hosted version `12` completed 24/24.

### Scheduled evaluations

Hosted agents do not support `responseCompleted` evaluation rules. Foundry
rejects them with:

```text
The agent 'contract-policy-expert' is of kind 'hosted', which is not supported
for evaluation rules. Hosted and external agents are not supported.
```

For hosted agents, use a Foundry schedule over an eval group and trace data. The
current schedule ID is `contract-policy-expert-hourly-trace-eval`. It runs
hourly against the trace-evaluation group and uses an
`azure_ai_trace_data_source_preview` data source filtered to
`agent_name = contract-policy-expert`.

The shape is:

```python
from azure.ai.projects.models import CronTrigger, EvaluationScheduleTask, Schedule

eval_run = {
    "eval_id": eval_id,
    "name": "contract-policy-expert scheduled monitor evaluation",
    "data_source": {
        "type": "azure_ai_trace_data_source_preview",
        "trace_source": {
            "type": "agent_filter",
            "agent_name": "contract-policy-expert",
            "start_time": start_unix,
            "end_time": end_unix,
            "max_traces": 25,
        },
    },
    "metadata": {"agent_name": "contract-policy-expert"},
    "evaluation_level": "conversation",
}

project_client.beta.schedules.create_or_update(
    schedule_id="contract-policy-expert-hourly-trace-eval",
    schedule=Schedule(
        display_name="Scheduled evaluation: contract-policy-expert hourly",
        enabled=True,
        trigger=CronTrigger(expression="0 * * * *", time_zone="UTC"),
        task=EvaluationScheduleTask(eval_id=eval_id, eval_run=eval_run),
    ),
)
```

List schedules and runs with the SDK:

```python
list(project_client.beta.schedules.list())
list(project_client.beta.schedules.list_runs("contract-policy-expert-hourly-trace-eval"))
```

### Actionable Insights

Insights in Foundry analyzes production traces and creates cards only when it
finds repeated behavior worth review. A successful scan can still return zero
cards.

The required setup is:

- a GPT-5 or newer judge deployment;
- recent traces for `contract-policy-expert`;
- Application Insights connected to the Foundry project;
- the interactive user has the hosted-agent Insights role required by Foundry;
- the project managed identity can read the judge model deployment;
- the project managed identity has `Monitoring Reader` on the connected
  Application Insights resource and linked Log Analytics workspace;
- if `AppGenAIContent` is protected, the project managed identity also has
  `Privileged Monitoring Data Reader` on the App Insights resource or linked
  workspace.

The generic failure:

```text
A required Agent Insights dependency is unavailable.
```

usually means one of those prerequisites is missing. In Caldova, the fix was to
grant the project managed identity:

```powershell
az role assignment create `
  --assignee-object-id <project-managed-identity-principal-id> `
  --assignee-principal-type ServicePrincipal `
  --role "Monitoring Reader" `
  --scope <app-insights-resource-id>

az role assignment create `
  --assignee-object-id <project-managed-identity-principal-id> `
  --assignee-principal-type ServicePrincipal `
  --role "Monitoring Reader" `
  --scope <log-analytics-workspace-resource-id>
```

If protected table access is enabled, also grant:

```powershell
az role assignment create `
  --assignee-object-id <project-managed-identity-principal-id> `
  --assignee-principal-type ServicePrincipal `
  --role "Privileged Monitoring Data Reader" `
  --scope <log-analytics-workspace-resource-id>
```

After RBAC propagation, rerun:

```python
from azure.ai.projects.models import AgentInsightRunCreate

project_client.beta.agent_insight_monitors.begin_create_run(
    monitor_id,
    AgentInsightRunCreate(lookback_hours=2),
).result()
```

For the Caldova agent, scans now succeed and analyze traces. The current empty
Insights tab means `insights_created`, `insights_updated`, and
`insights_reopened` are all zero. That is a healthy empty result, not a setup
failure.
