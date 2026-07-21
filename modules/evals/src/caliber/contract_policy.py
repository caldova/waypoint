from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .paths import git_sha

TRAIN_SUPPLIERS = {
    "cmo-001",
    "cmo-002",
    "cmo-003",
    "cmo-004",
    "cmo-005",
    "cmo-006",
    "cmo-007",
    "cmo-008",
    "cmo-009",
    "cmo-010",
}
VALIDATION_SUPPLIERS = {"cmo-011", "cmo-012"}

PROMPT_VARIANTS = (
    {
        "id": "standard-evidence",
        "coordinator_question": (
            "Return the FoundryIQ evidence contract JSON for this invoice line. "
            "Identify grounded contract/policy evidence only."
        ),
        "request_style": "standard coordinator request",
        "focus": "balanced evidence extraction",
    },
    {
        "id": "citation-audit",
        "coordinator_question": (
            "Audit this invoice line for contract and policy support. Return only "
            "the strict FoundryIQ evidence JSON with source_ref citations."
        ),
        "request_style": "citation-focused audit",
        "focus": "citation specificity and grounded claims",
    },
    {
        "id": "variance-review",
        "coordinator_question": (
            "For this invoice variance review, identify the evidence-backed contract "
            "or policy basis. Return the FoundryIQ evidence JSON only."
        ),
        "request_style": "variance review",
        "focus": "issue category and support direction",
    },
    {
        "id": "controller-brief",
        "coordinator_question": (
            "Prepare the evidence object a controller can review before any payment "
            "decision. Cite only provided contract and policy evidence."
        ),
        "request_style": "controller evidence brief",
        "focus": "decision boundary discipline",
    },
    {
        "id": "supplier-response",
        "coordinator_question": (
            "Extract the contract and policy evidence needed for a supplier response. "
            "Do not make a payment decision; return strict JSON only."
        ),
        "request_style": "supplier response prep",
        "focus": "recommended supplier action support",
    },
    {
        "id": "risk-review",
        "coordinator_question": (
            "Review the invoice line for leakage risk and return the grounded "
            "FoundryIQ evidence JSON using only the retrieved evidence."
        ),
        "request_style": "payment leakage risk review",
        "focus": "risk category and source support",
    },
    {
        "id": "qa-check",
        "coordinator_question": (
            "Quality-check the billed line against the retrieved contract and policy "
            "sections. Return the strict evidence JSON with no extra prose."
        ),
        "request_style": "quality check",
        "focus": "shape compliance and no extra prose",
    },
    {
        "id": "terse-json",
        "coordinator_question": (
            "Return JSON only: grounded FoundryIQ evidence for this invoice line, "
            "with supported citations and no Waypoint write action."
        ),
        "request_style": "terse JSON request",
        "focus": "JSON-only response and write-boundary safety",
    },
)

CONTRACT_EXPANSION_VARIANTS = (
    {
        "id": "clause-grounding",
        "coordinator_question": (
            "Return the strict FoundryIQ evidence JSON for this contract or policy clause. "
            "Ground every claim in the provided source_ref values."
        ),
        "request_style": "contract clause grounding",
        "focus": "clause-level evidence extraction",
    },
    {
        "id": "invoice-risk",
        "coordinator_question": (
            "A future invoice line may depend on this clause. Extract the contract and policy "
            "evidence object only; do not make a payment decision."
        ),
        "request_style": "future invoice risk review",
        "focus": "billability boundary and support direction",
    },
    {
        "id": "citation-check",
        "coordinator_question": (
            "Audit the clause support and return JSON only with specific source_ref citations."
        ),
        "request_style": "citation audit",
        "focus": "citation specificity",
    },
    {
        "id": "controller-prep",
        "coordinator_question": (
            "Prepare a controller-review evidence object from the provided contract and policy "
            "sections. Cite only grounded evidence."
        ),
        "request_style": "controller prep",
        "focus": "review-ready evidence contract",
    },
)

CONTRACT_EVIDENCE_TERMS = (
    "approval",
    "authorization",
    "batch",
    "billable",
    "billing",
    "charge",
    "cost",
    "credit",
    "discount",
    "dispute",
    "documentation",
    "evidence",
    "escalation",
    "fee",
    "invoice",
    "material",
    "milestone",
    "price",
    "pricing",
    "quantity",
    "rate",
    "release",
    "surcharge",
    "true-up",
    "withhold",
)


