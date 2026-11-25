# Contract Policy Analyst: offline retrieval benchmark v1

> **Current expanded study:** the coordinator subsequently authorized new
> fictional source documents. The original grounded subsets and empty globally
> pristine partition below remain preserved. The new **48-family study** has
> **336 optimizer train / 120 optimizer validation / 120 study-heldout** cases.
> See [Expanded fictional-authority study](#expanded-fictional-authority-study)
> for the additive corpus, seals, canaries, and exact parent APIs.

> **Replacement headline test:** `final-test-v2` now seals **120 CPA2 cases /
> 10 new source families / 260 documents**, entirely offline. The parent reports
> incidental CPA1 study-heldout source exposure in training captures; that old
> partition is now **exposed-source regression**, not the headline test. Its
> original files and labels are unchanged. CPA2 remains **sealed-uningested**
> until both optimizer candidate selection and RFT/checkpoint selection freeze.

These are independent preparation assets, not a renamed expert training set or
evidence-analyst runtime. No model, agent, KB, optimizer, RFT job, or cloud state
was changed. All generated labels are synthetic `pending_human_review`.

## Fresh final-test-v2: offline release gate

Build only, with no ingestion, retrieval, inference, judge or training calls:

```powershell
uv run --project modules\evals python -m caliber.contract_policy_analyst_benchmark --repo . --final-test-v2
```

`build_final_test_v2(repo=Path(...))` uses the fixed seed
`CPA2-offline-seal-2026-11-25`. CPA2 names, supplier/service/line identities,
commercial parameters, source bytes and numeric business-fact vectors are
distinct from CPA1. Calculation primitives and neutral constants such as one
fixed service item intentionally recur; this is not global/pretraining
pristineness. New fictional clauses are authored authority, not approved policies.

Each family has all 12 scenario archetypes: established calculation, amount
variance, tier threshold boundary, tier basis variance, capped cost/credit
variance, valid waiver, absent waiver, single attestation, outside date window,
quality-status conflict, wrong service and wrong supplier. The supplier-only
trap retains the correct line/service IDs. Coverage is 30 approval-direction,
40 recovery-direction, 40 review-direction and 10 escalation-direction cases;
these are evidence directions, never executed business decisions.

- Corpus: `modules\corpus\data\contract-policy-analyst\final-test-v2\`
  contains 10 SOWs, 10 policies, 120 records and 120 supplier invoices in the four
  `source-markdown` folders. Scenario labels, review lists and canary definitions
  stay outside those folders.
- Requests:
  `modules\evals\datasets\contract-policy-analyst\final-test-v2\final-test-v2.jsonl`.
- Evaluator-only references: the same dataset root's
  `references\final-test-v2.jsonl`, joined by request `reference_id` to reference `id`.
- `seal-manifest.json` exposes `rows`, `source_families`, `status`,
  all prompt/reference/source hashes, catalog pin and prior CPA1 manifest pin.
  `source-manifest.json` pins all 260 source bytes. `review-list.jsonl` lists all
  120 pending reviews; `leakage-audit.json` discloses prior source exposure.
- `load_study_split(repo=..., split="final-test-v2")` returns the unchanged
  `id/task/messages/reference/ground_truth/metadata` contract with task/reference
  hashes. It verifies the seal, all source bytes and inventory. Missing, changed,
  extra or unsealed sources fail closed. `study_optimizer_rows` rejects this split.
- Future source refs use `knowledge/contracts/policy-analyst-v2/`; that is a
  **planned** blob namespace, not evidence of uploaded or indexed documents.
- New canaries are offline definitions in the new corpus root's
  `retrieval-canaries.jsonl`. **Do not run them or upload/index CPA2 until BOTH
  selection processes freeze.** No final-test prompts/gold/labels may enter either
  selection process. Status is a builder declaration, not remote inspection.
- Original CPA1 retry canaries remain exactly
  `modules\corpus\data\contract-policy-analyst\v1\retrieval-canaries.jsonl`.

The deterministic builder refuses changed or extra artifacts across both roots
before writing. Focused tests cover CPA1 identity/byte/numeric overlap, renamed
numeric facts, supplier-only distractors, source-backed oracle consistency,
unchanged v1 artifacts, unsealed sources and loader tampering. They do not grade
model outputs or perform final-test calibration.

## Source audit and limits

The current corpus has **15 fictional supplier contracts and 3 company policies**.
All 18 whole-document families already appear in historical expert assets.
Historical `cmo-*` supplier paths correspond to current `sup-*` paths; the builder
verifies that historical cited passage text matches the actual corpus passage.
An alias, another section, another invoice ID, or another prompt style does not
create an independent source family.

The old generator joins scenario outcomes to invoices and suppliers, embeds the
answer-bearing contract sections, copies `recommended_action` into claims and
summary, and exposes outcome fields, risk examples, and outcome-bearing line
descriptions. The existing prompt-preparation utility removes many label keys
but retains embedded evidence and outcome-bearing descriptions. It is therefore
not sufficient for this tool-enabled benchmark.

The existing data audit checks identity and normalized-prompt leakage; this
benchmark additionally audits whole document families across splits and all
historical expert JSONL assets, including evidence-only v3 and challenge rows.
The frozen v1/v2/v3 expert graders were inspected, not edited. Their business-label
and recommended-action scoring is deliberately not reused. The evidence-analyst
grader and rubric were inspected; their different schema, evidence-role
classifications, and synthetic embedded sources are not the Analyst's contract.
Only the existing Markdown section/source-ref utility and JSONL reader are reused.

### Prepared sizes

| Partition | Rows | Meaning |
| --- | ---: | --- |
| `train` | 10 | One cleaned source scenario per supplier 001–010; preparation candidates, not ready-to-submit RFT |
| `validation` | 2 | One cleaned source scenario per supplier 011–012 |
| `historical-regression` | 24 | All historical eval rows preserved; **3 invoice lines × 8 styles**, not 24 independent tasks |
| `new-grounded-candidates` | 5 | Independently authored document questions: marginal volume discount, serialized-count basis, rush-order authorization, all-unit regional price tier, authority-response milestone |
| `sealed-heldout` | **0** | Blocked; no unexposed document families |

The five new questions are supported by real committed corpus passages, not
invented retrieval documents. They have distinct substantive questions rather
than renamed templates. Their document families are nevertheless contaminated:
Aster Ridge and HelioPack were exposed in training; Evergreen, Atlas, and Signal
Ridge were exposed in historical evaluation. Shared policy families also
contaminate train/validation and regression. `leakage-audit.json` reports exact
families and exposure files. No pristine, independent, or 150-case claim is made.

**Live KB retrievability remains unverified.** The local files prove source
existence, not successful ingestion. There is no verified local KB inventory or
successful retrieval transcript in these assets. Operational records such as
purchase orders, approvals, release certificates, and run logs are referenced by
the invoice sources but their contents are not corpus documents. They are not
fabricated here.

To unlock a meaningful sealed evaluation, provide genuinely new fictional
contract/policy families with reviewed operational records, ingest them into the
same read-only KB, retain exact retrieval identifiers and successful transcripts,
then author and human-review new questions and references. Audit against every
historical/training/optimizer/eval source before sealing. Extending the current
builder requires explicit source/spec review: it rejects changed inventories,
missing sections, passage drift, unknown prompt styles, and output drift.

## Files and repeatable build

Under `modules\evals\`:

- `src\caliber\contract_policy_analyst_benchmark.py`
- `tests\test_contract_policy_analyst_benchmark.py`
- `datasets\contract-policy-analyst\case-specs.json`: independently authored
  neutral descriptions, source-grounded claims, gaps, and new document questions.
- `datasets\contract-policy-analyst\<partition>.jsonl`: **model requests only**,
  retrieval tool expectations, reference IDs, and provenance.
- `datasets\contract-policy-analyst\references\<partition>.jsonl`: evaluator-only
  candidate answers, exact corpus passages and hashes, and untouched historical
  labels/prompts under `historical_reference`.
- `datasets\contract-policy-analyst\source-inventory.json`,
  `leakage-audit.json`, `validation-report.json`: repeatable source/build evidence.
- `datasets\contract-policy-analyst\local-validation.json`: executed local checks,
  with explicit distinction between fixtures and live semantic evaluation.
- `graders\contract-policy-analyst\quality-rubric.json`
- `graders\contract-policy-analyst\contract_policy_analyst_grader.py`

From the repository root, entirely offline:

```powershell
uv run --project modules\evals python -m caliber.contract_policy_analyst_benchmark --repo .
uv run --project modules\evals pytest modules\evals\tests\test_contract_policy_analyst_benchmark.py -q -p no:cacheprovider
uv run --project modules\evals ruff check modules\evals\src\caliber\contract_policy_analyst_benchmark.py modules\evals\tests\test_contract_policy_analyst_benchmark.py modules\evals\graders\contract-policy-analyst\contract_policy_analyst_grader.py
```

An identical build is a no-op. All prospective writes are checked first; existing
different bytes cause failure before any output is written. Output scope is
restricted to this new dataset directory. No timestamp or random case generation
is involved. Source hashes include the actual corpus scenario/invoice/supplier
artifacts, the old generator/audit/preparation modules, frozen expert graders,
and all inspected historical expert JSONL.

## Model request and expected output boundary

Send only `messages` to the tool-enabled agent. Never include `metadata`,
`reference_id`, the candidate answer, corpus snapshots, or archived originals in
the model request. Every user request explicitly asks for retrieval with
`contracts-kb-mcp___knowledge_base_retrieve`. No supporting passage, allowed
citation, expected outcome, scenario ID, risk example, or action hint is embedded.
Outcome-bearing descriptions are manually replaced with neutral charge types.
Historical invoice IDs and non-outcome line facts remain for traceable regression;
supplier retrieval aliases map to the actual current corpus.

The response uses the **established expert schema**:
`agent`, `plane`, `invoice_id`, `output_type`, `evidence`, `unsupported`, `summary`,
`correlation`. `agent=contract-policy-analyst`, `plane=foundryiq`,
`output_type=expert_evidence`. Confidentiality classifications are
`standard|confidential|ip_sensitive|restricted`, not evidence-role labels.
`supports` describes evidence direction, never a payment or recovery action.

The current expected directions are independently authored `review` candidates:
the cleaned prompt does not establish operational compliance/noncompliance.
Original historical `recover`/`escalate` labels and directives are preserved
separately, not quietly relabeled. Missing records are **unverified**, not asserted
never to exist. A document-question correlation ID is explicitly not a fabricated
invoice. Confidence 0.86 is an example, not a rewarded target.

To obtain expected outputs, join prompt `reference_id` to the corresponding
reference row `id`; its `expected_output_json` is an offline candidate. Obtain
reviewed gold from domain reviewers after real KB retrieval. Do not obtain gold
by copying historical dispositions, agent outputs, or training-derived rubrics.

## Identical reason-text judge and code caps

`quality-rubric.json` is independently authored and intended for **gpt-6-astra**
as the same blinded judge across every compared model. Do not regenerate or tune
it per model. It grades grounded reasoning, evidence direction, necessary gaps,
retrieval/citations, evidence-only boundaries, and the established output contract.
Every dimension requires a concrete reason. No `recommended_action` lexical
reward, historical support-label reward, or training-output similarity is used.

The stdlib-only code grader accepts `grade(sample, item)` and provides
`evaluate(sample, item)` for flags, code score, judge score, and reason text.
It rejects malformed/duplicate-key/non-finite JSON, wrong identities,
wrong/missing supplier sections, missing retrieval, duplicate evidence, invalid
confidence/classification, directives, claimed actions, and stuffing. Critical
caps are below the 0.8 pass threshold, including unsupported facts, false/missed
gaps and semantic judge failures.

Regex is **not** an entailment or gap-correctness proof. Unknown paraphrases and
arbitrary unsupported facts cannot pass without a bound semantic result.
Even canonical references with valid replayed retrieval are capped at **0.49**
without a verified judge result. A trusted item-side judge can assess paraphrases;
the host is responsible for the authenticity of that result. A weak or dishonest
judge can still miss semantic failures, so local tests do not prove live quality.

### Evaluator adapter contract

The caller supplies an evaluator-owned `item`:

```python
item = {
    "reference": reference_row,
    "tool_messages": [
        {
            "name": "contracts-kb-mcp___knowledge_base_retrieve",
            "status": "succeeded",
            "content": {
                "sources": [
                    {"source_ref": exact_retrieved_ref, "text": actual_retrieved_passage}
                ]
            },
        }
    ],
    "rubric_sha256": sha256_of_quality_rubric_file_bytes,
    "judge_result": {
        "judge_model": "gpt-6-astra",
        "output_sha256": grader.output_sha256(sample),
        "retrieval_sha256": grader.retrieval_sha256(item_tool_messages),
        "rubric_sha256": sha256_of_quality_rubric_file_bytes,
        "dimensions": [{"id": dimension_id, "score": integer_1_to_5, "reason": reason_text}],
        "critical_flags": [],
    },
}
```

Include all six dimensions once. The host attaches the hashes **after** obtaining
the real judge result; the model must not provide them. Tool content may also be a
JSON string in the same shape. The current code requires the full pinned source
section to appear in the normalized retrieved passage. KB citation format or
chunking differences need a reviewed, lossless adapter; never fabricate transcript
content from references to make a rollout pass. Successful tool names alone do
not count. A failed call or an answer's assertion that it retrieved is not proof.
Hashes bind data consistency; they are not cryptographic proof of tool execution
or judge authenticity. Authenticity is an evaluator-host responsibility.

Local tests use explicit **synthetic judge fixtures and replayed corpus
passages**, not a live judge or KB. They cover positive candidates, unsupported
facts, false gaps, wrong IDs and sections, false support, directives/claimed
actions despite disclaimers, duplicate/extra fields, malformed confidence,
missing/failed/conflicting retrieval, stale judge hashes, missing reason text,
paraphrases, recommendation poisoning, and repeatable fail-closed builds.

## Expanded fictional-authority study

### Concrete corpus findings

The authoritative existing sources contain 15 suppliers, 15 canonical invoices,
15 scenario seeds, and 18 app-seed invoice cases. The three historical regression
invoice lines were not the whole corpus. There are no additional authoritative
supplier contract families beyond the original 15 contracts and 3 policies.
The app-seed extensions reference those same source families, not new contracts.

The existing `ledgerfield.contracts_kb_upload` collects contract Markdown and
optionally policies; operational/invoice documents are not in its default
collection. Its original sync deletes undesired blobs under the selected prefix.
**Do not use that default destructive sync for this addition.** Parent owns an
explicit additive ingestion adapter, preserving original defaults and using the
new data root and four folders below. No ingestion was run by this builder.

### Newly authored sources and source authority

Source root: `modules\corpus\data\contract-policy-analyst\v1`.

| Upload folder | Documents | Meaning |
| --- | ---: | --- |
| `contracts\source-markdown\` | 48 | New supplier SOWs, six substantive commercial rules each |
| `policies\source-markdown\` | 48 | Family-scoped evidence escalation/exception policies |
| `operational\source-markdown\` | 576 | Real local fictional records, including omissions and wrong-item records |
| `invoices\source-markdown\` | 576 | One distinct fictional invoice line per document |

These are **new fictional commercial authority**, not clauses extracted from
reviewed customer contracts. Every source and candidate is
`synthetic/pending_human_review`. `domain-catalog.json` sits one directory above
the upload root and records authorship and 96 domain-specific rule archetypes.
It is not retrieval evidence. Original corpus sources are untouched.

The 12 service domains cover solid dose, sterile filling, serialization, API
supply, GMP testing, clinical supply, cold logistics, biologic capacity, device
assembly, sterilization, process development and regulatory services. Each has
eight different rule archetypes; four supplier variants rotate six into each
SOW. Variants change prerequisite graphs (strict conjunction, signed pre-service
waiver, or dual attestation), all-unit versus incremental tier basis, inclusive
versus exclusive windows, allowance percentages, rates, credits and overage
bases. This materializes 288 supplier-specific clause/scenario families.

Each family has 12 distinct invoice conditions, not 12 wording variants:
six established conditions, two amount/date-window violations, two missing
prerequisite records, one wrong-service/line distractor and one sponsor/provider
acceptance conflict. The wrong-item document actually exists, and both identities
are explicit. Missing fields are omitted from a real record rather than supplied
as imaginary documents. Domain-specific status conflicts include lot rejection,
decommissioned serials, invalidated reports and unreceived filings.

Expected directions are derived from the authored calculations, prerequisites,
actual invoice amount and actual operational fields—not copied from a behavior
label. Arithmetic uses Decimal and final-cent rounding. The calculation
primitives recur across families: this is source-family independence, **not**
an assertion of disjoint abstract mathematics or 576 unrelated recipe types.

### Allocation, seal and exposure

The allocation function is fixed before source generation:

| Split | Supplier/source families | Clause/scenario families | Cases | Primary directions |
| --- | ---: | ---: | ---: | --- |
| `optimizer-train` | 28 | 168 | 336 | 168 approve, 56 recover, 84 review, 28 escalate |
| `optimizer-validation` | 10 | 60 | 120 | 60 approve, 20 recover, 30 review, 10 escalate |
| `study-heldout` | 10 | 60 | 120 | 60 approve, 20 recover, 30 review, 10 escalate |

Whole supplier, SOW, policy, record, invoice, scenario-family, line identity and
normalized prompt sets have zero cross-split overlap. Family identifiers are
`CPA1-F001` through `CPA1-F048`; opaque line ordering prevents output labels
appearing in filenames. `partition-plan.json` records the exact allocation.

The initial retrieval baseline reset from `5aac278` is **parent-reported**, not
executed or verified by this offline builder. Historical original-document
exposure is recorded separately. The expanded heldout is **study-local**, not
globally pristine, pretraining-independent or human-approved.
`datasets\contract-policy-analyst\sealed-heldout.jsonl` stays empty.

`expanded-v1\seal-manifest.json` pins the family partition, heldout prompt and
reference bytes, and every heldout source document hash. Only optimizer train
and validation rows may enter optimizer data. The existing KB tool may retrieve
all newly ingested documents; inspect actual optimizer transcripts and exclude
any heldout family whose passage was returned during training/validation.
Ingestion itself is not optimizer exposure. Canary answers and heldout gold must
not enter optimizer context.

### Ingestion manifests and retrieval canaries

Parent upload configuration:

- Container: `knowledge`.
- Additive blob prefix: `contracts/policy-analyst-v1`.
- Tool unchanged: `contracts-kb-mcp___knowledge_base_retrieve`.
- Real toolbox binding unchanged: `contract-toolbox`.
- Source refs: `knowledge/contracts/policy-analyst-v1/<unique-basename>.md#<section>`.

`source-manifest.json` maps each local path to its unique remote `blob_name`,
container, family, partition, SHA-256 and pending review status. The entire
source tree has 1,248 uploadable Markdown documents. Never upload the manifests,
`cases-index.jsonl`, `review-list.jsonl`, `retrieval-canaries.jsonl`, domain catalog,
benchmark references, README, or expected answers.

`retrieval-canaries.jsonl` contains 48 exact query/expected-document pairs. For
example:

```text
CPA1-F001 Fictional Solid Dose Production Partner 001 SOW Released tablet production evidence policy
```

Expected documents:
`cpa1-f001-solid-dose-sow.md`, `cpa1-f001-evidence-policy.md`.
Expected references:

```text
knowledge/contracts/policy-analyst-v1/cpa1-f001-solid-dose-sow.md#1-commercial-rule-released-tablets
knowledge/contracts/policy-analyst-v1/cpa1-f001-evidence-policy.md#1-evidence-escalation
```

The SOW anchor is `For released tablet production, billability requires`.
An invoice/record canary is:

```text
CPA1-F001-INV001 invoice line CPA1-F001-L001 operational observations
```

Expected invoice: `cpa1-f001-inv001.md`; record:
`cpa1-f001-l001-observations.md`. Each record's identity must be checked against
the retrieved invoice: some are intentionally for another line.
Parent has reported original Aster Ridge SOW/policy retrieval success; that does
not verify any new CPA1 document. New canary verification remains parent-owned.

The manifest carries blob names and section refs, but actual retrieval may return
URLs or chunk citation identifiers. Build a lossless adapter that retains raw
citations and resolves them to these pinned document/section refs. Never substitute
reference text for missing tool output. The current code grader needs the full
pinned source section in the normalized real retrieved passage.

### Exact build and data APIs for parent integration

Builder filename:
`modules\evals\src\caliber\contract_policy_analyst_benchmark.py`.

```powershell
uv run --project modules\evals python -m caliber.contract_policy_analyst_benchmark --repo . --expanded
```

Public Python APIs, all offline:

```python
build_expanded_study(*, repo: Path) -> dict
load_study_split(*, repo: Path, split: str) -> list[dict]
study_optimizer_rows(*, repo: Path, split: str) -> list[dict]
foundry_reason_evaluator_body(*, repo: Path) -> dict
derive_study_expectation(*, rule: list, parameters: dict, facts: dict, invoice: dict) -> dict
```

The split files are exactly:

- `modules\evals\datasets\contract-policy-analyst\expanded-v1\optimizer-train.jsonl`
- `modules\evals\datasets\contract-policy-analyst\expanded-v1\optimizer-validation.jsonl`
- `modules\evals\datasets\contract-policy-analyst\expanded-v1\study-heldout.jsonl`
- Evaluator-only references: the same filenames under `expanded-v1\references\`.

Raw prompt row:

```text
id: string
messages: [{role: developer|user, content: string}]
expected_tools: [contracts-kb-mcp___knowledge_base_retrieve]
reference_id: string
metadata: {split, source_family, supplier_id, scenario_family, invoice_line_id,
           document_names, domain, synthetic, review_status, authority,
           global_pristine:false, kb_ingestion_verified:false,
           baseline_reset_ref, baseline_reset_verification}
```

Join `reference_id` to reference `id`. Reference row:

```text
id, version, review_status, synthetic, label_source,
expected_output_json: established expert_evidence object,
allowed_claims: {source_ref: [canonical neutral claim]},
required_gaps: [string],
sources: [{document, section, source_ref, text, classification, source_family,
           local_path, section_sha256, blob_name, container}],
historical_reference: null,
ground_truth: {primary_supports, support_by_source, required_gaps,
               acceptable_citations, source_family, scenario_family,
               authored_rule, observed_facts, invoice_facts, derived_expectation}
```

`load_study_split` verifies prompt/reference artifact hashes and returns:
`id`, `task`, `messages`, `reference`, `ground_truth` (JSON string), `source_family`,
`scenario_family`, `split`, `metadata`, `task_sha256`, `reference_sha256`.
`task` is exactly developer content plus two newlines plus user content. Use this
same task byte string across all model arms and matched attempts. It contains
no source passages, prices, supporting record facts, or expected answers.
The remaining fields are evaluator/runner metadata, never hosted model input.

`study_optimizer_rows` returns exactly `{id, query:task, ground_truth:reference_json}`
for train/validation and **rejects study-heldout**. Ground truth remains in the
optimizer evaluator lane, not the agent query. No hidden sampling or retries are
implemented here; parent owns `caliber.contract_policy_analyst_eval` and matched
run/statistical recording.

### Exact grader and native Foundry reason-text evaluator contract

Grader filename:
`modules\evals\graders\contract-policy-analyst\contract_policy_analyst_grader.py`.
Load using `importlib.util.spec_from_file_location` because the directory name
contains hyphens; ordinary dotted package import is not appropriate.

```python
grade(sample: str | dict, item: dict) -> float
evaluate(sample: str | dict, item: dict) -> dict
output_sha256(sample: str | dict) -> str
retrieval_sha256(tool_messages: list) -> str
```

`sample` is text or `{output_text: str}` / `{output_json: object}`.
`item` supplies trusted `reference`, normalized genuine `tool_messages`,
`rubric_sha256`, and optional authenticated host-side `judge_result`, as described
above. `evaluate` returns exactly:

```text
version, score, code_score, judge_score, flags, pass, judge_reasons
```

`judge_score` is null without a verified judge; `judge_reasons` is the six
`{id,score,reason}` dimension results. `score` combines code, semantic score and
critical caps. Canonical examples without the semantic judge score no higher
than 0.49; absent retrieval also caps at 0.30. A `code_score` alone is not accuracy.

Independent rubric filename:
`modules\evals\graders\contract-policy-analyst\quality-rubric.json`.
It is unchanged across the original and expanded study. Top-level fields include
`version`, `type:rubric`, `authorship`, `review_status`,
`intended_judge_model:gpt-6-astra`, `pass_threshold:0.8`, `score_scale`,
`judge_instructions`, and six `{id,description,weight,always_applicable}` dimensions.

Use `foundry_reason_evaluator_body(repo=...)` to convert it into the repository's
established native custom reason-text shape. The payload has
`evaluator_type:custom`, supported turn/conversation levels and
`definition.type:rubric`. It copies the six independently authored dimensions,
prepends the identical judge instructions, requires a model deployment init
parameter, and supplies a primary increasing 0–1
`contract_policy_analyst_quality` metric. Its data schema requires evaluator-only
`query`, `response`, `ground_truth`, and `retrieval_context` strings.

Parent may register this body under a new stable evaluator name such as
`contract-policy-analyst-independent-quality-v1` using the existing Foundry
evaluator registration surface, **then bind init model to the same
gpt-6-astra deployment for every arm**. Registration/inference is not performed
here. Record the rubric file SHA-256 and native payload SHA-256 separately.
Pass actual retrieval transcripts as `retrieval_context` and confirm they reach
the judge; do not assume optimizer reflection automatically receives ground truth
or tool spans.

The host normalizes the real per-dimension integer grades and reason text into
`item.judge_result.dimensions`, carries real critical flags, and attaches output,
retrieval and **rubric-file** hashes. If Foundry only exposes an aggregate metric
and prose reason, retain those as separate native results; do not fabricate six
dimension grades to satisfy the code grader. Local combined grading remains
fail-closed until the necessary semantic result is genuinely available.

### Local validation and pending human review

`expanded-v1\validation-report.json` contains coverage, source counts, catalog and
corpus-manifest hashes; `expanded-v1\local-validation.json` records executed tests.
`v1\review-list.jsonl` lists all 576 candidates and required domain, arithmetic,
record-identity, gap, support and citation review. `source-manifest.json` carries
pending review status for all 1,248 source documents.

Review-pending labels are neither approved gold nor policy authority outside this
fictional study. Local fixture scores do not establish actual model quality,
live retrievability, or optimizer improvement. Parent still owns additive
ingestion, actual canaries, hosted baseline/optimizer calls, the original expert
smoke and paired statistical analysis.
