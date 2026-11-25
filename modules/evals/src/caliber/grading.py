from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any, Protocol


class Grader(Protocol):
    def __call__(self, sample: dict[str, Any], item: dict[str, Any]) -> float:
        """Return a score from 0.0 to 1.0."""


def require_score_range(score: float) -> float:
    if not math.isfinite(score) or score < 0.0 or score > 1.0:
        raise ValueError(f"grader score must be between 0.0 and 1.0, got {score}")
    return score


def load_grader(path: Path) -> Grader:
    if not path.exists():
        raise ValueError(f"grader file does not exist: {path}")
    spec = importlib.util.spec_from_file_location("caliber_dynamic_grader", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load grader: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    grade = getattr(module, "grade", None)
    if not callable(grade):
        raise ValueError(f"grader must define callable grade(sample, item): {path}")
    return grade
