# Contract Policy Analyst

Independent, read-only contract and policy reviewer for fictional Caldova.
All model arms use the expert's real FoundryIQ dispatch:
`contracts-kb-mcp___knowledge_base_retrieve` with `query_variants`.
The existing Contract Policy Expert and parked Contract Evidence Analyst are
unchanged.

## Baseline provenance

The current baseline (`.agent_configs/baseline`, "naive v2") is better but
still naive. It states a role, the evidence-only task and read-only boundary,
the one retrieval tool and its sources, and the answer format. It has no worked
examples, grader flags, scoring rules, or arithmetic/tier/approval heuristics.
A rubber-duck review found no rubric leakage. Its tool and query descriptions
match the runtime defaults in `toolbox.py`.

The first baseline is preserved byte-for-byte in
`releases/astra-baseline-v1/baseline` (instructions `9b048c89…`, tools
`446d29dc…`; deployed as v1–v5). It copies the initial retrieval-capable
instructions from commit `5aac278` with only the agent name changed. The later
`530f966` seed prohibited retrieval and encouraged inferred citations, so it
is not a valid starting point for this tool-enabled comparison. Select the old
baseline with `deploy_version.ps1 -Release astra-baseline-v1`.

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

Native optimizer candidates arrive at startup through `OPTIMIZATION_CONFIG`,
or through `OPTIMIZATION_CANDIDATE_ID` with a valid project
`OPTIMIZATION_RESOLVE_ENDPOINT` under `/agent_optimization_jobs/<job>`.
The inline path uses the installed optimization SDK. The resolver uses Castia's
GA candidate-config client; the SDK's older preview resolver route is unsupported.
Both paths validate the actual candidate payload before constructing the model.
Only instructions and tool descriptions can change. Unknown fields, missing
instructions, changed models or schemas, and unresolved candidate IDs stop startup.
The effective candidate hashes are recorded by native capture.

An operator-applied local candidate must exist and match its own files. Missing
candidates cannot fall back to `baseline/`. With no injection, the baseline
instructions and tool definitions remain unchanged. HTTP request instructions,
tools, and capture metadata do not override the startup configuration. Castia
0.19.0 has no candidate channel in its request context.

### Optimizer flow (azd agents extension 1.2.0)

Probe job `opt_b3e66152116048cea11621393d52835e` established the working path:

- Submit with a GA `OptimizeRequest` file via `azd ai agent optimize --config`.
  Legacy `eval.yaml` is rejected. With `--no-prompt`, the flag and
  `--eval-config` routes omit `agent_optimization_space` and return 400. The
  request file must set `target_attributes` (e.g. `[instructions, tools]`).
- During screening, the platform injects mini IDs
  (`cand_<job>_<NNNN>_mini_<sha>`) with a job-scoped resolver. The GA
  `/candidates/<mini>/config` route serves them; captures showed each candidate's
  own hashes.
- `optimize apply` resolves only materialized candidates and returns 404 on mini
  IDs. It also rewrites `azure.yaml` with a static `OPTIMIZATION_CANDIDATE_ID`.
  Restore `azure.yaml`. The CLI also rewrites `.agent_configs/baseline/metadata.yaml`
  (drops `tools_file`) and reformats `tools.json`; revert both.
- To deploy a candidate, place its files in `.agent_configs/<id>/` (from `apply`,
  or from the `/config` payload for a mini ID). Then run
  `scripts/deploy_version.ps1 -Release baseline -Candidate <id>`. That sets
  `CPA_APPLIED_CANDIDATE_ID`, which stays separate from the platform-injected
  variable; a conflicting injection fails startup. Version 9 served the applied
  candidate's hashes, not the baseline's, with real retrieval.
