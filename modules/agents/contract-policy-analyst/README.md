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

The first training-only integration pilot exposed two measurement defects:
native capture success fields differed from the transcript adapter, and shared
request metadata was incorrectly excluding reference parts from canaries.
Preserve those original results as invalid calibration evidence, not baseline
quality. Regrade saved model outputs in a new revision with a fresh judge request
bound to the corrected, actual retrieved context; do not rerun the model or reuse
the old empty-context judge.

Broad KB retrieval also returned passages from the original `study-heldout`
families during training calibration. That split is now exposed-source
regression evidence, not a pristine headline. The replacement `final-test-v2`
families must stay sealed offline and unindexed until optimizer, RFT checkpoint
and configuration selection are frozen.

`caliber.contract_policy_analyst_batch` preserves version-pinned invocation
starts, responses, native captures and judge requests in a private output
directory. It rejects uncertain inference reruns, stale grader/parser bindings,
changed judge inputs and partial summaries. Case IDs are hashed for filenames
because their colons would create alternate data streams on Windows. Canary
reparsing uses `scripts/corpus_canaries.py --offline-from`; live retries require
`--allow-live` and a separate output directory.

RFT preflight rejects explicit batch sizes outside 1-256; omit the field for
automatic selection rather than sending `-1`. Before the substantive MAI-2
job, verify an always-true reward probe in the actual trainer. A successful
standalone grader request is not proof that training honors its reward.
MAI-2 training JSONL must use `developer`, never `system`; verify that offline
before upload. An optimized deployment must prove its effective instruction and
tool hashes match the selected candidate before it can enter the comparison.
