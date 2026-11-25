# Contract Policy Analyst

Independent, read-only contract and policy reviewer for fictional Caldova.
All model arms use the expert's real FoundryIQ dispatch:
`contracts-kb-mcp___knowledge_base_retrieve` with `query_variants`.
The existing Contract Policy Expert and parked Contract Evidence Analyst are
unchanged.

## Baseline provenance

The baseline copies the initial retrieval-capable instructions from commit
`5aac278`, with only the agent name changed. It is an honest starter, not a
prompt sabotaged to produce a large improvement. The later `530f966` seed
explicitly prohibited retrieval and encouraged inferred citations; that is
not a valid starting point for this tool-enabled comparison.

The short tool and query descriptions come from the expert's runtime defaults.
Unlike the historical MCP optimizer overlay, the optimizer sees the exact
function schema that every model receives. Candidates can change description
wording; changing the tool name or query schema fails release validation.

## Runtime

```powershell
uv sync
uv run pytest -q
uv run ruff check .
uv run python main.py
```

Non-secret deployment values are supplied through the standalone azd
environment. `.env.example` documents the required settings; never commit real
environment values. Both Astra and MAI use the account-level Responses route.
The hosted identity needs Foundry User on the project and Cognitive Services
OpenAI User on the account. Retrieval uses the toolbox's own scoped token.

`OPTIMIZATION_LOCAL_DIR` selects a release directory containing `baseline/`.
Startup rejects missing or mismatched instruction/tool files rather than
silently running another arm. `CPA_REASONING_EFFORT` is pinned per release.

## Measurement boundaries

The historical 24 cases are regression evidence, not a pristine test. New
held-out cases must be source-grounded, separate from optimizer train and
validation, and sealed before selection. Synthetic labels remain
`pending_human_review`. All attempts count; five repeats are not five times
as many independent cases. Compare paired case means with confidence intervals.

### Native observability and complete evaluation evidence

Castia owns the normal `execute_tool` and model-loop traces. Content-enabled
model spans can record the messages containing actual function results.
Export requires an Azure Monitor/App Insights binding; content recording is
explicitly enabled with `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true`.
Do not infer an export binding or complete payload capture from span names.
`CPA_NATIVE_TRACE_PROJECT=true` discovers the existing project AppInsights
connection at process startup and lets Castia initialize its own exporter.
The connection credential stays process-local; it is not copied into azd,
source files or evidence. Existing explicit exporter settings take precedence.
Discovery failures produce a warning, not a fabricated tracing-success result.

Checked the installed 0.15.0 against published
[0.18.1](https://github.com/sethjuarez/castia/releases/tag/python-v0.18.1):
neither returns locally executed function-call trajectories in the outer hosted
Responses output. Native developer diagnostics summarize tool results to
[500 characters](https://github.com/sethjuarez/castia/blob/python-v0.18.1/packages/python/src/castia/observe/dev_diagnostics.py),
so they cannot replace complete retrieval passages in the evidence grader.
The newer release does not resolve that gap; this agent retains its current pin.

`retrieval_audit.py` supplements those native traces only with exact raw tool
results required by evaluation. It records the native trace/span and platform
call IDs when available, task/output hashes and release configuration hashes.
It never supplies reference answers to the model or registers another tool.
When `CPA_AUDIT_ACCOUNT_URL` is set, immutable JSON records go to the private
`cpa-eval-audits` container. The hosted identity needs Storage Blob Data
Contributor scoped to that container; the evaluator needs read access.
Missing configuration disables this supplemental upload, not native tracing.
An enabled upload failure propagates instead of returning unaudited success.
Evaluation must reject absent, incomplete or ambiguous matching records.

Live retrieval can drift. Record queries and retrieval payload hashes for each
attempt, plus canaries before and after a batch. A matching function tool alone
does not demonstrate faithful retrieval or tool-use learning from RFT.
