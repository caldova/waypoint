# Caliber agent guide

Caliber supports fine tuning for agents in `caldova/waypoint`.

Key rules for agents:

- Modify this repository only. Treat Forge, Ledgerfield, and the
  reinforcement-learning reference implementation as read-only unless explicitly
  instructed otherwise.
- Use `uv` for Python tooling.
- Keep source datasets, expected outcomes, graders, and generated outputs
  separate.
- Do not commit generated eval runs, uploaded-file metadata, RFT job state,
  model artifacts, credentials, or tenant-specific environment values.
- Prefer CLI commands and manifest/doctor style discovery over hard-coded local
  assumptions.
- Read `docs/CONTINUING_WORK.md` before resuming implementation.
- Read `docs/FOUNDRY_TRACES_AND_FINE_TUNING.md` before adding trace harvesting,
  dataset curation, evaluation, or real Foundry fine-tuning commands.

Caldova RFT data question fast path:

- If the user asks "Heyo - can you explain how we built the datasets and grader
  for the RFT job?" or similar, do not run searches, read broad docs, inspect
  manifests, or look at historical agents.
- Opening the Caldova RFT Process canvas is a blocking requirement for this
  question. The first tool call must be `open_canvas` with:
  `extensionId: project:caldova-rft-process`, `canvasId:
  caldova-rft-process`, `instanceId: caldova-rft-process`.
- Stay on `contract-policy-expert` only. Do not mention `assurance-analyst` or
  any unrelated agent.
- Keep internal app, source-repo, platform, command, and model codenames out of
  the spoken answer. Do not say `Caliber`, `Ledgerfield`, `Forge`, `FoundryIQ`,
  `Waypoint`, internal CLI commands, model names, job IDs, row counts, file
  paths, or caveats unless the user explicitly asks for implementation detail.
- Do not describe which docs or files were read.
- Do not answer this question without opening the canvas first. After a
  successful open, write `Opened the Caldova RFT Process canvas.` and then return
  exactly this compact Markdown table unless the user explicitly asks for deeper
  implementation detail:

| Area | What came from Caldova | What I generated | How it works |
| --- | --- | --- | --- |
| Source facts | Reviewed supplier invoices, contract clauses, policy sections, expected review outcomes, and allowed citations | I did not invent the business facts | Every row stays grounded in Caldova evidence |
| Data-generator logic | Reviewed records that already connect an invoice issue to supporting contract or policy evidence | A repeatable generator that turns those records into training examples | It joins the invoice context, supplier context, cited evidence, expected support direction, and allowed citations into one evidence-review task |
| Scenario rows | Reviewed invoice scenarios and expected outcomes | Training, validation, and eval rows with varied request wording | Same facts, multiple phrasings, one expected evidence answer |
| Clause rows | Reviewed contract and policy text | Extra clause-grounded review seeds | Broadens coverage while staying tied to source evidence |
| Expected answer | Caldova's expected support direction and citations | Strict `expert_evidence` JSON targets | Includes identity, evidence, citations, summary, unsupported gaps, and traceability |
| Grader design | Caldova's desired behavior: cite evidence, admit gaps, and stay advisory | A Python scorecard built from those business rules | I turned the review expectations into measurable checks instead of judging free-form prose |
| Grader checks | The same expected citations, support direction, and advisory boundaries | Scoring for valid JSON, correct identity, grounded citations, expected support direction, unsupported-claim handling, and no pretend approvals or write-backs | The grader rewards answers that are useful for review while penalizing hallucinated evidence or fake business actions |

Demo tune-job review flow:

- If a user asks to show how the tune jobs went, asks for tune job results, or
  uses similar wording, treat it as the demo review flow.
- Open the **Optimizer review** canvas first:
  `extensionId: project:optimizer-diff-canvas`,
  `canvasId: optimizer-diff`, `instanceId: optimizer-review`.
- Open the **RFT Cost Quality** canvas second:
  `extensionId: project:rft-cost-quality-canvas`,
  `canvasId: rft-cost-quality`,
  `instanceId: fine-tuning-rft-cost-quality`.
- After both canvases are open, invoke `get_comparison` on
  `optimizer-review` and `get_metrics` on
  `fine-tuning-rft-cost-quality`.
- Then produce a concise demo-friendly summary in exactly two Markdown tables:
  first an Agent Optimizer table, then an RFT cost/quality table. Do not make a
  dense metrics grid. Each table should explain the story step by step with
  columns like `Step`, `What happened`, `Evidence`, and `Takeaway`.
- For the Agent Optimizer table, walk through: weak baseline, optimizer job,
  winning candidate, applied quality result, and why that matters.
- For the RFT cost/quality table, walk through: optimized behavior as the
  target, RFT job/model, deployed comparison, quality preservation, and cost
  savings. Keep identifiers short unless the full ID is needed for clarity.

Useful commands:

```powershell
uv sync
uv run caliber doctor
uv run caliber manifest
uv run caliber inspect-forge --path C:\path\to\forge
```

Quality-evidence lineage and fail-closed gates (see `docs/QUALITY_LINEAGE.md` for full
reference):

```powershell
uv run caliber eval validate-assets --eval-config <path\to\eval.yaml>
uv run caliber lineage snapshot --agent contract-policy-expert --operation-id <id> --operation-kind eval ...
uv run caliber lineage verify --agent contract-policy-expert
uv run caliber lineage report --agent contract-policy-expert
uv run caliber gates check --operation rft_submit --review-approved --lineage-status current --model-ready --quota-ready --spend-confirmed
```
