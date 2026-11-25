"""Versioned v3 evaluator references for contract-policy-analyst (offline only).

v1 references stay immutable. v3 re-derives the evidence direction from the same
source-authored text and recorded fields, fixing defects found in the hand audit:

* unit pricing says "per observed accepted service unit" but v1 priced quantity;
* fixed-fee "once per accepted service item" with accepted_quantity 0 is ambiguous;
* tier pricing "per service unit" with an accepted-count prerequisite does not say
  which count is the price basis, so either reading is acceptable;
* per-source direction is a set of acceptable values (neutral sources may be
  review or unknown) instead of one exact label.

Labels remain synthetic and pending human review. Corpus text is unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from caliber.contract_policy_analyst_benchmark import (
    AGENT,
    STUDY_SPLITS,
    commercial_amount,
    read_jsonl,
)

VERSION = "contract-policy-analyst-reference-v3"
NEUTRAL = ("review", "unknown")
ROLES = ("rule", "policy", "observations", "invoice")
CONTROLLER = " The controller retains the decision."


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _role(source_ref: str) -> str:
    anchor = source_ref.split("#", 1)[-1]
    name = source_ref.rsplit("/", 1)[-1]
    if "commercial-rule" in anchor:
        return "rule"
    if "evidence-policy" in name:
        return "policy"
    if "observations" in name:
        return "observations"
    if "-inv" in name and "invoice-line" in anchor:
        return "invoice"
    raise ValueError(f"unrecognized source role: {source_ref}")


def amount_readings(rule: dict[str, Any], facts: dict[str, Any]) -> dict[str, Decimal]:
    """Every defensible clause-derived amount, keyed by the quantity reading used."""
    kind, params = rule["calculation"], rule["parameters"]
    rate = Decimal(str(params["rate"]))
    accepted = Decimal(str(facts["accepted_quantity"]))
    if kind == "unit":
        return {"accepted_quantity": (rate * accepted).quantize(Decimal("0.01"))}
    if kind == "fixed":
        # "USD N once per accepted service item": zero accepted items supports no fee.
        return {"accepted_items": (rate * accepted).quantize(Decimal("0.01"))}
    if kind == "tier":
        return {
            "quantity": commercial_amount(kind, params, facts),
            "accepted_quantity": commercial_amount(
                kind, params, {**facts, "quantity": facts["accepted_quantity"]},
            ),
        }
    return {"authored": commercial_amount(kind, params, facts)}


def _window_valid(rule: dict[str, Any], facts: dict[str, Any]) -> bool:
    params, day = rule["parameters"], facts["completion_day"]
    end = params["window_end_day"]
    return 1 <= day <= end if params["window_end_inclusive"] else 1 <= day < end


def _basis_text(kind: str, reading: str) -> str:
    return {
        ("unit", "accepted_quantity"): "accepted-unit basis",
        ("fixed", "accepted_items"): "once-per-accepted-item basis",
        ("tier", "quantity"): "observed-quantity basis",
        ("tier", "accepted_quantity"): "accepted-quantity basis",
    }.get((kind, reading), "authored basis")


def classify(reference: dict[str, Any]) -> dict[str, Any]:
    """Return the v3 category, amounts, corrections and ambiguity for one case."""
    truth = reference["ground_truth"]
    rule, facts = truth["authored_rule"], truth["observed_facts"]
    invoice = truth["invoice_facts"]
    v1 = truth["derived_expectation"]
    record = v1["record_supports"]
    billed = Decimal(str(invoice["amount"])).quantize(Decimal("0.01"))
    readings = amount_readings(rule, facts) if record != "unknown" else {}
    distinct = sorted(set(readings.values()))
    discrepancy = bool(distinct) and billed not in distinct
    out: dict[str, Any] = {
        "billed_amount": _money(billed),
        "amount_readings": {k: _money(v) for k, v in readings.items()},
        "definite_amount_discrepancy": discrepancy,
        "corrections": [], "ambiguity": None,
    }
    if record == "unknown":
        out["category"] = "wrong_entity"
    elif record == "escalate":
        out["category"] = "escalate"
    elif record == "review":
        out["category"] = "missing_condition"
    elif rule["calculation"] == "window" and not _window_valid(rule, facts) or discrepancy:
        out["category"] = "recover"
    elif len(distinct) > 1:
        out["category"] = "ambiguous"
        matched = sorted(k for k, v in readings.items() if v == billed)
        out["ambiguity"] = (
            f"The billed USD {_money(billed)} matches the {', '.join(matched)} reading of "
            f"the {rule['calculation']} rule but not "
            + ", ".join(
                f"{k} (USD {_money(v)})" for k, v in sorted(readings.items()) if v != billed
            )
            + "; the authored text does not settle which quantity is the price basis."
        )
    else:
        out["category"] = "approve"
    if out["category"] in {"approve", "recover"} and out["category"] != record:
        out["corrections"].append({
            "field": "record_supports", "v1": record, "v3": out["category"],
            "basis": "price basis re-derived from authored commercial text: "
            + rule["calculation"],
        })
    if out["category"] == "ambiguous":
        out["corrections"].append({
            "field": "record_supports", "v1": record, "v3": "ambiguous",
            "basis": "authored commercial text admits more than one quantity basis",
        })
    if (
        v1.get("expected_amount") and readings
        and v1["expected_amount"] not in out["amount_readings"].values()
    ):
        out["corrections"].append({
            "field": "expected_amount", "v1": v1["expected_amount"],
            "v3": sorted(set(out["amount_readings"].values())),
            "basis": "authored text names the accepted-unit/accepted-item basis",
        })
    return out


def contract(reference: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """Per-source acceptable directions and case-level requirements."""
    refs = [s["source_ref"] for s in reference["sources"]]
    roles = {ref: _role(ref) for ref in refs}
    if sorted(roles.values()) != sorted(ROLES):
        raise ValueError(f"unexpected source roles: {reference['id']}")
    category = info["category"]
    neutral = set(NEUTRAL)
    allowed: dict[str, set[str]] = {}
    require: dict[str, Any] | None = None
    forbidden: set[str] = set()
    for ref, role in roles.items():
        if role == "policy":
            allowed[ref] = neutral | ({"escalate"} if category == "escalate" else set())
        elif category == "approve":
            allowed[ref] = neutral | {"approve"}
        elif category == "recover" or category == "missing_condition":
            allowed[ref] = neutral | {"approve", "recover"}
        elif category == "wrong_entity":
            allowed[ref] = set(neutral)
        elif category == "escalate":
            allowed[ref] = neutral | {"escalate"}
            if info["definite_amount_discrepancy"]:
                allowed[ref].add("recover")
        else:
            allowed[ref] = neutral | {"approve", "recover"}
    decisive = [r for r, role in roles.items() if role in {"rule", "observations"}]
    if category == "approve":
        forbidden = {"recover", "escalate"}
        require = {"supports": ["approve"], "source_refs": decisive}
    elif category == "recover":
        forbidden = {"escalate"}
        require = {
            "supports": ["recover"],
            "source_refs": [r for r, role in roles.items() if role != "policy"],
        }
    elif category == "missing_condition":
        forbidden = {"escalate"}
        require = {"supports": list(NEUTRAL), "source_refs": decisive}
    elif category == "wrong_entity":
        forbidden = {"approve", "recover", "escalate"}
        require = {
            "supports": list(NEUTRAL),
            "source_refs": [r for r, role in roles.items() if role == "observations"],
        }
    elif category == "escalate":
        forbidden = {"approve"} | (
            set() if info["definite_amount_discrepancy"] else {"recover"}
        )
        require = {
            "supports": ["escalate"],
            "source_refs": [r for r, role in roles.items() if role in {"policy", "observations"}],
        }
    else:
        forbidden = {"escalate"}
    required_gaps = list(reference["required_gaps"]) if category in {
        "missing_condition", "wrong_entity", "escalate",
    } else []
    optional_gaps = []
    if category == "ambiguous":
        optional_gaps.append(
            "The chargeable quantity basis for this billed amount is not defined by the "
            "authored rule; the billable amount is unverified."
        )
    return {
        "category": category,
        "roles": roles,
        "allowed_supports": {ref: sorted(values) for ref, values in allowed.items()},
        "forbidden_supports": sorted(forbidden),
        "require_any": require,
        "required_gaps": required_gaps,
        "gap_required": bool(required_gaps),
        "optional_gaps": optional_gaps,
        "approval_expected": category == "approve",
        "definite_amount_discrepancy": info["definite_amount_discrepancy"],
        "amount_readings": info["amount_readings"],
        "billed_amount": info["billed_amount"],
        "ambiguity": info["ambiguity"],
        "corrections": info["corrections"],
        "classification_graded": False,
    }


def _fixture(reference: dict[str, Any], terms: dict[str, Any]) -> dict[str, Any]:
    v1 = reference["expected_output_json"]
    truth = reference["ground_truth"]
    category = terms["category"]
    expected = copy.deepcopy(v1)
    supports = {
        "approve": {"rule": "approve", "observations": "approve"},
        "recover": {"rule": "recover", "observations": "recover"},
        "missing_condition": {"rule": "review", "observations": "review"},
        "wrong_entity": {"rule": "review", "observations": "unknown"},
        "escalate": {"policy": "escalate", "observations": "escalate"},
        "ambiguous": {},
    }[category]
    for row in expected["evidence"]:
        row["supports"] = supports.get(terms["roles"][row["source_ref"]], "review")
    if category == "recover" and terms["corrections"] and len(terms["amount_readings"]) == 1:
        reading, amount = next(iter(terms["amount_readings"].items()))
        expected["summary"] = (
            f"The clause-derived amount on the "
            f"{_basis_text(truth['authored_rule']['calculation'], reading)} is USD {amount}, "
            f"while the invoice bills USD {terms['billed_amount']}." + CONTROLLER
        )
    elif category == "ambiguous":
        expected["summary"] = terms["ambiguity"] + CONTROLLER
    expected["unsupported"] = list(terms["required_gaps"] or terms["optional_gaps"])
    return expected


def build_reference(reference: dict[str, Any]) -> dict[str, Any]:
    info = classify(reference)
    terms = contract(reference, info)
    v3 = copy.deepcopy(reference)
    v3["version"] = VERSION
    v3["expected_output_json"] = _fixture(reference, terms)
    v3["required_gaps"] = terms["required_gaps"]
    v3["v3_contract"] = terms
    v3["derived_from"] = {
        "version": reference.get("version"),
        "reference_sha256": _sha(_canonical(reference)),
    }
    v3["synthetic"] = True
    v3["review_status"] = "pending_human_review"
    return v3


def build(repo: Path, splits: tuple[str, ...] = STUDY_SPLITS) -> dict[str, Any]:
    root = repo.resolve() / "modules" / "evals" / "datasets" / AGENT / "expanded-v1"
    report = json.loads((root / "validation-report.json").read_text(encoding="utf-8"))
    out_dir = root / "references-v3"
    out_dir.mkdir(exist_ok=True)
    manifest: dict[str, Any] = {
        "version": VERSION, "synthetic": True, "review_status": "pending_human_review",
        "builder": "modules/evals/src/caliber/contract_policy_analyst_references_v3.py",
        "final_test_note": (
            "final-test-v2 stays sealed; derive its v3 references with this builder only "
            "at the single sanctioned unseal."
        ),
        "sources": {}, "artifact_sha256": {}, "counts": {},
    }
    for split in splits:
        source = f"references/{split}.jsonl"
        raw = (root / source).read_bytes()
        if _sha(raw) != report["artifact_sha256"][source]:
            raise ValueError(f"sealed v1 reference drift: {source}")
        rows = [build_reference(row) for row in read_jsonl(root / source)]
        data = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ).encode()
        target = out_dir / f"{split}.jsonl"
        if target.exists() and target.read_bytes() != data:
            raise ValueError(f"refusing to overwrite differing {target}")
        target.write_bytes(data)
        manifest["sources"][source] = report["artifact_sha256"][source]
        manifest["artifact_sha256"][f"references-v3/{split}.jsonl"] = _sha(data)
        counts: dict[str, Any] = {"rows": len(rows), "categories": {}, "corrected": 0}
        for row in rows:
            terms = row["v3_contract"]
            counts["categories"][terms["category"]] = (
                counts["categories"].get(terms["category"], 0) + 1
            )
            counts["corrected"] += bool(terms["corrections"])
        manifest["counts"][split] = counts
    path = out_dir / "manifest.json"
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise ValueError("refusing to overwrite differing references-v3 manifest")
    path.write_text(text, encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(build(args.repo)["counts"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
