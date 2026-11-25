# Contract Policy Analyst: quality story and talk track

The story page lives at `/quality/contract-policy-analyst` (Spanish:
`/es/quality/contract-policy-analyst`). It is a presenter page: arrow keys,
PageUp/PageDown (clickers) or the step dots move one beat at a time, and
`?step=<name>` opens a beat directly (`orient`, `baseline`, `optimized`, `rft`,
`payoff`, `evidence`).

Every number on the page comes from the pipeline's `quality.json` (see
[the data contract](#data-contract)). Until real results land, the page shows
labelled fixture data, and the numbers below stay as `{{placeholders}}`. Fill
them from the page, not from memory.

## Ground rules

- Narration claims only what is on screen. If a number is not visible, do not
  say it.
- Screens stay clean: no red or failed rows, no error panels, no empty panels.
  Caveats live in the evidence beat, in neutral styling.
- Every arm uses the same real FoundryIQ retrieval tool
  (`contracts-kb-mcp___knowledge_base_retrieve`). Say so once, on the first
  beat, and do not imply the tool changed between arms.
- The baseline is an honest starter prompt, not a sabotaged one. Call it the
  "starter prompt", not a "bad prompt".
- Do not present the page while the fixture banner is visible.

## Talk track

### 1. Orient: the problem

On screen: the problem statement, the FoundryIQ tool card, and the three
empty rungs (Build, Optimize, Train).

> Caldova's finance team checks supplier invoices against contracts and
> policies. The Contract Policy Analyst reads the contract through FoundryIQ,
> finds the clause that applies, and explains what the evidence supports. It
> doesn't approve or reject anything; people do that. Every version you'll
> see uses the same FoundryIQ retrieval tool. The only things that change are
> the instructions and the model.

### 2. Build: the starter prompt

On screen: the baseline rung on `{{baseline.model}}`, its pass rate, cost per
1K reviews and median latency.

> We start with a short, honest starter prompt on `{{baseline.model}}`. It
> passes `{{baseline.pass_rate}}` of `{{cases}}` sealed final-test cases. It calls the
> retrieval tool, but it doesn't always cite the passage that settles the
> question. That's the gap the rubric picks up.

Baseline failure modes to name (only those visible in the evidence beat's
rubric table, lowest dimensions first):

- `{{baseline.lowest_dimension_1}}`: `{{baseline.lowest_dimension_1_score}}`
- `{{baseline.lowest_dimension_2}}`: `{{baseline.lowest_dimension_2_score}}`

### 3. Optimize: Foundry Agent Optimizer

On screen: the Optimize rung, its pass rate, and the change versus the
starter prompt.

> Next, Foundry Agent Optimizer rewrote the instructions and tool
> descriptions against the same rubric. Same model, same tool. Pass rate goes
> from `{{baseline.pass_rate}}` to `{{optimized.pass_rate}}`. The longer
> instructions cost more per review: `{{optimized.cost_per_1k}}` per 1K.

### 4. Train: RFT on MAI-2

On screen: the Train rung on the fine-tuned MAI-2 model, with the untuned
MAI-2 marker beside it.

> Now we move that behavior to a much cheaper model. Untuned, MAI-2 with the
> optimized prompt passes `{{mai2_base.pass_rate}}`. After reinforcement
> fine-tuning on `{{rft.train_rows}}` graded examples, it passes
> `{{mai2_rft.pass_rate}}`, still calling the same FoundryIQ tool.

### 5. Payoff: cost and latency

On screen: cost per 1K reviews and median latency for all three rungs, and
the savings line.

> Here's the payoff. Compared with the optimized frontier model, the tuned
> MAI-2 agent costs `{{payoff.cost_ratio}}` less per review, at
> `{{mai2_rft.cost_per_1k}}` per 1K reviews, and answers in
> `{{mai2_rft.latency_p50}}` at the median instead of
> `{{optimized.latency_p50}}`.

If the tuned model's pass rate is within the confidence interval shown in the
evidence beat, say "matches", not "beats".

### 6. Evidence: how we know

On screen: per-dimension rubric scores per arm, retrieval evidence per arm,
the benchmark/grader lineage and the caveats.

> Every number traces back to the evaluation run: the same `{{cases}}` cases,
> the same grader, and audited retrieval records showing each answer called
> FoundryIQ and cited sources it actually retrieved.

Only claim query variants if that row shows a value; it reads "not measured"
unless the pipeline captured real MCP dispatch variants.

## Data contract

The page reads `apps/waypoint/web/public/quality/contract-policy-analyst.quality.json`.
That file is a copy of the pipeline's
`modules/optimization/evidence/contract-policy-analyst/quality.json`, made by:

```powershell
cd apps/waypoint/web
npm run quality:sync
```

The sync script refuses to copy a file marked `"fixture": true`. When the real
file is absent, the page loads
`public/quality/fixtures/contract-policy-analyst.fixture.json` and shows a
"Fixture data" banner on every beat. Fixture values are illustrative and are
not results.

The shape extends the contract-evidence-analyst `quality.json` produced by
`modules/evals/src/caliber/contract_evidence_eval.py` (`build_quality`).
Confirmed with the eval session:

- **Arms (six):** `baseline-astra`, `baseline-astra62`, `optimized-astra`,
  `optimized-astra62`, `mai2-base`, `mai2-rft`. The Build and Optimize rungs read
  one frontier track (`?track=astra62`, the default, or `?track=astra`). The
  Train rung is always `mai2-rft`, and `mai2-base` is the untuned marker. The
  evidence tables show all six arms.
- **Headline split:** `final-test-v2` (target 120 cases, 10 fresh supplier
  source families). It is sealed offline and ingested into the knowledge base
  only after optimizer, RFT and config selection are frozen. Say "sealed final
  test cases". `headline_split` names it.
- **Regression split:** `study-heldout` (120 cases, 10 source families) is
  listed in `regression_splits`. The live knowledge base already returns
  passages from its source families (no prompt or gold use), so it is
  exposed-source regression evidence, never the headline. The page opens it with
  `?split=study-heldout` and labels it with a neutral banner. Rungs, payoff and
  evidence all switch to that split.
- `optimizer-validation` is the optimizer's validation split and is never shown
  as a result.
- `benchmark.splits.<id>.{rows, source_families}` feeds the evidence lineage
  line.
- **Rubric dimensions:** `grounded_reasoning`, `support_direction`,
  `evidence_gaps`, `retrieval_and_citations`, `evidence_only_boundary`,
  `output_contract`.

The page uses, per arm and for `headline_split`:

| Field | Used for |
| --- | --- |
| `pass_rate`, `mean_score`, `unique_cases`, `runs` | Rung bars |
| `cost_usd_per_1k_lines`, `latency_ms.p50`, `latency_ms.p95` | Cost and latency |
| `rubric_dimensions.<id>.{label, mean_score}` | Rubric table (`mean_score` is normalized score/5 in [0, 1]; `raw_score_scale` is informational) |
| `critical_failures` (`{category: count}`) | Safety table: total across categories; `{}` is a measured zero, absent is "not measured" |
| `tokens_mean.{input_tokens, output_tokens, reasoning_tokens}` | Token usage per review |
| `retrieval.responses_with_tool_call_rate` | Answers that called FoundryIQ |
| `retrieval.tool_calls_mean`, `retrieval.tool_call_latency_ms_p50` | Retrieval call count and latency |
| `retrieval.tool_failures_reported` | Retrieval failures the tool reported |
| `retrieval.audit_complete_rate` | Answers with a complete evidence payload |
| `retrieval.citations_grounded_rate` | Citations grounded in retrieved sources (after lossless normalization) |
| `retrieval.query_variants_mean` | Only when real MCP dispatch variants are captured; otherwise `null` |
| top-level `comparisons[]` (`a`, `b`, `split`, `mean_difference`, `ci95`) | Paired change |

The eval session confirmed it emits these exact `retrieval.*` names. Every arm
is scored by the same frozen six-dimension gpt-6-astra judge. Unknown values
must stay `null`, never zero.

Missing optional fields render as "not measured", never as zero. An evidence row
that no arm measured is hidden, so the screen never shows a row of blanks. The TypeScript
types and adapter live in `apps/waypoint/web/lib/analystQuality.ts`.
