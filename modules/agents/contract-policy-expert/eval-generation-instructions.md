# Contract Policy Expert rubric generation brief

Generate a rubric evaluator for a read-only contract and policy evidence expert.

The agent answers supplier invoice review questions using retrieved contract and
policy evidence from the `contracts-kb-mcp___knowledge_base_retrieve` tool. The
dataset may also include already-retrieved context. A high-quality answer should:

- ground every material contract or policy claim in retrieved evidence from
  `contracts-kb-mcp___knowledge_base_retrieve` or supplied retrieved context
- cite stable source references for contract, policy, clause, or passage support
- return a reviewer-ready evidence packet rather than generic prose
- identify unsupported claims and missing evidence instead of guessing
- distinguish supported facts from evidence gaps
- stay advisory and read-only; it must not approve invoices, reconcile balances,
  trigger recovery, create cases, or write back to business systems
- provide a concise next step for a human reviewer when evidence supports one

Reward responses that are useful for invoice review because they connect the
charge, supplier, contract/policy term, cited source, support direction, and
remaining gap. Penalize uncited claims, vague summaries, unsupported conclusions,
missing evidence-gap handling, malformed evidence packets, and any language that
implies the agent took final finance action.
