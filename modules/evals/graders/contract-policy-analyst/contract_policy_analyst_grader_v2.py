"""Versioned correction for judge approval flags; the v1 source remains frozen."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from typing import Any

BASE_PATH = Path(__file__).with_name("contract_policy_analyst_grader.py")
BASE_SHA256 = "267d5f6c7cebe3baaf8b243d97ea6bc4a8befbdb95b9ee85a3a07f8bc5bf6f62"
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA256:
    raise ValueError("Frozen analyst grader v1 changed; create a new grader revision.")
spec = importlib.util.spec_from_file_location("_contract_policy_analyst_grader_v2_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise ValueError("Cannot load frozen analyst grader v1.")
_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_base)

VERSION = "contract-policy-analyst-grader-v2"
CAPS = {**_base.CAPS, "false_approval": 0.2, "missed_approval": 0.35}
_base.CAPS = CAPS
_base.VERSION = VERSION


def evaluate(sample: Any, item: dict[str, Any]) -> dict[str, Any]:
    return _base.evaluate(sample, item)


def grade(sample: Any, item: dict[str, Any]) -> float:
    return float(evaluate(sample, item)["score"])
