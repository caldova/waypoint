"""Tests for caliber.eval_assets: structural validation of eval.yaml + dataset + rubric."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caliber.eval_assets import validate_eval_config

VALID_DIMENSIONS = [
    {"id": "grounding", "description": "Cites contract/policy evidence.", "weight": 10},
    {"id": "gaps", "description": "Reports unsupported claims.", "weight": 5},
]


def _write_eval_config(
    base: Path,
    *,
    dataset_local_uri: str = "datasets/sample",
    evaluator_local_uri: str = "evaluators/sample/rubric_dimensions.json",
    dataset_files: list[str] | None = None,
    dimensions: list[dict] | None = None,
    write_rubric: bool = True,
) -> Path:
    dataset_dir = base / "datasets" / "sample"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    for name in dataset_files if dataset_files is not None else ["rows.jsonl"]:
        (dataset_dir / name).write_text('{"input": {}, "expected": {}}\n', encoding="utf-8")

    if write_rubric:
        rubric_path = base / "evaluators" / "sample" / "rubric_dimensions.json"
        rubric_path.parent.mkdir(parents=True, exist_ok=True)
        rubric_path.write_text(
            json.dumps(dimensions if dimensions is not None else VALID_DIMENSIONS),
            encoding="utf-8",
        )

    eval_config = base / "eval.yaml"
    eval_config.write_text(
        f"""
name: sample-eval
agent:
    name: sample-agent
    kind: hosted
dataset_reference:
    name: sample
    version: "1"
    local_uri: {dataset_local_uri}
evaluators:
    - name: sample
      version: "1"
      local_uri: {evaluator_local_uri}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return eval_config


def test_validate_eval_config_passes_for_well_formed_assets(tmp_path: Path) -> None:
    eval_config = _write_eval_config(tmp_path)
    result = validate_eval_config(eval_config)
    assert result["ok"] is True
    assert result["agent"] == "sample-agent"
    assert result["dataset"]["files"]
    assert result["evaluators"][0]["exists"] is True
    assert result["evaluators"][0]["dimension_count"] == 2
    assert result["evaluators"][0]["weight_total"] == 15
    assert result["rubric_issues"] == []


def test_validate_eval_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        validate_eval_config(tmp_path / "eval.yaml")


def test_validate_eval_config_flags_missing_dataset(tmp_path: Path) -> None:
    eval_config = _write_eval_config(tmp_path, dataset_local_uri="datasets/does-not-exist")
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    dataset_check = next(c for c in result["checks"] if c["name"] == "dataset_reference_resolves")
    assert dataset_check["ok"] is False


def test_validate_eval_config_flags_missing_evaluator(tmp_path: Path) -> None:
    eval_config = _write_eval_config(tmp_path, write_rubric=False)
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    assert result["evaluators"][0]["exists"] is False
    assert result["evaluators"][0]["issues"]


def test_validate_eval_config_flags_empty_rubric(tmp_path: Path) -> None:
    eval_config = _write_eval_config(tmp_path, dimensions=[])
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    assert any("non-empty" in issue for issue in result["rubric_issues"])


def test_validate_eval_config_flags_dimension_missing_fields(tmp_path: Path) -> None:
    eval_config = _write_eval_config(
        tmp_path, dimensions=[{"id": "grounding", "description": "Missing weight"}]
    )
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    assert any("missing" in issue for issue in result["rubric_issues"])


def test_validate_eval_config_flags_non_positive_weight(tmp_path: Path) -> None:
    eval_config = _write_eval_config(
        tmp_path,
        dimensions=[{"id": "grounding", "description": "Bad weight", "weight": 0}],
    )
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    assert any("positive number" in issue for issue in result["rubric_issues"])


def test_validate_eval_config_flags_invalid_json_rubric(tmp_path: Path) -> None:
    eval_config = _write_eval_config(tmp_path)
    rubric_path = tmp_path / "evaluators" / "sample" / "rubric_dimensions.json"
    rubric_path.write_text("{not valid json", encoding="utf-8")
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    assert any("invalid JSON" in issue for issue in result["rubric_issues"])


def test_validate_eval_config_flags_missing_required_top_level_fields(tmp_path: Path) -> None:
    eval_config = tmp_path / "eval.yaml"
    eval_config.write_text("name: incomplete-eval\n", encoding="utf-8")
    result = validate_eval_config(eval_config)
    assert result["ok"] is False
    required_check = next(c for c in result["checks"] if c["name"] == "required_fields")
    assert required_check["ok"] is False


def test_validate_eval_config_handles_windows_style_backslash_local_uri(tmp_path: Path) -> None:
    # Mirrors real Caldova eval configs authored with backslash path separators,
    # e.g. modules/agents/contract-policy-expert/eval.yaml.
    eval_config = _write_eval_config(
        tmp_path,
        dataset_local_uri=r"datasets\sample",
        evaluator_local_uri=r"evaluators\sample\rubric_dimensions.json",
    )
    result = validate_eval_config(eval_config)
    assert result["ok"] is True
    assert result["evaluators"][0]["exists"] is True


def test_validate_eval_config_against_real_contract_policy_expert_asset() -> None:
    # Guards against regressions in the actual in-scope eval asset this
    # command targets: modules/agents/contract-policy-expert/eval.yaml.
    modules_dir = Path(__file__).resolve().parents[2]
    eval_config = (
        modules_dir / "agents" / "agents" / "contract-policy-expert" / "eval.yaml"
    )
    if not eval_config.exists():
        pytest.skip(f"contract-policy-expert eval.yaml not found at {eval_config}")
    result = validate_eval_config(eval_config)
    assert result["ok"] is True
    assert result["agent"] == "contract-policy-expert"
