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

All study arms pin the validated Castia 0.19.0 release. Its operator-only
`CASTIA_TOOL_CAPTURE=blob` mode writes create-only `castia.tool_capture/v1`
documents containing full tool arguments/results, response/call/trace IDs,
release provenance, timing and canonical hashes. Client metadata cannot enable
capture. Payload caps and sink failures do not change the model response;
evaluation rejects missing, incomplete, ambiguous or hash-invalid evidence.
Capture is off by default and enabled only on evaluation versions.

The private `castia-tool-captures` container holds captures and shared Responses
state. The hosted identity needs container-scoped Storage Blob Data Contributor;
the evaluator needs read access. `response_store.py` supplies atomic ETag-checked
state updates for background evaluation/optimizer polling across replicas.
Backend failures propagate rather than impersonating missing responses.
In-flight execution remains process-bound even with shared state; preserve
failed attempts if a worker restarts. No automatic deletion or retention sweep
is configured. Existing 0.15.0 smoke captures remain historical evidence.

This independent evaluation agent serves Responses only, as required by the
optimizer. The existing expert's Teams protocol and runtime are unchanged.

Live retrieval can drift. Record queries and retrieval payload hashes for each
attempt, plus canaries before and after a batch. A matching function tool alone
does not demonstrate faithful retrieval or tool-use learning from RFT.
