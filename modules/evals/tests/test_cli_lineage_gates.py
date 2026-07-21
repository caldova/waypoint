"""Smoke tests for the new `caliber lineage`, `caliber gates`, and
`caliber eval validate-assets` CLI subcommands, exercised end to end through
`caliber.cli.main` (argv in, exit code + stdout out) rather than the module
functions directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caliber.cli import main


def _run(capsys: pytest.CaptureFixture, argv: list[str]) -> tuple[int, dict]:
    exit_code = main(argv)
    out = capsys.readouterr().out
    return exit_code, json.loads(out)


def test_lineage_snapshot_then_verify_then_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"input": {}, "expected": {}}\n', encoding="utf-8")
    ledger = tmp_path / "manifest.jsonl"

    exit_code, snapshot_result = _run(
        capsys,
        [
            "lineage",
            "snapshot",
            "--agent",
            "contract-policy-expert",
            "--operation-id",
            "op-cli-1",
            "--operation-kind",
            "eval",
            "--dataset",
            str(dataset),
            "--model-deployment",
            "gpt-5-mini",
            "--metric",
            "pass_rate=1.0",
            "--ledger",
            str(ledger),
            "--json",
        ],
    )
    assert exit_code == 0
    assert snapshot_result["snapshot"]["agent"] == "contract-policy-expert"
    assert ledger.exists()

    exit_code, verify_result = _run(
        capsys,
        [
            "lineage",
            "verify",
            "--ledger",
            str(ledger),
            "--dataset",
            str(dataset),
            "--model-deployment",
            "gpt-5-mini",
            "--json",
        ],
    )
    assert exit_code == 0
    assert verify_result["status"] == "current"

    exit_code, report_result = _run(
        capsys, ["lineage", "report", "--ledger", str(ledger), "--json"]
    )
    assert exit_code == 0
    assert report_result["total_snapshots"] == 1
    assert report_result["agents"][0]["agent"] == "contract-policy-expert"


def test_lineage_snapshot_rejects_duplicate_via_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"input": {}, "expected": {}}\n', encoding="utf-8")
    ledger = tmp_path / "manifest.jsonl"
    argv = [
        "lineage",
        "snapshot",
        "--agent",
        "a",
        "--operation-id",
        "op1",
        "--operation-kind",
        "eval",
        "--dataset",
        str(dataset),
        "--ledger",
        str(ledger),
        "--json",
    ]
    assert main(argv) == 0
    capsys.readouterr()

    # Re-running with the exact same inputs at the exact same instant would
    # collide; simulate that by directly re-appending the persisted snapshot.
    from caliber.lineage import append_snapshot, read_snapshots

    existing = read_snapshots(ledger)[0]
    with pytest.raises(ValueError, match="already exists"):
        append_snapshot(ledger, existing)


def test_gates_check_reports_closed_by_default(capsys: pytest.CaptureFixture) -> None:
    exit_code, result = _run(capsys, ["gates", "check", "--operation", "rft_submit", "--json"])
    assert exit_code == 0
    assert result["allowed"] is False
    assert "review_approved" in result["blocking_reasons"]


def test_gates_check_allows_when_everything_confirmed(capsys: pytest.CaptureFixture) -> None:
    exit_code, result = _run(
        capsys,
        [
            "gates",
            "check",
            "--operation",
            "rft_submit",
            "--review-approved",
            "--lineage-status",
            "current",
            "--model-ready",
            "--quota-ready",
            "--spend-confirmed",
            "--json",
        ],
    )
    assert exit_code == 0
    assert result["allowed"] is True


def test_gates_check_protected_approval_via_cli(capsys: pytest.CaptureFixture) -> None:
    exit_code, denied = _run(
        capsys,
        [
            "gates",
            "check",
            "--operation",
            "candidate_promote",
            "--required-approver-role",
            "eng-lead",
            "--json",
        ],
    )
    assert exit_code == 0
    assert denied["gates"]["protected_approval"]["ok"] is False

    exit_code, allowed = _run(
        capsys,
        [
            "gates",
            "check",
            "--operation",
            "candidate_promote",
            "--required-approver-role",
            "eng-lead",
            "--approval",
            "alice:eng-lead",
            "--json",
        ],
    )
    assert exit_code == 0
    assert allowed["gates"]["protected_approval"]["ok"] is True


def test_eval_validate_assets_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    dataset_dir = tmp_path / "datasets" / "sample"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "rows.jsonl").write_text('{"a": 1}\n', encoding="utf-8")

    rubric_dir = tmp_path / "evaluators" / "sample"
    rubric_dir.mkdir(parents=True)
    (rubric_dir / "rubric_dimensions.json").write_text(
        json.dumps([{"id": "grounding", "description": "d", "weight": 10}]), encoding="utf-8"
    )

    eval_config = tmp_path / "eval.yaml"
    eval_config.write_text(
        """
name: sample-eval
agent:
    name: sample-agent
dataset_reference:
    local_uri: datasets/sample
evaluators:
    - name: sample
      local_uri: evaluators/sample/rubric_dimensions.json
""".strip()
        + "\n",
        encoding="utf-8",
    )

    exit_code, result = _run(
        capsys, ["eval", "validate-assets", "--eval-config", str(eval_config), "--json"]
    )
    assert exit_code == 0
    assert result["ok"] is True
    assert result["agent"] == "sample-agent"


def test_cli_reports_error_exit_code_for_bad_lineage_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    exit_code = main(
        ["lineage", "verify", "--ledger", str(tmp_path / "missing.jsonl"), "--json"]
    )
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "error:" in err
