# Invoice Assurance E2E Readiness TODO

> [!WARNING]
> Historical readiness tracker retained for provenance. Its agent names, live
> resource details, and open items predate the validated monorepo deployment.
> Use [FORGE_CURRENT_STATE.md](FORGE_CURRENT_STATE.md) and
> [docs/deployment.md](../../../docs/deployment.md) for current state.

This was the living record for what remained before the Assurance Orchestrator invoice assurance
pipeline is honestly end-to-end.

For the current agent fleet, deployment paths by kind, shared resources, stubbed
surfaces, and Jess completion checklist, see
[`FORGE_CURRENT_STATE.md`](FORGE_CURRENT_STATE.md).

The goal is not merely "the agents start." The goal is:

1. Assurance Orchestrator accepts an invoice plus PDF input.
2. Content Understanding extracts invoice facts.
3. Assurance Orchestrator fans out to each IQ evidence plane.
4. Each IQ returns a structured evidence contract with cited sources.
5. Assurance Orchestrator prepares or hands off a governed write payload.
6. The waypoint-recorder performs the only Waypoint write.
7. The resulting Waypoint case/run/recommendation/draft can be inspected in the
   Waypoint app.

## Current honest status

| Area | Current state | Gap to real E2E |
| --- | --- | --- |
| Assurance Orchestrator | Content Understanding extraction works when PDF input is supplied; deterministic workflow runs; IQ fan-out plumbing exists; write plan is read-only. The local canvas/orchestrator can hand that preview to the waypoint-recorder. Hosted diagnostic fan-out now proves WebIQ/FoundryIQ/FabricIQ lane calls complete and WorkIQ failure is surfaced without writes. Latest local Mission Control run (2026-06-27) called `assurance-orchestrator_run_invoice_assurance_workflow` for `INV-2026-08034`, reached all 4 validator lanes, produced 1 future payload, and kept `side_effects_performed=false`. | Latest local Mission Control run did not include PDF input, so Content Understanding was `not_invoked`. WorkIQ still fails in hosted smoke, and hosted/deployed handoff to the waypoint-recorder still needs proof. |
| Content Understanding | Live Forge validation passed for PDF URL and binary/base64 PDF input. The defaults script validates deployments and skips no-op PATCHes. A read-only preflight confirms the Forge AI Services account has the required `gpt-4.1` and `text-embedding-3-large` deployments and defaults. | Active hosted `assurance-orchestrator` version 13 is missing the `CONTENT_UNDERSTANDING_*` env vars; redeploy before live hosted PDF extraction smoke. Latest local Assurance Orchestrator workflow run did not pass `pdf_uri`/`pdf_base64`, so CU was not invoked in that trace. Need fresh-environment validation through the GitHub deploy workflow. |
| Waypoint Recorder | Governed Waypoint write works when called directly with transformed Assurance Orchestrator judgement data. The waypoint-recorder accepts and tests a single Assurance Orchestrator `write_plan.future_payloads[]` preview, and the local canvas calls it automatically after a Assurance Orchestrator run. Latest local Mission Control handoff wrote `case-1ac5d25f15584805b3b7d0d8db7005a2`, `run-5cdd6a72019d437197fddd4327a6c9b9`, and `rec-eb12ebab88eb415ea311f2650f92cff6`. | Need hosted endpoint handoff validation. |
| Assurance Analyst status surface | Hosted agent owns the read-only Waypoint status tools and returns a structured failure instead of writing. | Cloud Waypoint reader auth returns 401 for `/api/cases` and `/api/runs`; merged `assurance-analyst` needs redeploy and Teams/hire surface still needs validation after auth is fixed. |
| WorkIQ | Email, Teams, and SharePoint MCP URL wiring exists with agentic identity support. Hosted version 12 starts, but the direct smoke fails because the legacy default SharePoint MCP placeholder returns HTTP 400 during MCP context setup. Code/deploy defaults now skip that placeholder until an explicit tenant-supported endpoint is configured. | Need exact MCP endpoints, scope/auth, permissions, redeploy, and a successful evidence contract. |
| WebIQ | Agent code uses Foundry native web search / Bing grounding. A hosted direct smoke returned valid `webiq` evidence JSON with source URLs from active version 12. | Not fully exercised through Assurance Orchestrator. Need prove the WebIQ validator lane completes inside Assurance Orchestrator fan-out. |
| FoundryIQ | Has local fallback tools over Waypoint contract/policy corpus, and source now points the hosted toolbox at the live `contracts-kb` RemoteTool MCP connection. A read-only live smoke validates KB/source/connection wiring and grounded retrieval with source refs. Active hosted version 11 is contract-valid but still has `TOOLBOX_MCP_ENDPOINT=""`, so it returns no evidence for `INV-2026-08034`. | Need redeploy/toolbox refresh, hosted FoundryIQ invocation through the refreshed toolbox endpoint, then Assurance Orchestrator fan-out proof. |
| FabricIQ | Current tool is intentionally stubbed and explicitly says no Fabric, OneLake, warehouse, Power BI, semantic model, or Waypoint corpus was queried for Fabric claims. | Not wired to Microsoft Fabric/OneLake/warehouse yet. Define the real Fabric source before replacing the stub. |
| Pipeline Mission Control canvas | Can run local stack and pass PDF/IQ endpoint inputs. A clean local fallback run is persisted as a session artifact with every IQ lane, waypoint-recorder handoff, and Waypoint case/run/recommendation IDs. | Need a clean run that also includes Content Understanding/PDF extraction and, separately, hosted endpoints. |
| Deploy workflow | Self-wires hosted Assurance Orchestrator endpoint env vars from the Foundry project endpoint. | Need a deployed run proving endpoints, identities, connections, model defaults, and resource dependencies work together. |