def build_contract_policy_datasets(
    *,
    ledgerfield_path: Path,
    out_dir: Path,
    source_ref: str | None = None,
    variants_per_scenario: int = 1,
    agent: str = "contract-policy-expert",
    forge_agent: str | None = None,
) -> dict[str, Any]:
    if variants_per_scenario < 1:
        raise ValueError("variants_per_scenario must be at least 1")
    if variants_per_scenario > len(PROMPT_VARIANTS):
        raise ValueError(
            f"variants_per_scenario cannot exceed {len(PROMPT_VARIANTS)} deterministic variants"
        )
    resolved_agent = agent.strip()
    if not resolved_agent:
        raise ValueError("agent is required")
    resolved_forge_agent = (forge_agent or resolved_agent).strip()
    if not resolved_forge_agent:
        raise ValueError("forge_agent is required when provided")

    ledgerfield_root = ledgerfield_path.resolve()
    _require_file(ledgerfield_root / "data" / "scenarios" / "invoice-assurance-scenarios.json")
    _require_file(ledgerfield_root / "data" / "invoices" / "supplier-invoices.json")
    _require_file(ledgerfield_root / "data" / "suppliers" / "cmo_suppliers.json")

    scenarios = _read_json(
        ledgerfield_root / "data" / "scenarios" / "invoice-assurance-scenarios.json"
    )["scenarios"]
    invoices = _read_json(ledgerfield_root / "data" / "invoices" / "supplier-invoices.json")[
        "invoices"
    ]
    suppliers = {
        supplier["id"]: supplier
        for supplier in _read_json(ledgerfield_root / "data" / "suppliers" / "cmo_suppliers.json")
    }
    invoice_lines = _scenario_invoice_lines(invoices)
    resolved_source_ref = source_ref or _git_sha(ledgerfield_root)

    rows_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "eval": []}
    for scenario in scenarios:
        supplier_id = scenario["supplier_id"]
        line_record = invoice_lines.get(scenario["scenario_id"])
        if line_record is None:
            raise ValueError(f"scenario has no matching invoice line: {scenario['scenario_id']}")
        supplier = suppliers.get(supplier_id)
        if supplier is None:
            raise ValueError(f"scenario references unknown supplier: {supplier_id}")

        for variant in PROMPT_VARIANTS[:variants_per_scenario]:
            row = _build_row(
                ledgerfield_root=ledgerfield_root,
                source_ref=resolved_source_ref,
                scenario=scenario,
                supplier=supplier,
                invoice=line_record["invoice"],
                line=line_record["line"],
                prompt_variant=variant,
                agent=resolved_agent,
                forge_agent=resolved_forge_agent,
            )
            rows_by_split[_split_for_supplier(supplier_id)].append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for split, rows in rows_by_split.items():
        path = out_dir / f"{resolved_agent}-{split}.jsonl"
        _write_jsonl(path, rows)
        outputs[split] = {"path": str(path), "rows": len(rows)}

    return {
        "agent_alias": resolved_agent,
        "forge_agent": resolved_forge_agent,
        "source_repo": "caldova/waypoint",
        "source_ref": resolved_source_ref,
        "out_dir": str(out_dir),
        "prompt_variants_per_scenario": variants_per_scenario,
        "outputs": outputs,
        "next_step": (
            "Run caliber rle plan with the generated train, validation, eval datasets "
            f"and graders/{resolved_agent}/contract_policy_evidence_grader.py."
        ),
    }


