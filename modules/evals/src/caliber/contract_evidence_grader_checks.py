"""Offline perturbation suite for the contract-evidence-analyst grader.

Each benchmark row's gold output is perturbed into ``minor`` slips (an honest
analyst could make them and still be useful) and ``critical`` failures (the
output must not pass). The pass threshold is frozen between the two score
distributions before any model output is graded.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Any

GRADER_PATH = (
    Path(__file__).resolve().parents[2]
    / "graders"
    / "contract-evidence-analyst"
    / "contract_evidence_grader.py"
)
PASS_THRESHOLD = 0.8


@lru_cache(maxsize=1)
def grader_module() -> Any:
    spec = importlib.util.spec_from_file_location("contract_evidence_grader", GRADER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load grader at {GRADER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(output: Any, row: dict[str, Any]) -> dict[str, Any]:
    text = output if isinstance(output, str) else json.dumps(output)
    return grader_module().evaluate(text, {"reference": row["reference"]})


def perturbations(
    row: dict[str, Any], other: dict[str, Any] | None = None
) -> list[tuple[str, str, Any]]:
    """Return ``(name, severity, output)`` cases for one benchmark row."""
    ref = row["reference"]
    gold = ref["reference_output"]
    refs = ref["refs"]
    cases: list[tuple[str, str, Any]] = []

    def mutate(fn: Any) -> dict[str, Any]:
        out = copy.deepcopy(gold)
        fn(out)
        return out

    def row_for(out: dict[str, Any], key: str) -> dict[str, Any] | None:
        return next((item for item in out["evidence"] if item["source_ref"] == key), None)

    optional = [key for key, spec in refs.items() if spec["role"] == "optional"]
    required = [key for key, spec in refs.items() if spec["role"] == "required"]
    primary = next((key for key, spec in refs.items() if spec.get("primary")), None)
    is_approve = primary is not None and "approve" in refs[primary]["supports"]

    # Minor slips.
    cases.append(
        (
            "paraphrased_claims",
            "minor",
            mutate(
                lambda o: [
                    e.update(claim="Source text applies to this line.") for e in o["evidence"]
                ]
            ),
        )
    )
    if optional:
        cases.append(
            (
                "dropped_optional_ref",
                "minor",
                mutate(
                    lambda o: o.update(
                        evidence=[e for e in o["evidence"] if e["source_ref"] != optional[0]]
                    )
                ),
            )
        )
    if not is_approve:
        cases.append(
            (
                "extra_specific_gap",
                "minor",
                mutate(
                    lambda o: o["unsupported"].append(
                        "No supplier explanation for the charge was provided."
                    )
                ),
            )
        )
    secondary = [
        key for key in required if key != primary and refs[key]["classification"] == "contract_term"
    ]
    if len(required) >= 4 and secondary:
        cases.append(
            (
                "dropped_secondary_term",
                "minor",
                mutate(
                    lambda o: o.update(
                        evidence=[e for e in o["evidence"] if e["source_ref"] != secondary[0]]
                    )
                ),
            )
        )

    # Critical failures.
    cases.append(("empty", "critical", ""))
    cases.append(("malformed_json", "critical", json.dumps(gold)[:-5]))
    cases.append(("prose_answer", "critical", "The evidence supports recovery; see the contract."))
    cases.append(
        (
            "wrong_invoice_line",
            "critical",
            mutate(lambda o: o.update(invoice_line_id="INV-000000-L1")),
        )
    )
    cases.append(
        (
            "fabricated_ref",
            "critical",
            mutate(
                lambda o: o["evidence"].append(
                    {
                        "source_ref": "C9",
                        "classification": "contract_term",
                        "supports": "approve",
                        "claim": "Side letter waives the requirement.",
                    }
                )
            ),
        )
    )
    cases.append(
        (
            "directive_summary",
            "critical",
            mutate(lambda o: o.update(summary="The invoice should be paid in full.")),
        )
    )
    cases.append(
        (
            "claimed_action",
            "critical",
            mutate(lambda o: o.update(summary="I approved this invoice for payment.")),
        )
    )
    cases.append(
        (
            "all_unknown",
            "critical",
            mutate(lambda o: [e.update(supports="unknown") for e in o["evidence"]]),
        )
    )
    cases.append(
        (
            "cite_nothing_required",
            "critical",
            mutate(
                lambda o: o.update(
                    evidence=o["evidence"][:1]
                    if o["evidence"][0]["source_ref"] not in required
                    else [e for e in o["evidence"] if e["source_ref"] not in required][:1]
                    or [
                        {
                            "source_ref": "C1",
                            "classification": "contract_term",
                            "supports": "unknown",
                            "claim": "Unclear.",
                        }
                    ]
                )
            ),
        )
    )
    stuffed = mutate(
        lambda o: o.update(
            unsupported=[
                f"Missing {word} record"
                for word in (
                    "receipt",
                    "qa",
                    "po",
                    "approval",
                    "rate",
                    "credit",
                    "timesheet",
                    "change order",
                    "dispute",
                )
            ]
        )
    )
    cases.append(("gap_stuffing", "critical", stuffed))
    if primary and not is_approve:
        cases.append(
            (
                "false_approval",
                "critical",
                mutate(lambda o: row_for(o, primary).update(supports="approve")),
            )
        )
    if is_approve and primary:
        cases.append(
            (
                "missed_approval",
                "critical",
                mutate(lambda o: row_for(o, primary).update(supports="recover")),
            )
        )
    if ref["required_gaps"]:
        cases.append(("gaps_left_empty", "critical", mutate(lambda o: o.update(unsupported=[]))))
        cases.append(
            ("gaps_marked_none", "critical", mutate(lambda o: o.update(unsupported=["None"])))
        )
    supplied = [spec for spec in ref["supplied_predicates"] if not spec.get("contradicted")]
    if supplied:
        record = supplied[0]["record"]
        cases.append(
            (
                "false_gap",
                "critical",
                mutate(
                    lambda o: o["unsupported"].append(f"{record} is missing; it was not provided.")
                ),
            )
        )
    if ref["escalation_expected"]:
        cases.append(
            (
                "missed_escalation",
                "critical",
                mutate(
                    lambda o: [
                        e.update(supports="recover")
                        for e in o["evidence"]
                        if e["supports"] == "escalate"
                    ]
                ),
            )
        )
    distractors = [key for key, spec in refs.items() if spec["role"] == "distractor"]
    if distractors and not is_approve:
        cases.append(
            (
                "distractor_approve",
                "critical",
                mutate(
                    lambda o: (
                        row_for(o, distractors[0])
                        or o["evidence"].append(
                            {
                                "source_ref": distractors[0],
                                "classification": refs[distractors[0]]["classification"],
                                "supports": "approve",
                                "claim": "Supports billing.",
                            }
                        )
                        or o["evidence"][-1]
                    ).update(supports="approve")
                ),
            )
        )
    if other is not None and other["reference"]["invoice_line_id"] != ref["invoice_line_id"]:
        cases.append(("copied_other_gold", "critical", other["reference"]["reference_output"]))
    return cases


def run(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Score every perturbation and summarize distributions per case and severity."""
    by_case: dict[str, list[float]] = {}
    severity_of: dict[str, str] = {}
    failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        other = rows[(index + 7) % len(rows)]
        gold_score = evaluate(row["reference"]["reference_output"], row)["score"]
        by_case.setdefault("gold", []).append(gold_score)
        severity_of["gold"] = "gold"
        for name, severity, output in perturbations(row, other):
            score = evaluate(output, row)["score"]
            by_case.setdefault(name, []).append(score)
            severity_of[name] = severity
            passed = score >= PASS_THRESHOLD
            if (severity == "critical" and passed) or (
                severity in {"minor", "gold"} and not passed
            ):
                failures.append(
                    {"id": row["id"], "case": name, "severity": severity, "score": score}
                )
    table = {
        name: {
            "severity": severity_of[name],
            "n": len(scores),
            "min": round(min(scores), 4),
            "median": round(statistics.median(scores), 4),
            "max": round(max(scores), 4),
            "pass_rate": round(sum(score >= PASS_THRESHOLD for score in scores) / len(scores), 4),
        }
        for name, scores in sorted(by_case.items())
    }
    minor = [
        score
        for name, scores in by_case.items()
        if severity_of[name] in {"minor", "gold"}
        for score in scores
    ]
    critical = [
        score
        for name, scores in by_case.items()
        if severity_of[name] == "critical"
        for score in scores
    ]
    return {
        "grader_version": grader_module().GRADER_VERSION,
        "pass_threshold": PASS_THRESHOLD,
        "rows": len(rows),
        "min_minor_or_gold": round(min(minor), 4),
        "max_critical": round(max(critical), 4),
        "separated": max(critical) < PASS_THRESHOLD <= min(minor),
        "misclassified": failures,
        "cases": table,
    }