## P0 blockers

These must be resolved before calling the pipeline end-to-end.

### 1. Make the Assurance Orchestrator to waypoint-recorder handoff explicit

Assurance Orchestrator currently has two related but separate paths:

- Deterministic workflow: prepares `write_plan.future_payloads[]` and performs no
  side effects.
- Chat/tool path: exposes `handoff_to_waypoint-recorder` when `WAYPOINT_RECORDER_ENDPOINT` is
  configured.

TODO:

- Decide whether deterministic Assurance Orchestrator should:
  - remain strictly read-only and require an external orchestrator/canvas to call
    waypoint-recorder, or
  - invoke waypoint-recorder itself after preparing the write plan.
- If it remains read-only, implement and document the orchestrator/canvas
  write-plan to waypoint-recorder step. **Done locally in Pipeline Mission Control.**
- Normalize the write-plan payload into the flat shape expected by
  `waypoint-recorder.waypoint_record_assurance`. **Done for single-invoice previews in
  the waypoint-recorder tool contract.**
- Add tests proving Assurance Orchestrator never writes directly to Waypoint.

### 2. Prove WorkIQ with real Microsoft 365 MCP tools

Current wiring exists, but evidence validation failed in smoke testing.

TODO:

- Confirm the tenant-supported MCP endpoints for:
  - email
  - Teams
  - SharePoint
  **Still open; the legacy SharePoint placeholder is now explicitly rejected.**
- Confirm `WORKIQ_MCP_SCOPE` and whether the platform connection alone is
  sufficient or an explicit bearer token is required.
- Validate the hosted agent identity has the required access.
- Add a direct WorkIQ smoke that returns one evidence contract for a known
  invoice/scenario. **Blocked on real MCP endpoint/auth; current hosted smoke fails with HTTP 400 from the placeholder SharePoint MCP URL.**
- Add a Assurance Orchestrator fan-out smoke proving the WorkIQ lane returns `completed`, not
  `failed`.

### 3. Prove WebIQ through Assurance Orchestrator

The WebIQ agent is wired to Foundry native web search, but the branch has not
fully exercised WebIQ evidence behavior through Assurance Orchestrator.

TODO:

- Verify the Bing grounding resource and project connection are present in the
  target environment. **Done via hosted WebIQ smoke against `rg-forge`.**
- Run WebIQ directly with a known invoice/scenario prompt.
  **Done with `scripts\test_hosted_iq_agent.py market-evidence-expert --plane webiq --require-evidence`.**