def build_contract_policy_contract_expansion(
    *,
    ledgerfield_path: Path,
    out_dir: Path,
    source_ref: str | None = None,
    variants_per_clause: int = 3,
    agent: str = "contract-policy-expert",
    forge_agent: str | None = None,
) -> dict[str, Any]:
    if variants_per_clause < 1:
        raise ValueError("variants_per_clause must be at least 1")
    if variants_per_clause > len(CONTRACT_EXPANSION_VARIANTS):
        raise ValueError(
            f"variants_per_clause cannot exceed {len(CONTRACT_EXPANSION_VARIANTS)} variants"
        )
    resolved_agent = agent.strip()
    if not resolved_agent:
        raise ValueError("agent is required")
    resolved_forge_agent = (forge_agent or resolved_agent).strip()
    if not resolved_forge_agent:
        raise ValueError("forge_agent is required when provided")

    ledgerfield_root = ledgerfield_path.resolve()
    contracts_dir = ledgerfield_root / "data" / "contracts" / "source-markdown"
    policies_dir = ledgerfield_root / "data" / "policies" / "source-markdown"
    _require_file(ledgerfield_root / "data" / "suppliers" / "cmo_suppliers.json")
    if not contracts_dir.is_dir():
        raise ValueError(f"contracts source directory does not exist: {contracts_dir}")
    if not policies_dir.is_dir():
        raise ValueError(f"policies source directory does not exist: {policies_dir}")

    suppliers = {
        supplier["id"]: supplier
        for supplier in _read_json(ledgerfield_root / "data" / "suppliers" / "cmo_suppliers.json")
    }
    resolved_source_ref = source_ref or _git_sha(ledgerfield_root)
    rows_by_split: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "eval": []}
    section_count = 0

    for contract_path in sorted(contracts_dir.glob("*.md")):
        rel_contract = contract_path.relative_to(ledgerfield_root).as_posix()
        markdown = contract_path.read_text(encoding="utf-8")
        supplier_id = _contract_metadata(markdown, "Supplier ID")
        supplier = suppliers.get(supplier_id)
        if supplier is None:
            raise ValueError(f"contract references unknown supplier: {contract_path}")
        for section in _leaf_markdown_sections(markdown):
            if not _is_training_clause(section["title"], section["text"]):
                continue
            section_count += 1
            policy_ref = _policy_context_for_clause(
                ledgerfield_root=ledgerfield_root,
                title=section["title"],
                text=section["text"],
            )
            for variant in CONTRACT_EXPANSION_VARIANTS[:variants_per_clause]:
                row = _build_contract_expansion_row(
                    source_ref=resolved_source_ref,
                    supplier=supplier,
                    contract_ref={
                        "document": rel_contract,
                        "section": section["title"],
                        "text": section["text"],
                    },
                    policy_ref=policy_ref,
                    prompt_variant=variant,
                    agent=resolved_agent,
                    forge_agent=resolved_forge_agent,
                )
                rows_by_split[_split_for_supplier(supplier_id)].append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for split, rows in rows_by_split.items():
        path = out_dir / f"{resolved_agent}-contracts-{split}.jsonl"
        _write_jsonl(path, rows)
        outputs[split] = {"path": str(path), "rows": len(rows)}

    foundry_eval_path = out_dir / f"{resolved_agent}-contracts-foundry-eval-input.jsonl"
    _write_jsonl(
        foundry_eval_path,
        [_foundry_eval_input(row) for row in rows_by_split["eval"]],
    )
    outputs["foundry_eval_input"] = {
        "path": str(foundry_eval_path),
        "rows": len(rows_by_split["eval"]),
    }

    return {
        "agent_alias": resolved_agent,
        "forge_agent": resolved_forge_agent,
        "source_repo": "caldova/waypoint",
        "source_ref": resolved_source_ref,
        "out_dir": str(out_dir),
        "source_sections": section_count,
        "prompt_variants_per_clause": variants_per_clause,
        "outputs": outputs,
        "next_step": (
            "Review generated contract-clause rows, then either concatenate them with the "
            "scenario rows for RFT packaging or run a separate Foundry eval against the "
            "contracts-foundry-eval-input JSONL."
        ),
    }


