"""Validate a Foundry-style agent eval config (eval.yaml + dataset + rubric).

This targets `azd ai agent eval` style configs such as
`modules/agents/contract-policy-expert/eval.yaml`: a YAML file that
references a dataset directory and one or more evaluator rubric-dimension
JSON files. Caliber treats these assets as read-only evidence to validate and
hash for lineage, not as something it generates or mutates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REQUIRED_TOP_LEVEL_FIELDS = ("name", "agent", "dataset_reference", "evaluators")
REQUIRED_DIMENSION_FIELDS = ("id", "description", "weight")


def validate_eval_config(eval_config_path: Path) -> dict[str, Any]:
    """Validate structural consistency of an eval.yaml and everything it references."""
    if not eval_config_path.exists():
        raise ValueError(f"eval config does not exist: {eval_config_path}")

    config = _load_yaml(eval_config_path)
    base_dir = eval_config_path.parent

    missing_fields = [key for key in REQUIRED_TOP_LEVEL_FIELDS if key not in config]
    checks = [
        _check(
            "required_fields",
            not missing_fields,
            "eval config must include: " + ", ".join(REQUIRED_TOP_LEVEL_FIELDS)
            if missing_fields
            else "all required top-level fields are present.",
        )
    ]

    agent = config.get("agent")
    agent_name = agent.get("name", "") if isinstance(agent, dict) else ""
    checks.append(
        _check(
            "agent_name_present",
            bool(agent_name),
            "agent.name must be set." if not agent_name else f"agent.name is '{agent_name}'.",
        )
    )

    dataset_reference = config.get("dataset_reference")
    dataset_local_uri = (
        dataset_reference.get("local_uri") if isinstance(dataset_reference, dict) else None
    )
    dataset_dir = _resolve_local_uri(base_dir, dataset_local_uri)
    dataset_files = _dataset_files(dataset_dir) if dataset_dir else []
    checks.append(
        _check(
            "dataset_reference_resolves",
            bool(dataset_files),
            f"dataset_reference.local_uri resolved to {len(dataset_files)} file(s)."
            if dataset_files
            else f"dataset_reference.local_uri did not resolve to any files: {dataset_dir}",
        )
    )

    evaluators = config.get("evaluators")
    evaluator_results = [
        _validate_evaluator(base_dir, evaluator)
        for evaluator in (evaluators if isinstance(evaluators, list) else [])
    ]
    checks.append(
        _check(
            "evaluators_present",
            bool(evaluator_results),
            "eval config must declare at least one evaluator."
            if not evaluator_results
            else f"{len(evaluator_results)} evaluator(s) declared.",
        )
    )
    checks.append(
        _check(
            "evaluators_resolve",
            bool(evaluator_results) and all(item["exists"] for item in evaluator_results),
            "every evaluator local_uri resolved to an existing rubric file."
            if evaluator_results and all(item["exists"] for item in evaluator_results)
            else "at least one evaluator local_uri did not resolve to an existing rubric file.",
        )
    )

    rubric_issues = [issue for item in evaluator_results for issue in item.get("issues", [])]
    checks.append(
        _check(
            "rubric_dimensions_valid",
            not rubric_issues,
            "every rubric dimension has id, description, and a positive weight."
            if not rubric_issues
            else f"{len(rubric_issues)} rubric dimension issue(s) found.",
        )
    )

    ok = all(check["ok"] for check in checks)
    return {
        "path": str(eval_config_path),
        "ok": ok,
        "agent": agent_name,
        "dataset": {
            "local_uri": dataset_local_uri,
            "files": [str(path) for path in dataset_files],
        },
        "evaluators": evaluator_results,
        "checks": checks,
        "rubric_issues": rubric_issues,
    }


def _dataset_files(dataset_path: Path) -> list[Path]:
    if dataset_path.is_file():
        return [dataset_path]
    if dataset_path.is_dir():
        return sorted(dataset_path.glob("*.jsonl"))
    return []


def _resolve_local_uri(base_dir: Path, local_uri: str | None) -> Path | None:
    """Resolve a `local_uri` from eval.yaml relative to base_dir.

    Some eval configs (authored on Windows tooling) use backslash path
    separators, e.g. `evaluators\\foo\\rubric_dimensions.json`. Normalize to
    the platform separator so resolution works on macOS/Linux CI too.
    """
    if not local_uri:
        return None
    normalized = local_uri.replace("\\", "/")
    return base_dir / normalized


def _validate_evaluator(base_dir: Path, evaluator: Any) -> dict[str, Any]:
    name = evaluator.get("name", "") if isinstance(evaluator, dict) else ""
    local_uri = evaluator.get("local_uri") if isinstance(evaluator, dict) else None
    path = _resolve_local_uri(base_dir, local_uri)
    exists = bool(path and path.exists())

    dimensions: list[Any] = []
    issues: list[str] = []
    if exists:
        try:
            dimensions = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            issues.append(f"{path}: invalid JSON")
            dimensions = []
        if not isinstance(dimensions, list) or not dimensions:
            issues.append(f"{path}: rubric dimensions must be a non-empty JSON array")
            dimensions = []
    elif local_uri:
        issues.append(f"evaluator '{name}' local_uri does not resolve: {path}")

    weight_total = 0.0
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            issues.append(f"evaluator '{name}': rubric dimension must be a JSON object")
            continue
        missing = [key for key in REQUIRED_DIMENSION_FIELDS if key not in dimension]
        if missing:
            dimension_id = dimension.get("id", "<unknown>")
            issues.append(f"evaluator '{name}' dimension '{dimension_id}': missing {missing}")
            continue
        weight = dimension.get("weight")
        if not isinstance(weight, int | float) or weight <= 0:
            issues.append(
                f"evaluator '{name}' dimension '{dimension['id']}': weight must be a "
                "positive number"
            )
            continue
        weight_total += float(weight)

    return {
        "name": name,
        "local_uri": local_uri,
        "path": str(path) if path else None,
        "exists": exists,
        "dimension_count": len(dimensions),
        "weight_total": weight_total,
        "issues": issues,
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only without PyYAML installed
        raise ValueError(
            "PyYAML is required to validate eval configs; install it with `uv add pyyaml`"
        ) from exc

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"eval config must be a YAML mapping: {path}")
    return data


def _check(name: str, ok: bool, message: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "message": message}