- Verify output is JSON matching the shared evidence contract.
  **Done.**
- Run Assurance Orchestrator with WebIQ enabled and confirm the WebIQ validator lane is
  `completed`. **Done in hosted diagnostic fan-out; full run still blocked by WorkIQ.**
- Capture source URLs/citations in the evidence contract.
  **Done for direct hosted WebIQ smoke; Assurance Orchestrator lane capture pending.**

### 4. Decide what FabricIQ really is

Current FabricIQ is intentionally stubbed. It keeps the `fabriciq` evidence lane
present and contract-valid, but it does not query Microsoft Fabric, OneLake, a
warehouse, Power BI, a semantic model, or the Waypoint corpus for Fabric claims.

TODO:

- Keep the stub honest until the real Fabric source is defined.
- If true Fabric-backed, define the Fabric source:
  - workspace
  - lakehouse/warehouse
  - table/query surface
  - authentication model
  - expected invoice key fields
- Add a direct FabricIQ smoke and a Assurance Orchestrator fan-out smoke once real Fabric access
  exists.

### 5. Prove FoundryIQ against the knowledge base

FoundryIQ has local fallback tools over Waypoint contract/policy data, but the
primary intended path is now the Foundry contracts knowledge base exposed through
the `kb-mcp-connection` RemoteTool project connection.

TODO:

- Confirm `contracts-kb` exists in the target Foundry/Search environment.
  **Done for `rg-forge` with `scripts\test_foundryiq_kb.py`.**
- Confirm contracts are indexed from the intended Ledgerfield sources.
  **Done for `contracts-ks` / `contracts-kb`; policy corpus is not in this KB scope yet.**
- Confirm the KB MCP endpoint is reachable where expected.
  **Done for the Search KB MCP endpoint and `kb-mcp-connection` target.**
- Prefer Foundry knowledge-base/toolbox retrieval, with Waypoint
  contract/policy corpus only as local fallback. **Done in prompt/toolbox wiring.**
- Add direct FoundryIQ smoke proving grounded retrieval with source refs.
  **Done at the KB MCP layer with `scripts\test_foundryiq_kb.py`; hosted agent invocation still pending.**
- Validate active hosted FoundryIQ response contract.
  **Done with `scripts\test_hosted_iq_agent.py contract-policy-expert --plane foundryiq`; active version 11 returned a valid empty contract because `TOOLBOX_MCP_ENDPOINT` is not yet set.**
- Add Assurance Orchestrator fan-out smoke proving FoundryIQ returns a completed lane.
  **Done in hosted diagnostic fan-out; active FoundryIQ lane is completed but currently returns empty evidence until toolbox redeploy.**

## P1 validation

These should be done after the blockers are resolved.

### 1. Fresh-environment deploy validation

The live Forge account was manually configured and validated. The automation now
needs to prove it can configure a fresh or reset environment.

TODO:

- Run provision/deploy in a clean environment.
- Confirm `gpt-4.1` and `text-embedding-3-large` deployments exist before the
  Content Understanding defaults PATCH.
- Confirm `scripts/configure_content_understanding.py` logs "already configured"
  on a second run.
- Confirm Assurance Orchestrator receives all `CONTENT_UNDERSTANDING_*` env vars.
- Confirm the hosted Assurance Orchestrator container can call Content Understanding with its
  managed identity.

### 2. One traceable canvas run

We need one run that a reviewer can inspect without piecing together separate
manual calls.

TODO:

- Start Waypoint via Aspire.
  **Done; Waypoint Aspire API observed at dynamic HTTPS endpoints including
  `https://localhost:59158` and `https://localhost:62595`. Docker Desktop must
  be running so Aspire can start the local Postgres container.**
- Start Forge stack from Pipeline Mission Control.
  **Done; after setting local non-secret Foundry endpoint/model values, Mission
  Control started the IQ stub host and local Assurance Orchestrator Responses server.**
- Run a known existing Waypoint invoice plus PDF input.
  **Partially done for `INV-2026-08034` without PDF input; CU status was
  `not_invoked`.**
