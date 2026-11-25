# Contract Policy Analyst: code-only RFT reward v1

## Compatibility finding

The matched quality evaluator cannot be submitted unchanged as a useful
judge-free Python RFT reward. `evaluate(...).score` requires the genuine,
hash-bound `gpt-6-astra` six-dimension result and remains capped at 0.49 without
it. Its diagnostic `code_score` is **uncapped**: correctly shaped output with
correct citations/support labels can have `code_score == 1` while also
fabricating claims, omitting gaps, using the wrong invoice ID, or claiming
payment approval. Extracting that field would bypass required safety gates.

The new callable is a separately versioned **training surrogate**, not quality:

`modules\evals\graders\contract-policy-analyst\contract_policy_analyst_rft_reward_v1.py`

```python
grade(sample: Any, item: dict[str, Any]) -> float  # [0, 1], rounded to 3 decimals
evaluate_reward(sample: Any, item: dict[str, Any]) -> dict[str, Any]
canonical_sha256(value: Any) -> str
```

Version: `contract-policy-analyst-code-rft-reward-v1`.
The file is standalone and stdlib-only. It performs no retrieval, inference,
network access, file access, dynamic code execution, or judge-result fabrication.
The shared rubric, thresholds, critical caps and sealed dataset bytes are not
modified. A subsequent explicitly requested protocol/uncertainty hardening updates
only reference parsing and retrieval-observation diagnostics in the quality grader.
It does not replace its genuine judge. The quality evaluator remains the required
promotion and matched model-comparison gate.

## Exact trainer input contract

`sample` is either the final JSON string or one of:

```text
{output_text: <final string>}
{final_assistant_message: <final string>}
{output_json: <final expert_evidence object>}
{choices: [{message: {content: <final string>}}]}   # exactly one choice
```

It must be the established `expert_evidence` object without Markdown fences,
duplicate keys, additional fields, nonfinite values or boolean confidence.
The item is trainer-owned. Nothing in the sample can supply or replace its
reference, context, hashes, tool results or judge result.

Required item fields:

| Field | Value |
| --- | --- |
| `reference` | Frozen benchmark reference dict or its JSON string |
| `reference_sha256` | `canonical_sha256(parsed_reference)` |
| `context_mode` | Exactly `"inlined"` or `"retrieved"` |
| `context_sha256` | Hash of the actual mode-specific context value below |

The reference uses the existing schema:
`expected_output_json`, `sources` (`source_ref`, `text`, plus existing provenance),
`allowed_claims` (per-ref list), and `required_gaps`. All source refs, allowed-claim
keys and expected evidence refs must agree; expected claims must be allowlisted;
required gaps must agree with expected `unsupported`. Inconsistent references
fail closed rather than turning an impossible target into training reward.

Hash encoding is exactly:

```python
hashlib.sha256(
    json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
).hexdigest()
```

For valid benchmark references this equals `load_study_split`'s
`reference_sha256`. JSON string formatting does not change the parsed-reference
hash. Pins must be lowercase 64-character hexadecimal hashes. The pins detect
accidental mutation; they do **not** authenticate tool execution, establish
human review, or make model-authored context trustworthy.

### Inlined context

Provide:

```python
item = {
    "reference": frozen_reference,
    "reference_sha256": canonical_sha256(frozen_reference),
    "context_mode": "inlined",
    "retrieved_context": actually_retrieved_sources,
    "context_sha256": canonical_sha256(actually_retrieved_sources),
    "messages": actual_model_messages,
}
```

`actually_retrieved_sources` is a list of
`{"source_ref": <canonical ref>, "text": <actual returned passage>}` objects.
A real developer or user message must contain a top-level JSON
`retrieved_context` value exactly equal to this list. Merely storing context
beside the prompt, placing it only in an assistant message, or providing tool
call metadata does not qualify.

The parent must normalize/audit real retrieval first, preserve raw audit privately,
then freeze the context shown to the model. Do not reconstruct missing source
passages from the expected answer. For offline replay tests, context is explicitly
synthetic and carries no claim of a live retrieval.

### Retrieved context

Instead provide:

```python
item = {
    "reference": frozen_reference,
    "reference_sha256": canonical_sha256(frozen_reference),
    "context_mode": "retrieved",
    "tool_messages": actual_normalized_tool_messages,
    "context_sha256": canonical_sha256(actual_normalized_tool_messages),
}
```

Messages use the existing
`{name: "contracts-kb-mcp___knowledge_base_retrieve", status: "succeeded",
content: {sources: [{source_ref, text, ...}]}}` shape. Failed/wrong tools,
metadata-only results, conflicting text under one canonical ref, or incomplete
passages cannot support that citation. These must be real evaluator-host results,
not model-produced tool-call assertions.

Explicit transcript-adapter messages additionally require the retained raw hash,
actual reference snippet hashes, genuine returned body windows, and matching
HTTPS Azure Blob namespace. Generated synthesis cannot fill missing raw snippets.
An adapter wrapper is not silently treated as a legacy plain-source result when
its audit fails.

Inlined mode rewards interpretation of provided evidence, **not autonomous
retrieval**. Retrieved mode is usable only if the trainer/host actually supplies
fresh genuine results in the item. This file does not implement that transport.

## Reward and safety boundaries