- Response IDs must use the platform format `{prefix}_{16 hex}00{32 hex}`.
  castia ≤0.19.0 mints `resp_{uuid4().hex}`, and the platform rejects those
  IDs with `400 Malformed identifier` when the optimizer fetches the agent's
  response. Every eval item then reports `TARGET_INVOCATION_FAILED` and is
  scored on empty output. Because of this, the optimizer scores for the probe
  above and for `opt_4fa59c4f…` (r1) are invalid; their run folders contain
  `SCORES-INVALID.json`. castia 0.20.1 fixes ID precedence and adds hosted
  Foundry persistence (sethjuarez/castia#143, sethjuarez/castia#147).
  This agent pins it. `tests/test_response_ids.py`
  guards the format. Before trusting any optimizer score, check that its eval
  output_items have no `sample.error`.

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

Historical v8 study runs pin Castia 0.19.0; new versions pin 0.20.1. Its operator-only
`CASTIA_TOOL_CAPTURE=blob` mode writes create-only `castia.tool_capture/v1`
documents containing full tool arguments/results, response/call/trace IDs,
release provenance, timing and canonical hashes. Client metadata cannot enable
capture. Payload caps and sink failures do not change the model response;
evaluation rejects missing, incomplete, ambiguous or hash-invalid evidence.
Capture is off by default and enabled only on evaluation versions.

The private `castia-tool-captures` container holds captures and historical
Responses state. The hosted identity needs container-scoped Storage Blob Data
Contributor for captures; the evaluator needs read access. New hosted versions
use Castia's default `FoundryResponseStore`, not `BlobResponseStore`: responses
are published to Foundry storage and read through the project Responses API.
Blob persistence alone does not make a response visible there.
`response_store.py` remains available for local and historical Blob workflows;
it must not replace the hosted Foundry store. Background and
`previous_response_id` are unsupported on the Foundry store. Backend failures
propagate rather than impersonating missing responses. No automatic deletion
or capture-retention sweep is configured. Existing 0.15.0 smoke captures remain
historical evidence.

This independent evaluation agent serves Responses only, as required by the
optimizer. The existing expert's Teams protocol and runtime are unchanged.

Live retrieval can drift. Record queries and retrieval payload hashes for each
attempt, plus canaries before and after a batch. A matching function tool alone
does not demonstrate faithful retrieval or tool-use learning from RFT.

Batch invocations require `--instructions-sha256` and `--tools-sha256` from the
verified effective deployment configuration. Every native capture must match
these frozen hashes; a nonempty hash or successful reply alone is insufficient.

Judge-only recovery permits one retry of an issued request that resets mid-read
with no HTTP status or result body. Preserve the failed receipt with billing
unknown, wait at least 10 seconds, and reuse the exact saved response and context.
Count the retry against the shared ten-retry per-arm budget; never rerun the
agent or select the best of multiple judge results. An unsuccessful retry is an
operational zero with quality unknown. The frozen v8 runner remains unchanged:
`runs/capacity_rejudge.py --read-reset-case <case/run key>` performs the approved
recovery, stores an immutable recovery ledger and reserves the shared budget.
HTTP 500/502/503/504/429 retries and proven-unissued connection retries retain
their existing limits.

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
Recorded inference failures count as operational zero without fabricated judge
scores or capture evidence; the batch continues only unissued trials. Reports
separately identify inference failures and quality conditional on scored responses.
Unknown usage remains unknown, and unverified captures cannot imply complete
retrieval coverage. When the runner changes, preserve the original manifest and
grades: a new revision may reuse exact saved responses and hash-bound judge
requests, never substitute fresh inference for a failed or uncertain attempt.
Judge connection establishment may try at most five times, with create-only
request/error/completion receipts under `judge-transport`. Only SDK `ConnectError`
causes with no HTTP status or judge body qualify for unissued connection recovery.
Back off 10/20/40/60 seconds plus bounded positive jitter; prior failed attempts
count after resume. Five exhausted unissued connections produce an explicit
operational zero with unknown task quality, while preserving the actual agent
response, capture and model cost. Continue until more than five cases in an arm
exhaust connections, then stop as an outage. Separately, judge HTTP 500/502/503/504/429
without a judge result may retry once per case/run, up to ten per arm/batch.
Honor Retry-After with at least ten seconds of backoff. Preserve the failed
request and its unknown billing; use the first valid judge, never best-of.
Atomic reservation files prevent a second retry or exceeding the batch cap.
Any failed HTTP retry, other 4xx, returned judge body, read/write failure or
unresolved started request stops the batch. Completed judge receipts are reused
exactly; agent inference itself is never retried. Judge token estimates retain a
known subtotal, but total judge cost stays unknown after server-error retries.

The original quality grader v1 rejects judge flags `false_approval` and
`missed_approval` as unrecognized, leaving those judgments unverified. Keep
v1 results and hashes intact. The separate `contract_policy_analyst_grader_v2.py`
pins v1 and adds explicit caps of 0.20 and 0.35 respectively; it does not
relax any existing cap. Retrospective v2 regrades reuse the exact recorded
responses, verified captures and bound judge results, and are not prospective
or human-calibrated.

**Frozen grader (v3; supersedes the 2026-11-25 v2 freeze).** Grader v3 (SHA256
`7c9ce4b3…`, pinning v1 base `267d5f6c…6f62`) with rubric v3, references v3
and RFT reward v2 (`127729d0…`) is the single quality grader for every future
live run: optimizer/candidate evals, checkpoint selection, the post-RFT eval
and the sealed final test. The batch runner hash-checks all four files,
records versions/hashes in each manifest, and refuses summaries mixing grader
revisions. The comparison anchor is the v3 regrade in
`runs\baseline-offline-regrade-v3\report.json` (tracked copy:
`modules\evals\datasets\contract-policy-analyst\expanded-v1\offline-regrade-v3-report.json`);
never compare v1, v2 and v3 numbers. The RFT trainer reward cannot call the
judge, so it is the deterministic code-only surrogate
`contract_policy_analyst_rft_reward_v2.py`; a test keeps its shared caps equal
to v3. Reported quality for tuned checkpoints always comes from v3, not the
reward. The v2 report and files remain immutable history.

RFT preflight rejects explicit batch sizes outside 1-256; omit the field for
automatic selection rather than sending `-1`. Before the substantive MAI-2
job, verify an always-true reward probe in the actual trainer. A successful
standalone grader request is not proof that training honors its reward.
MAI-2 training JSONL must use `developer`, never `system`; verify that offline
before upload. An optimized deployment must prove its effective instruction and
tool hashes match the selected candidate before it can enter the comparison.