- Capture:
  - Content Understanding status
  - each IQ lane status
  - waypoint-recorder handoff/write status
  - Waypoint case/run/recommendation/draft IDs
  **Done except CU input. Latest deterministic workflow run called
  `assurance-orchestrator_run_invoice_assurance_workflow`, reached 4 validators, produced 1
  future payload, and the waypoint-recorder wrote
  `case-1ac5d25f15584805b3b7d0d8db7005a2`,
  `run-5cdd6a72019d437197fddd4327a6c9b9`, and
  `rec-eb12ebab88eb415ea311f2650f92cff6`.**
- Save the output somewhere stable enough for review. Avoid relying on truncated
  canvas JSON if the payload is large.
  **Done for an earlier run in session artifact
  `traceable-local-pipeline-smoke-20260626.json`. Latest 2026-06-27 run is
  captured in Mission Control state and session/tool output, but should be saved
  as a stable artifact if it becomes review evidence.**

### 3. Contract tests for evidence JSON

Each IQ should return the same high-level evidence contract.

TODO:

- Define the shared evidence contract shape explicitly.
- Add tests or eval cases for:
  - WorkIQ **Done for prompt contract and local stub shape.**
  - WebIQ **Done for prompt contract and local stub shape.**
  - FoundryIQ **Done for prompt contract, local stub shape, and no-corpus tool output.**
  - FabricIQ **Done for prompt contract, local stub shape, and no-corpus tool output.**
- Validate required fields:
  - `agent`
  - `plane`
  - `invoice_id`
  - `evidence[]`
  - `summary`
  - source references/citations
  - confidence
  - classification
- Keep `python scripts\test_evidence_contract.py` green when changing IQ
  prompts, stubs, or evidence tools.

### 4. Waypoint Recorder input contract

The waypoint-recorder currently accepts a flat result JSON. Assurance Orchestrator's write plan nests
the recommendation.

TODO:

- Document the canonical waypoint-recorder input contract.
- Add a converter from Assurance Orchestrator `write_plan.future_payloads[]` to that contract.
- Add tests for:
  - valid payload
  - missing invoice id
  - missing evidence
  - partial IQ lanes
  - no side effects in Assurance Orchestrator
  - exactly one waypoint-recorder write

## P2 cleanup and docs

These improve maintainability after the end-to-end path works.

### 1. Update PR and resource docs

TODO:

- Keep the PR body honest about what has and has not been exercised.
- Update `docs/CONTENT_UNDERSTANDING.md` after fresh-environment validation.
- Update `docs/FOUNDRY_KNOWLEDGE_BASE.md` after hosted FoundryIQ invocation validation.
- Link this TODO from `docs/AGENT_PIPELINE.md` once it stabilizes.

### 2. Better local diagnostics

TODO:

- Add a one-command local status report for:
  - Waypoint API
  - Assurance Orchestrator
  - WorkIQ
  - WebIQ
  - FoundryIQ
  - FabricIQ
  - waypoint-recorder
  - Content Understanding env values
- Include endpoint and status, but never print secrets.

### 3. CI/eval coverage

TODO:

- Add lightweight schema tests for evidence contracts.
- Add smoke evals for each IQ lane.
- Add a read-only Assurance Orchestrator eval with Content Understanding mocked.
- Add an waypoint-recorder write-contract test using a fake Waypoint client. **Done for
  Assurance Orchestrator preview normalization and one valid fake write.**

## Definition of done

The pipeline is end-to-end when all of these are true:

- Content Understanding succeeds for a real invoice PDF.
- WorkIQ, WebIQ, FoundryIQ, and FabricIQ each return a completed evidence
  contract for the same invoice.
- Assurance Orchestrator uses those evidence contracts to synthesize a judgement.
- Assurance Orchestrator does not write directly to Waypoint.
- Waypoint Recorder writes the Waypoint run/case/recommendation/draft exactly once.
- The Waypoint web app shows the resulting artifacts.
- The same flow works from the canvas and from the hosted/deployed path.
- The deploy workflow can configure a fresh environment without manual resource
  fixes.