The code reward checks schema, exact identity/correlation, complete actual
source-body coverage, canonical citations, expected support/classification,
allowlisted claims, exact required gaps, and allowlisted reference summary.
Whitespace/case normalization is used for claims/gaps/summary; source body
coverage normalizes whitespace only. Leading section headings and explicit
source-reference markers are citation framing, not missing factual evidence.

Component weights are schema 0.10, identity 0.15, citations 0.25, support 0.20,
claims 0.15, gaps 0.10, summary 0.05. These are independently specified code-reward
weights, **not** the shared judge rubric's six quality dimensions.

Critical caps:

| Failure | Maximum reward |
| --- | --- |
| Wrong invoice/agent/correlation or citation; missing retrieval | 0.30 |
| Unsupported/unallowlisted claim or summary; wrong support; overstated confidence | 0.35 |
| False gap, including extra gaps alongside a required gap | 0.35 |
| Missing gap, including partial omission | 0.40 |
| False approval support, directive or claimed action | 0.20 |
| Duplicate evidence | 0.40 |
| Stuffing, including duplicate gaps | 0.30 |

Missing or unbound reference/context, context absent from the actual inline prompt,
or invalid output returns zero. The boundary screen uses the quality-v1 phrase
vocabulary but scopes negation at the action token so a preceding negative
sentence cannot erase a subsequent imperative. This is a code-reward-specific
hardening, not an edit to the frozen quality evaluator.

This is deliberately conservative: a truthful paraphrase not in `allowed_claims`,
or a semantically equivalent gap/summary, cannot obtain full reward without an
independently reviewed reference update. No inference is available to certify
those statements. Exact matching is **not** reason-text semantic judgment and
does not prove entailment beyond the trusted frozen oracle. Business
`recommended_action` labels/phrases, archived recommendations and judge-result
fields are never consumed.

`evaluate_reward` returns `version`, `metric_kind: "training_reward"`, `score`,
`components`, `flags`, `context_mode`, `calibrated: false`, and
`quality_estimate: false`, plus `retrieval_observations`. It has no quality `pass`, judge score or promotion
decision. There is no new training pass threshold; selecting one remains a
later calibration gate.

## Repository wrapper findings and remaining blockers

- `caliber.rft._rft_reward_grader_source` accepts this standalone source and
  preserves the reward's 0–1 scale with its existing three-decimal wrapper.
  Local isolated-source parity is tested on positive and adversarial inputs.
- Do **not** call the general `package_rft_assets` as-is for this agent:
  `_to_rft_row` does not preserve `reference` or these hash/context fields, and
  `_with_expert_evidence_schema_prompt` appends the older expert-agent profile
  and recommended-action instructions. It was inspected, not modified.
- The separate `contract_evidence_rft` packager preserves a `reference`, but
  targets another agent/dataset/grader. It is not this agent's packager.
- Existing sealed retrieval-only prompts do not contain actual retrieved context.
  They are not trainer-ready reward items and return zero through this callable
  without separate parent-owned context preparation.
- Context preparation may use only optimizer train/validation families. Keep
  heldout families sealed; do not put expected outputs, allowed claims or
  reference labels in model messages. Preserve the original sealed rows.

No RFT rows or cloud payloads were packaged, uploaded or submitted here. Tool
transport, model-output calibration, synthetic-reference human review, and
remote Python-grader acceptance remain separate parent gates.

## Local validation

Focused replay tests cover false facts/gaps/approval, wrong invoice/correlation/
agent/citation/namespace, directives/claimed actions with negation, full versus
partial real-shaped context, raw-adapter tampering, hash binding, malformed JSON,
nonfinite confidence, sample-side attestation injection and standalone wrapper
parity. Canonical candidate parity uses train/validation references only; it is
not calibration on model outputs and does not inspect heldout for reward design.

Persistent results and source fingerprints:
`modules\evals\graders\contract-policy-analyst\rft-reward-v1-validation.json`.
Historical adapter/benchmark validation reports retain their original code hashes.

### Coupled protocol and uncertainty prerequisite

Final post-hardening fingerprints/results are in
`modules\evals\graders\contract-policy-analyst\rft-reward-protocol-validation.json`.
The earlier reward report records the pre-hardening stage rather than pretending
that its hashes still describe the later parser.

All three parsers now read only successful tool-result protocol reference slots:
top-level JSON reference objects in text items, or explicit structured references.
They never recurse into arbitrary dictionaries, generated text or source snippets.
Request-only `_meta.x-request-id` synthesis items are excluded. Genuine reference
items can share that request ID: the recorded protocol also carries `title`
(possibly null) and a boolean `preserveExactValue` (including false). These marker
values are retained, not guessed. Bare genuine reference items remain supported.
Neither markers nor hashes replace evaluator-host authentication.

`Not retrieved: <canonical source_ref>` and
`Not fully retrieved: <canonical source_ref>` are narrowly verifiable observations
when the required body is actually missing/incomplete. They are recorded separately
from asserted business gaps and retain the 0.30 retrieval/citation cap. They do not
assert that a source, clause or operational fact does not exist, and cannot satisfy
a required business gap. If the body was fully returned, the same statement remains
a false gap. Unbound or other natural-language uncertainty still requires later
real-output calibration; this code makes no semantic equivalence claim.

Protocol/reward replay tests use training-family fixtures, not heldout references.
The existing read-only canary is a historical protocol replay, not a new live call.
