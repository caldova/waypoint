# Lossless real-tool transcript adapter

This is a pre-freeze v1 grader integration change, not a benchmark, rubric,
threshold, runtime, or cloud change. Sealed dataset and corpus bytes are untouched.

## Files and public interface

Adapter:
`modules\evals\graders\contract-policy-analyst\contract_policy_analyst_transcript.py`.

Grader:
`modules\evals\graders\contract-policy-analyst\contract_policy_analyst_grader.py`.

Load each with `importlib.util.spec_from_file_location`; the directory contains
hyphens. Both modules are stdlib-only. No network calls or other imports from
the runtime/eval runner are required.

```python
normalize_tool_messages(
    tool_messages: list[dict] | dict,
    *,
    reference: dict,
    allowed_hosts: set[str] | None = None,
) -> dict

audit_adapter(
    tool_messages: list[dict] | dict,
    *,
    reference: dict,
    allowed_hosts: set[str] | None = None,
) -> dict
```

Input may be:

- An actual `{ok, content, structured_content}` result.
- A list of `{name: <actual tool name>, result: <actual result>}` envelopes.
- A read-only canary snapshot `{records: [{query, result}, ...]}`.

Raw-result and canary callers explicitly assert trusted retrieval origin.
Envelopes with another tool name, failed outer status, or `ok != true` are not
promoted to successful retrieval. Set `allowed_hosts` to the actual storage
account hostname(s) when known. Otherwise HTTPS Azure Blob hostnames are accepted.
Neither authentication nor actual tool execution is proven by a JSON hash.
Those remain evaluator-host responsibilities.

Adapter result:

```text
version
tool_messages             # normalized grader-compatible messages
raw_tool_messages          # deep-copied original JSON values, unchanged
raw_sha256                 # canonical JSON value hash
reference_snippets         # actual snippets with original URI/ref_id/uid/raw reference
mappings                   # canonical refs, returned text, raw chunk origins
citation_aliases           # only unambiguous aliases
ambiguous_aliases
issues
ready                      # all pinned section bodies mapped; not a live-quality score
```

`audit_adapter` recomputes from the raw input and returns `version`, `raw_sha256`,
`ready`, `mappings`, `citation_aliases`, `ambiguous_aliases`, and `issues`.
It does not accept a model-authored normalization assertion as proof.

Parent integration:

```python
adapted = adapter.normalize_tool_messages(
    actual_raw_tool_results,
    reference=reference_row,
    allowed_hosts={actual_storage_hostname},
)
item = {
    "reference": reference_row,
    "tool_messages": adapted["tool_messages"],
    "rubric_sha256": pinned_rubric_file_sha256,
}
# Obtain the real reason-text judge result against the ORIGINAL final response
# and genuine retrieval evidence, then bind its hashes on the host side.
item["judge_result"] = actual_bound_judge_result
result = grader.evaluate(original_sample, item)
```

Bind `judge_result.output_sha256` to `grader.output_sha256(original_sample)`,
not a rewritten response. Bind its `retrieval_sha256` to
`grader.retrieval_sha256(item["tool_messages"])`, and its rubric hash to the
unchanged rubric file. Keep `adapted.raw_tool_messages`, raw URIs and ref IDs in
the parent's private audit storage. Never send raw audit metadata, expected
answers, or references as model input. Existing evaluator-side retrieval context
may contain the real returned passages; it must not substitute missing text.

## What is and is not evidence

The observed API emits a generated synthesis followed by JSON reference blocks:

```text
{kind:"reference", ref_id:0, uri:<actual blob URI>,
 sourceData:{snippet:<actual Markdown chunk>, blob_url:<actual URI>, uid:<actual UID>}}
```

The adapter reads only reference-block `sourceData.snippet`, including duplicate
reference objects under `structured_content`. Generated synthesis is retained
raw but never used as source evidence, even when it contains a complete expected
passage or authoritative-looking action guidance.

The entire expected **substantive body** must be present in genuine returned
chunks. Only the leading Markdown section heading and explicit `**Source ref:**`
marker are excluded as citation framing. Rates, conditions, exception language,
negations, identity fields, provenance sentences, nested headings, and JSON
record fields are not dropped.

A whole chunk may cover that body. Multiple chunks may cover it only through
exact observed suffix/prefix overlaps of at least eight tokens. Ordering and
inserted text are never taken from the pinned reference. Text emitted by the
adapter is selected from actual returned tokens, with whitespace normalization;
raw strings and all original JSON values remain retained separately.