def _build_row(
    *,
    ledgerfield_root: Path,
    source_ref: str,
    scenario: dict[str, Any],
    supplier: dict[str, Any],
    invoice: dict[str, Any],
    line: dict[str, Any],
    prompt_variant: dict[str, str],
    agent: str,
    forge_agent: str,
) -> dict[str, Any]:
    section_context = [
        _load_section_context(ledgerfield_root=ledgerfield_root, evidence_ref=evidence_ref)
        for evidence_ref in scenario["evidence_refs"]
    ]
    allowed_source_refs = [
        _source_ref(evidence_ref["document"], evidence_ref["section"])
        for evidence_ref in scenario["evidence_refs"]
    ]
    expected_output = _expected_output(
        scenario=scenario,
        invoice=invoice,
        section_context=section_context,
        allowed_source_refs=allowed_source_refs,
        agent=agent,
    )
    prompt = _input_prompt(
        supplier=supplier,
        invoice=invoice,
        line=line,
        section_context=section_context,
        scenario=scenario,
        prompt_variant=prompt_variant,
    )
    row_id = f"ledgerfield:{scenario['scenario_id']}:{line['line_id']}:{prompt_variant['id']}"
    return {
        "id": row_id,
        "messages": [
            {
                "role": "developer",
                "content": (
                    f"You are {agent}, the Forge hosted FoundryIQ contract/policy "
                    "evidence expert. Return strict JSON only. Stay in the foundryiq "
                    "knowledge plane. Retrieve or "
                    "use only provided contract and policy evidence. Do not approve, "
                    "reconcile, decide, write back to Waypoint, or create cases."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "expected": {"text": json.dumps(expected_output, sort_keys=True)},
        "expected_tools": [],
        "expected_output_json": expected_output,
        "ground_truth": {
            "decision_state": scenario["expected_decision_state"],
            "issue_category": scenario["issue_category"],
            "recommended_action": scenario["recommended_action"],
            "expected_supports": _support_for_state(scenario["expected_decision_state"]),
            "evidence_refs": scenario["evidence_refs"],
            "acceptable_citations": allowed_source_refs,
        },
        "retrieved_context": {
            "mode": "embedded",
            "forge_retrieval_tool": "knowledge_base___knowledge_base_retrieve",
            "contract_policy_sections": section_context,
        },
        "metadata": {
            "source_repo": "caldova/waypoint",
            "ledgerfield_source_ref": source_ref,
            "source_paths": [
                "data/scenarios/invoice-assurance-scenarios.json",
                "data/invoices/supplier-invoices.json",
                "data/suppliers/cmo_suppliers.json",
            ],
            "training_agent": agent,
            "forge_agent": forge_agent,
            "plane": "foundryiq",
            "rft_route": "plain_embedded_evidence",
            "future_tool_augmented_route": "knowledge_base___knowledge_base_retrieve",
            "prompt_variant": prompt_variant["id"],
            "prompt_variant_focus": prompt_variant["focus"],
            "scenario_id": scenario["scenario_id"],
            "supplier_id": scenario["supplier_id"],
            "invoice_id": invoice["invoice_id"],
            "line_id": line["line_id"],
            "split_group": f"supplier_id:{scenario['supplier_id']}",
            "label_source": "ledgerfield_scenario_metadata",
            "review_status": "seed",
        },
    }


def _build_contract_expansion_row(
    *,
    source_ref: str,
    supplier: dict[str, Any],
    contract_ref: dict[str, str],
    policy_ref: dict[str, str],
    prompt_variant: dict[str, str],
    agent: str,
    forge_agent: str,
) -> dict[str, Any]:
    clause_slug = _source_ref(contract_ref["document"], contract_ref["section"]).split("#", 1)[1]
    invoice_id = f"SYN-{supplier['id'].upper()}-{clause_slug.upper()[:24]}"
    line_id = f"{invoice_id}-L001"
    context = [
        {
            "document": contract_ref["document"],
            "section": contract_ref["section"],
            "source_ref": _source_ref(contract_ref["document"], contract_ref["section"]),
            "classification": "confidential",
            "text": contract_ref["text"],
        },
        policy_ref,
    ]
    support = _support_for_clause(contract_ref["section"], contract_ref["text"])
    action = _action_for_clause(contract_ref["section"], contract_ref["text"], support)
    expected = _contract_expansion_expected(
        agent=agent,
        invoice_id=invoice_id,
        section_context=context,
        summary=action,
        support=support,
    )
    row_id = f"ledgerfield-contract:{supplier['id']}:{clause_slug}:{prompt_variant['id']}"
    prompt = _contract_expansion_prompt(
        supplier=supplier,
        invoice_id=invoice_id,
        line_id=line_id,
        section_context=context,
        prompt_variant=prompt_variant,
        support=support,
    )
    return {
        "id": row_id,
        "messages": [
            {
                "role": "developer",
                "content": (
                    f"You are {agent}, the Forge hosted FoundryIQ contract/policy "
                    "evidence expert. Return strict JSON only. Stay in the foundryiq "
                    "knowledge plane. Use only provided contract and policy evidence. "
                    "Do not approve, reconcile, decide, write back to Waypoint, or create cases."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "expected": {"text": json.dumps(expected, sort_keys=True)},
        "expected_tools": [],
        "expected_output_json": expected,
        "ground_truth": {
            "decision_state": _decision_state_for_support(support),
            "issue_category": _issue_category_for_clause(
                contract_ref["section"],
                contract_ref["text"],
            ),
            "recommended_action": action,
            "expected_supports": support,
            "evidence_refs": [
                {"document": contract_ref["document"], "section": contract_ref["section"]},
                {"document": policy_ref["document"], "section": policy_ref["section"]},
            ],
            "acceptable_citations": [item["source_ref"] for item in context],
        },
        "retrieved_context": {
            "mode": "embedded",
            "forge_retrieval_tool": "knowledge_base___knowledge_base_retrieve",
            "contract_policy_sections": context,
        },
        "metadata": {
            "source_repo": "caldova/waypoint",
            "ledgerfield_source_ref": source_ref,
            "source_paths": [contract_ref["document"], policy_ref["document"]],
            "training_agent": agent,
            "forge_agent": forge_agent,
            "plane": "foundryiq",
            "rft_route": "plain_embedded_evidence",
            "future_tool_augmented_route": "knowledge_base___knowledge_base_retrieve",
            "prompt_variant": prompt_variant["id"],
            "prompt_variant_focus": prompt_variant["focus"],
            "scenario_id": f"contract-clause:{supplier['id']}:{clause_slug}",
            "supplier_id": supplier["id"],
            "invoice_id": invoice_id,
            "line_id": line_id,
            "split_group": f"supplier_id:{supplier['id']}",
            "label_source": "ledgerfield_contract_policy_markdown",
            "review_status": "generated_contract_clause_seed",
        },
    }


def _input_prompt(
    *,
    supplier: dict[str, Any],
    invoice: dict[str, Any],
    line: dict[str, Any],
    section_context: list[dict[str, Any]],
    scenario: dict[str, Any],
    prompt_variant: dict[str, str],
) -> str:
    payload = {
        "coordinator_question": prompt_variant["coordinator_question"],
        "request_style": prompt_variant["request_style"],
        "focus": prompt_variant["focus"],
        "supplier": {
            "id": supplier["id"],
            "name": supplier["name"],
            "supplier_type": supplier["supplier_type"],
            "region": supplier["region"],
            "specialty": supplier["specialty"],
            "contract_model": supplier["contract_model"],
            "reconciliation_focus": supplier["reconciliation_focus"],
            "risk_examples": supplier["risk_examples"],
        },
        "invoice": {
            "invoice_id": invoice["invoice_id"],
            "supplier_id": invoice["supplier_id"],
            "supplier_name": invoice["supplier_name"],
            "invoice_date": invoice["invoice_date"],
            "purchase_order_id": invoice["purchase_order_id"],
            "document_metadata": invoice["document_metadata"],
        },
        "line": line,
        "retrieved_context": section_context,
        "negative_constraints": [
            "no_decision",
            "no_waypoint_write",
            "no_uncited_claims",
            "json_only",
        ],
        "scenario_hint": {
            "scenario_id": scenario["scenario_id"],
            "future_invoice_line": scenario["future_invoice_line"],
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _contract_expansion_prompt(
    *,
    supplier: dict[str, Any],
    invoice_id: str,
    line_id: str,
    section_context: list[dict[str, Any]],
    prompt_variant: dict[str, str],
    support: str,
) -> str:
    payload = {
        "coordinator_question": prompt_variant["coordinator_question"],
        "request_style": prompt_variant["request_style"],
        "focus": prompt_variant["focus"],
        "supplier": {
            "id": supplier["id"],
            "name": supplier["name"],
            "supplier_type": supplier["supplier_type"],
            "region": supplier["region"],
            "specialty": supplier["specialty"],
            "contract_model": supplier["contract_model"],
            "reconciliation_focus": supplier["reconciliation_focus"],
        },
        "invoice": {
            "invoice_id": invoice_id,
            "supplier_id": supplier["id"],
            "supplier_name": supplier["name"],
            "document_metadata": {
                "source": "synthetic contract-clause expansion",
                "review_status": "generated_contract_clause_seed",
            },
        },
        "line": {
            "line_id": line_id,
            "description": f"Future invoice line requiring {support} evidence support",
            "expected_supports": support,
        },
        "retrieved_context": section_context,
        "negative_constraints": [
            "no_decision",
            "no_waypoint_write",
            "no_uncited_claims",
            "json_only",
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _expected_output(
    *,
    scenario: dict[str, Any],
    invoice: dict[str, Any],
    section_context: list[dict[str, Any]],
    allowed_source_refs: list[str],
    agent: str,
) -> dict[str, Any]:
    support = _support_for_state(scenario["expected_decision_state"])
    evidence = []
    for context, source in zip(section_context, allowed_source_refs, strict=True):
        evidence.append(
            {
                "claim": scenario["recommended_action"],
                "supports": support,
                "source_ref": source,
                "classification": context["classification"],
                "confidence": 0.86,
            }
        )
    return {
        "agent": agent,
        "plane": "foundryiq",
        "invoice_id": invoice["invoice_id"],
        "output_type": "expert_evidence",
        "evidence": evidence,
        "unsupported": [],
        "summary": scenario["recommended_action"],
        "correlation": {
            "waypoint_run_id": "ledgerfield-seed",
            "waypoint_invoice_id": invoice["invoice_id"],
        },
    }


def _contract_expansion_expected(
    *,
    agent: str,
    invoice_id: str,
    section_context: list[dict[str, Any]],
    summary: str,
    support: str,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "plane": "foundryiq",
        "invoice_id": invoice_id,
        "output_type": "expert_evidence",
        "evidence": [
            {
                "claim": _claim_for_context(context),
                "supports": support,
                "source_ref": context["source_ref"],
                "classification": context["classification"],
                "confidence": 0.84,
            }
            for context in section_context
        ],
        "unsupported": [],
        "summary": summary,
        "correlation": {
            "waypoint_run_id": "ledgerfield-contract-expansion",
            "waypoint_invoice_id": invoice_id,
        },
    }


def _load_section_context(
    *,
    ledgerfield_root: Path,
    evidence_ref: dict[str, str],
) -> dict[str, Any]:
    rel_path = evidence_ref["document"]
    section = evidence_ref["section"]
    path = ledgerfield_root / rel_path
    _require_file(path)
    text = _extract_markdown_section(path.read_text(encoding="utf-8"), section)
    return {
        "document": rel_path,
        "section": section,
        "source_ref": _source_ref(rel_path, section),
        "classification": "confidential" if "/contracts/" in rel_path else "standard",
        "text": text,
    }


def _extract_markdown_section(markdown: str, section: str) -> str:
    lines = markdown.splitlines()
    heading_index = None
    heading_level = None
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and match.group(2).strip() == section:
            heading_index = index
            heading_level = len(match.group(1))
            break
    if heading_index is None or heading_level is None:
        raise ValueError(f"section not found in markdown: {section}")

    end_index = len(lines)
    for index in range(heading_index + 1, len(lines)):
        match = re.match(r"^(#{1,6})\s+", lines[index])
        if match and len(match.group(1)) <= heading_level:
            end_index = index
            break
    return "\n".join(lines[heading_index:end_index]).strip()


def _leaf_markdown_sections(markdown: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    headings = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if match:
            headings.append(
                {
                    "index": index,
                    "level": len(match.group(1)),
                    "title": match.group(2).strip(),
                }
            )

    sections = []
    for pos, heading in enumerate(headings):
        next_index = len(lines)
        has_child = False
        for later in headings[pos + 1 :]:
            if later["level"] <= heading["level"]:
                next_index = later["index"]
                break
            has_child = True
        if has_child:
            continue
        text = "\n".join(lines[heading["index"] : next_index]).strip()
        sections.append({"title": str(heading["title"]), "text": text})
    return sections


def _contract_metadata(markdown: str, name: str) -> str:
    pattern = re.compile(rf"^\*\*{re.escape(name)}:\*\*\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        raise ValueError(f"contract metadata missing: {name}")
    return match.group(1).strip()


def _is_training_clause(title: str, text: str) -> bool:
    haystack = f"{title}\n{text}".lower()
    return any(term in haystack for term in CONTRACT_EVIDENCE_TERMS)


def _policy_context_for_clause(
    *,
    ledgerfield_root: Path,
    title: str,
    text: str,
) -> dict[str, str]:
    lowered = f"{title}\n{text}".lower()
    if any(term in lowered for term in ("qa", "release", "rejected", "retest", "quality")):
        policy_document = "data/policies/source-markdown/quality-release-billability-policy.md"
        policy_section = "6. Required evidence"
    elif any(term in lowered for term in ("escalate", "ip", "compliance", "sensitive")):
        policy_document = "data/policies/source-markdown/invoice-dispute-and-recovery-procedure.md"
        policy_section = "6. Escalation"
    elif any(term in lowered for term in ("dispute", "withhold", "credit", "recover")):
        policy_document = "data/policies/source-markdown/invoice-dispute-and-recovery-procedure.md"
        policy_section = "5. Withholding disputed amounts"
    elif any(term in lowered for term in ("duplicate", "wrong", "off-contract", "true-up")):
        policy_document = "data/policies/source-markdown/invoice-reconciliation-policy.md"
        policy_section = "5. Payment leakage categories"
    else:
        policy_document = "data/policies/source-markdown/invoice-reconciliation-policy.md"
        policy_section = "4. Minimum evidence for approval"

    policy_path = ledgerfield_root / policy_document
    _require_file(policy_path)
    return {
        "document": policy_document,
        "section": policy_section,
        "source_ref": _source_ref(policy_document, policy_section),
        "classification": "standard",
        "text": _extract_markdown_section(policy_path.read_text(encoding="utf-8"), policy_section),
    }


def _support_for_clause(title: str, text: str) -> str:
    lowered = f"{title}\n{text}".lower()
    if any(term in lowered for term in ("escalate", "compliance", "ip-sensitive")):
        return "escalate"
    if any(
        term in lowered
        for term in (
            "not billable",
            "not be billed",
            "included",
            "duplicate",
            "withhold",
            "credit",
            "dispute",
        )
    ):
        return "recover"
    if any(term in lowered for term in ("billable only", "only when", "must", "requires")):
        return "review"
    return "review"


def _decision_state_for_support(support: str) -> str:
    return {
        "approve": "matched",
        "review": "variance",
        "recover": "disputed",
        "escalate": "escalated",
    }.get(support, "variance")


def _issue_category_for_clause(title: str, text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", f"{title} {text[:80]}".lower()).strip("_")
    return slug[:80] or "contract_clause_review"


def _action_for_clause(title: str, text: str, support: str) -> str:
    clause = title.rstrip(".")
    if support == "escalate":
        return f"Escalate invoice evidence involving {clause} for quality or compliance review."
    if support == "recover":
        return f"Use {clause} to dispute or recover unsupported invoice charges."
    return f"Review the invoice line against {clause} and request supporting authorization."


def _claim_for_context(context: dict[str, str]) -> str:
    body = " ".join(
        line.strip()
        for line in context["text"].splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    sentence = body.split(". ", 1)[0].strip()
    if sentence:
        return sentence.rstrip(".") + "."
    return f"{context['section']} provides grounded contract or policy evidence."


def _foundry_eval_input(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "query": row["messages"][-1]["content"],
        "expected_behavior": row["expected"]["text"],
        "ground_truth": row["ground_truth"],
        "metadata": row["metadata"],
    }


def _scenario_invoice_lines(invoices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    records = {}
    for invoice in invoices:
        for line in invoice["lines"]:
            scenario_id = line.get("scenario_id")
            if scenario_id:
                records[scenario_id] = {"invoice": invoice, "line": line}
    return records


def _support_for_state(decision_state: str) -> str:
    mapping = {
        "matched": "approve",
        "variance": "review",
        "disputed": "recover",
        "escalated": "escalate",
    }
    return mapping.get(decision_state, "unknown")


def _split_for_supplier(supplier_id: str) -> str:
    if supplier_id in TRAIN_SUPPLIERS:
        return "train"
    if supplier_id in VALIDATION_SUPPLIERS:
        return "validation"
    return "eval"


def _source_ref(document: str, section: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", section.lower()).strip("-")
    return f"{document}#{slug}"


def _require_file(path: Path) -> None:
    if not path.exists():
        raise ValueError(f"required Ledgerfield source file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"required Ledgerfield source path is not a file: {path}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON source file: {path}") from exc


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    path.write_text(content, encoding="utf-8")


def _git_sha(path: Path) -> str:
    return git_sha(path)
