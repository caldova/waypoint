"""Build a small, unreviewed challenge set from current corpus clauses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contract_policy import _load_section_context

POLICY = {
    "document": "data/policies/source-markdown/invoice-reconciliation-policy.md",
    "section": "4. Minimum evidence for approval",
}
POLICY_CLAIM = (
    "An invoice line may be approved only when the billed item can be tied to an "
    "authorized source document."
)
CONTRACTS = "data/contracts/source-markdown"

# Facts are fictional counterfactuals, not claims about actual invoices or documents.
CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "included-quality-documentation",
        "supplier": "sup-013",
        "document": f"{CONTRACTS}/sup-013-evergreen-excipients-supply-agreement.md",
        "section": "5. Included quality documentation",
        "distractor": "4. Rush order approval",
        "line": "Charge for a standard certificate of analysis for an excipient lot.",
        "facts": [
            "The hypothetical invoice identifies the charge as a standard certificate of analysis.",
            "The hypothetical order contains no request for a non-standard document set.",
        ],
        "support": "recover",
        "action": (
            "Dispute the separate standard certificate charge because it is included in unit cost."
        ),
        "claim": "Standard certificates of analysis are included in unit cost.",
        "unsupported": [],
        "derivation": (
            "The visible line is for a standard certificate, and section 5 includes it in unit "
            "cost; the hypothetical order does not request non-standard documents."
        ),
    },
    {
        "id": "rush-authorization-not-provided",
        "supplier": "sup-013",
        "document": f"{CONTRACTS}/sup-013-evergreen-excipients-supply-agreement.md",
        "section": "4. Rush order approval",
        "distractor": "5. Included quality documentation",
        "line": "Rush-order fee for an excipient lot.",
        "facts": [
            "The hypothetical invoice names lot LOT-R13 and a requested ship date.",
            "Only a purchase order number is visible; no purchase order or written sponsor "
            "approval is supplied.",
        ],
        "support": "review",
        "action": (
            "Request the purchase order or written sponsor approval identifying the lot, "
            "requested ship date, and rush service level."
        ),
        "claim": (
            "Rush-order fees require a purchase order or written sponsor approval identifying "
            "the lot, requested ship date, and rush service level."
        ),
        "unsupported": [
            "Purchase order or written sponsor approval identifying the lot, requested ship date, "
            "and rush service level was not supplied."
        ],
        "derivation": (
            "Section 4 requires an identifying purchase order or written approval; the prompt "
            "provides only an order number, so the document's contents cannot be inferred."
        ),
    },
    {
        "id": "regional-volume-tier-matched",
        "supplier": "sup-014",
        "document": f"{CONTRACTS}/sup-014-atlas-regional-manufacturing-sow.md",
        "section": "2. Regional price tiers",
        "distractor": "3. Capacity reservation",
        "line": "2,100,000 released tablets at USD 0.36 each, total USD 756,000.",
        "facts": [
            "A hypothetical purchase order authorizes this supplier and SKU for the service month.",
            "A hypothetical sponsor QA release record identifies that SKU and 2,100,000 "
            "released tablets in the same month.",
            "The hypothetical invoice identifies the same supplier, SKU and month, quantity, "
            "unit rate and total.",
        ],
        "support": "approve",
        "action": (
            "The volume tier supports the invoiced rate; present the matched line "
            "for controller review."
        ),
        "claim": (
            "Monthly released volume of at least 2,000,000 tablets qualifies for USD 0.36 "
            "per released tablet for all released units."
        ),
        "unsupported": [],
        "derivation": (
            "Section 2 sets the USD 0.36 rate at this released volume. The hypothetical "
            "authorization and release record match the invoice, and 2,100,000 times 0.36 "
            "equals USD 756,000. The label is evidence support, not a payment action."
        ),
    },
    {
        "id": "capacity-timely-cancellation",
        "supplier": "sup-014",
        "document": f"{CONTRACTS}/sup-014-atlas-regional-manufacturing-sow.md",
        "section": "3. Capacity reservation",
        "distractor": "2. Regional price tiers",
        "line": "A December capacity reservation charge.",
        "facts": [
            "The hypothetical active purchase order lists the December reservation.",
            "The hypothetical sponsor cancellation notice is dated 2026-10-31; "
            "the first scheduled run is 2026-12-20.",
        ],
        "support": "recover",
        "action": (
            "Dispute the capacity charge because cancellation preceded the first run by 50 days."
        ),
        "claim": (
            "A reservation charge is not billable when the sponsor cancels at least "
            "45 calendar days before the first scheduled run."
        ),
        "unsupported": [],
        "derivation": (
            "The hypothetical dates are 50 calendar days apart, so the cancellation "
            "condition in section 3 applies even though December is on the purchase order."
        ),
    },
    {
        "id": "regulatory-filing-not-provided",
        "supplier": "sup-015",
        "document": f"{CONTRACTS}/sup-015-signal-ridge-regulatory-services-agreement.md",
        "section": "3. Submission evidence",
        "distractor": "2. Country scope authorization",
        "line": "Variation submission milestone for a listed country.",
        "facts": [
            "A hypothetical approved work order lists the country and procedure.",
            "The hypothetical invoice references a planned filing, but no filing evidence or "
            "submission date is supplied.",
        ],
        "support": "review",
        "action": (
            "Request filing evidence identifying the country, procedure, and submission date."
        ),
        "claim": (
            "Variation submission milestones require filing and evidence identifying the "
            "country, procedure, and submission date."
        ),
        "unsupported": [
            "Filing evidence identifying the country, procedure, and submission date "
            "was not provided."
        ],
        "derivation": (
            "Section 3 requires a filed package and filing evidence. The work order supports "
            "country scope but does not prove filing occurred."
        ),
    },
    {
        "id": "translation-correction-rush-premium",
        "supplier": "sup-015",
        "document": f"{CONTRACTS}/sup-015-signal-ridge-regulatory-services-agreement.md",
        "section": "5. Translation rates",
        "distractor": "3. Submission evidence",
        "line": "Rush premium on a corrected translation.",
        "facts": [
            "The hypothetical sponsor requested correction of a prior Signal Ridge "
            "translation error.",
            "The hypothetical invoice applies a rush premium to that correction.",
        ],
        "support": "recover",
        "action": (
            "Dispute the rush premium on the sponsor-requested correction of the supplier's "
            "translation error."
        ),
        "claim": (
            "Rush translation premiums may not be applied to sponsor-requested corrections "
            "of prior Signal Ridge translation errors."
        ),
        "unsupported": [],
        "derivation": (
            "Section 5 expressly excludes a rush premium for sponsor-requested corrections "
            "to this supplier's prior translation errors."
        ),
    },
)


def build_contract_policy_challenge(*, corpus_path: Path, out: Path) -> dict[str, Any]:
    """Create reproducible candidates without overwriting edited review data."""
    supplier_path = corpus_path / "data" / "suppliers" / "suppliers.json"
    suppliers = {item["id"]: item for item in json.loads(supplier_path.read_text("utf-8"))}
    rows = [_build_case(case, corpus_path, supplier_path, suppliers) for case in CASES]
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    if out.exists():
        if out.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite existing challenge data: {out}")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8", newline="\n")
    return {
        "path": str(out),
        "rows": len(rows),
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "review_status": "pending_human_review",
        "note": "Fictional candidates; do not treat as reviewed ground truth.",
    }


def corpus_source_sha256(path: Path) -> str:
    """Hash normalized UTF-8 text so checkout line endings do not alter provenance."""
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _build_case(
    case: dict[str, Any],
    corpus_path: Path,
    supplier_path: Path,
    suppliers: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    supplier = suppliers[case["supplier"]]
    primary = _load_section_context(
        ledgerfield_root=corpus_path,
        evidence_ref={"document": case["document"], "section": case["section"]},
    )
    policy = _load_section_context(ledgerfield_root=corpus_path, evidence_ref=POLICY)
    distractor = _load_section_context(
        ledgerfield_root=corpus_path,
        evidence_ref={"document": case["document"], "section": case["distractor"]},
    )
    sections = [distractor, policy, primary]
    invoice_id = f"SYN-CHALLENGE-{case['supplier'].upper()}-{case['id'].upper()}"
    scenario_id = f"synthetic-challenge:{case['id']}"
    action = case["action"]
    expected = {
        "agent": "contract-policy-expert",
        "plane": "foundryiq",
        "invoice_id": invoice_id,
        "output_type": "expert_evidence",
        "evidence": [
            {
                "claim": claim,
                "supports": case["support"],
                "source_ref": section["source_ref"],
                "classification": section["classification"],
                "confidence": 0.84,
            }
            for section, claim in ((primary, case["claim"]), (policy, POLICY_CLAIM))
        ],
        "unsupported": case["unsupported"],
        "summary": action,
        "correlation": {"waypoint_invoice_id": invoice_id, "waypoint_run_id": "unknown"},
    }
    prompt = {
        "coordinator_question": (
            "Review this fictional invoice line using only the visible hypothetical facts and "
            "retrieved contract/policy sections. Return grounded expert_evidence JSON; identify "
            "missing evidence and do not take a payment or business-system action."
        ),
        "supplier": {"id": supplier["id"], "name": supplier["name"]},
        "invoice": {"invoice_id": invoice_id, "supplier_id": supplier["id"]},
        "line": {"line_id": invoice_id + "-L1", "description": case["line"]},
        "hypothetical_facts": case["facts"],
        "retrieved_context": sections,
        "negative_constraints": [
            "no_decision", "no_waypoint_write", "no_uncited_claims", "json_only"
        ],
    }
    sources = [supplier_path, corpus_path / case["document"], corpus_path / POLICY["document"]]
    return {
        "id": scenario_id,
        "messages": [
            {
                "role": "developer",
                "content": (
                    "You are contract-policy-expert. Return strict expert_evidence JSON only. "
                    "Use the supplied evidence; do not approve payment, reconcile, decide, "
                    "write back to Waypoint, or create cases."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, indent=2, sort_keys=True)},
        ],
        "expected": {"text": json.dumps(expected, sort_keys=True)},
        "expected_tools": [],
        "expected_output_json": expected,
        "ground_truth": {
            "acceptable_citations": [primary["source_ref"], policy["source_ref"]],
            "expected_supports": case["support"],
            "recommended_action": action,
        },
        "retrieved_context": {
            "mode": "embedded",
            "forge_retrieval_tool": "knowledge_base___knowledge_base_retrieve",
            "contract_policy_sections": sections,
        },
        "metadata": {
            "source_repo": "caldova/waypoint",
            "source_root": "modules/corpus",
            "source_hash_format": "sha256_utf8_lf",
            "source_sha256": {
                path.relative_to(corpus_path).as_posix(): corpus_source_sha256(path)
                for path in sources
            },
            "training_agent": "contract-policy-expert",
            "forge_agent": "contract-policy-expert",
            "supplier_id": supplier["id"],
            "supplier_name": supplier["name"],
            "invoice_id": invoice_id,
            "line_id": invoice_id + "-L1",
            "scenario_id": scenario_id,
            "label_source": "synthetic_counterfactual_from_corpus_clauses",
            "review_status": "pending_human_review",
            "expected_answer_derivation": case["derivation"],
            "intended_use": "held_out_candidate_not_train_or_validation",
        },
    }