Missing tails, missing middle segments, changed words, ambiguous repeated section
bodies, conflicting same-call reference IDs, wrong blob namespaces, URI/blob URL
disagreement, and failed calls remain missing/ambiguous audit results. There is
no fall-back to expected text. Non-overlapping or otherwise unprovable chunk
assembly may conservatively fail even if a human would infer the intended passage.

## Faithful citation normalization

Expanded source paths are matched against the complete remote
`knowledge/contracts/policy-analyst-v1/...` path, not merely the basename.
Original source refs use the explicit established
`data/{contracts|policies}/source-markdown/...` → `knowledge/contracts/...`
mapping. No other location is guessed.

Actual document URIs and document URI plus the pinned section slug may alias a
canonical ref only when full body coverage exists and the mapping is unique.
Document-level URIs covering multiple pinned sections are reported ambiguous.
`ref_id:N`, `[ref_id:N]`, and `ref_id=N` aliases are accepted only when that
individual returned reference contains the complete body. A partially supporting
reference ID cannot gain full-section credit merely because another chunk fills
the rest. `call:I/ref_id:N` provides a call-scoped form; reused unscoped IDs
across different documents/calls are never silently narrowed to the gold source.

The grader rechecks the adapter's raw hash, chunk-origin hashes and contiguous
body windows against actual raw reference snippets. It also rechecks individual
ID coverage and allowed alias forms, so inserting fabricated normalized text or
an unsupported alias does not bypass the raw evidence requirement.

## Narrow grader change

Legacy `{content:{sources:[{source_ref,text}]}}` callers keep the original full
section check. The new explicit adapter route accepts complete substantive-body
coverage verified against retained raw snippets. Neither route accepts incomplete
conditions or missing exception text.

Canonicalization affects local citation lookup only. The response JSON and its
output hash are unchanged. `evaluate(sample,item)` has one additive result field:

```text
citation_mappings: [{original_source_ref, canonical_source_ref}]
```

The existing fields remain `version`, `score`, `code_score`, `judge_score`,
`flags`, `pass`, and `judge_reasons`. The later coupled prerequisite also adds
`retrieval_observations`, without changing the original response or judge hashes.
The 0.8 pass threshold, critical caps, confidence/schema checks, reason-text
judge requirement, independent rubric, and expected outputs are unchanged.
Without a bound genuine semantic result, even a fully mapped canonical response
remains capped at 0.49. Mapping success is not entailment or live accuracy.

## Validation evidence

Focused tests use explicitly fake API-shaped corpus replays, not live calls:
raw preservation, complete URI/ref-ID aliases, overlapping chunks, omitted words,
synthesis-only support, wrong namespaces/hosts, reused/conflicting IDs, ambiguous
sections, structured-content deduplication, tampered hashes/passages and partial-ID
gaming. The parent's
`modules\agents\contract-policy-analyst\runs\kb-before-expansion-attempt-2.json`
is additionally read-only replayed when available; this is recorded historical
retrieval, not a new live call. No raw snapshot is copied into committed fixtures.

The new adapter validation report is
`modules\evals\graders\contract-policy-analyst\transcript-adapter-validation.json`.
Prior benchmark validation reports retain their original historical hashes;
this report records the final pre-freeze grader/adapter hashes.

## Subsequent protocol-only hardening

The recursive reference scan is replaced by explicit protocol-slot parsing.
Only top-level JSON reference objects in text content items and direct structured
reference slots are eligible. A source snippet is always opaque source text:
JSON inside it cannot create a new ref ID, URI, UID, citation alias or source.
Unrecognized dictionaries, nested structured synthesis and non-text blocks are
not searched for reference-looking objects.

Request-only `_meta.x-request-id` identifies generated synthesis in the observed
protocol. Genuine reference items can also share the request ID, but their
decoration contains `title` (including null) and boolean `preserveExactValue`
(including false). Both marked and bare genuine references remain supported.
These transport markers are not proof of entailment or tool authentication.

The quality grader and the standalone code-only reward use the same strict raw
reference boundaries when verifying normalized passages. Poisoned synthesis cannot
be rehabilitated by adding fabricated normalization metadata. Genuine overlap
assembly, raw retention, structured-reference deduplication and call-scoped alias
checks retain their existing behavior.

Explicit canonical `Not retrieved:` / `Not fully retrieved:` observations for
actually incomplete pinned bodies appear in `retrieval_observations`, not as claims
of nonexistence. They retain the existing retrieval/citation cap and never satisfy
a required business gap. A false claim of non-retrieval after full body coverage
is still a false gap. Other uncertainty wording remains a later calibration matter.

Final post-hardening results:
`modules\evals\graders\contract-policy-analyst\rft-reward-protocol-validation.json`.
Earlier validation reports remain historical evidence with their original hashes.
