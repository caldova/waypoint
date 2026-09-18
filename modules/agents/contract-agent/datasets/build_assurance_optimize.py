"""Derive the Agent Optimizer dataset for contract-agent from the corpus.

The Foundry Agent Optimizer scores each row by running the agent on a scalar
``query`` and comparing to a scalar ``ground_truth`` (its dataset schema is
``{query, ground_truth}`` — not the rich ``messages``/dict-``ground_truth`` shape
the fleet-era eval splits use for the custom Python graders).

Every row here is grounded in ``invoice-decisions.json``: the query is the
natural assurance ask for a real corpus invoice, and the ground truth is that
invoice's governed decision plus the corpus summary, verbatim — nothing invented.

Each row also carries a task-level ``criteria`` grounding check. The optimizer's
eval loop is response-scoped (it scores the agent's answer against each
criterion), so ``builtin.tool_call_accuracy`` — which needs the tool trajectory —
can't run there. This criterion recovers the same "decided from evidence, not
from memory" signal in a form the loop supports: it names the invoice's real
corpus ``sources`` and asks the eval model to check the answer is grounded in
them and cites the governing basis.

Re-run this whenever the seed decisions change::

    python datasets/build_assurance_optimize.py

Writes ``assurance-optimize-train.jsonl`` + ``assurance-optimize-validation.jsonl``
next to this script. A stratified 2:1 split keeps every decision state in both.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECISIONS = HERE.parents[2] / "corpus" / "data" / "waypoint" / "invoice-decisions.json"

# The corpus records an accepted invoice as "approved"; the agent's decision
# vocabulary is approve/recover/escalate/review. Normalize so the ground truth
# speaks the agent's own decision language.
_DECISION = {"approved": "approve"}


def _row(decision: dict) -> dict:
    verb = _DECISION.get(decision["status"], decision["status"])
    sources = ", ".join(decision.get("sources", [])) or "the governing contract and policy"
    return {
        "name": decision["invoice_id"],
        "query": f"Assure invoice {decision['invoice_id']} and record your decision.",
        "ground_truth": f"{verb}: {decision['summary']}",
        "criteria": [
            {
                "name": "grounded_in_evidence",
                "instruction": (
                    "The decision must be grounded in the retrieved contract and "
                    f"policy evidence for this invoice ({sources}) and cite the "
                    "governing basis for the outcome. It must not be asserted from "
                    "memory or general knowledge."
                ),
            }
        ],
    }


def build() -> tuple[list[dict], list[dict]]:
    decisions = json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"]
    by_state: dict[str, list[dict]] = defaultdict(list)
    for d in sorted(decisions, key=lambda d: d["invoice_id"]):
        by_state[d["status"]].append(d)

    train: list[dict] = []
    validation: list[dict] = []
    # Every 3rd invoice of each decision state is held out for validation, so
    # both splits carry approve/recover/escalate/review.
    for state_decisions in by_state.values():
        for i, d in enumerate(state_decisions):
            (validation if i % 3 == 2 else train).append(_row(d))
    return train, validation


def _write(rows: list[dict], name: str) -> None:
    path = HERE / name
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    train, validation = build()
    _write(train, "assurance-optimize-train.jsonl")
    _write(validation, "assurance-optimize-validation.jsonl")
