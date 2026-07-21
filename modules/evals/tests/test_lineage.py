"""Tests for caliber.lineage: the immutable, hash-anchored quality-evidence ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caliber.lineage import (
    REVIEW_STATUSES,
    VERIFY_STATUSES,
    append_snapshot,
    build_snapshot,
    find_snapshot,
    latest_snapshot,
    lineage_report,
    load_reference_snapshots,
    read_snapshots,
    sha256_file,
    sha256_text,
    verify_snapshot,
)


def test_sha256_file_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("hello lineage", encoding="utf-8")
    assert sha256_file(path) == sha256_text("hello lineage")
    assert len(sha256_file(path)) == 64


def test_sha256_file_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        sha256_file(tmp_path / "missing.txt")


def test_build_snapshot_requires_agent_operation_and_kind(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="agent is required"):
        build_snapshot(agent="", operation_id="op1", operation_kind="eval", dataset_path=dataset)
    with pytest.raises(ValueError, match="operation_id is required"):
        build_snapshot(agent="a", operation_id="", operation_kind="eval", dataset_path=dataset)
    with pytest.raises(ValueError, match="operation_kind is required"):
        build_snapshot(agent="a", operation_id="op1", operation_kind="", dataset_path=dataset)


def test_build_snapshot_requires_at_least_one_hashable_component() -> None:
    with pytest.raises(ValueError, match="at least one of"):
        build_snapshot(agent="a", operation_id="op1", operation_kind="eval")


def test_build_snapshot_rejects_invalid_review_status(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="review_status must be one of"):
        build_snapshot(
            agent="a",
            operation_id="op1",
            operation_kind="eval",
            review_status="not-a-real-status",
            dataset_path=dataset,
        )


def test_build_snapshot_produces_deterministic_schema(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    snapshot = build_snapshot(
        agent="contract-policy-expert",
        operation_id="op1",
        operation_kind="eval",
        dataset_path=dataset,
        model_deployment="gpt-5-mini",
        metrics={"pass_rate": 1.0},
        approvals=[{"approver": "alice", "role": "eng-lead"}],
    )
    assert snapshot["schema_version"] == "1"
    assert snapshot["agent"] == "contract-policy-expert"
    assert snapshot["review_status"] in REVIEW_STATUSES
    assert snapshot["reference_only"] is False
    assert snapshot["hashes"]["dataset"]["available"] is True
    assert snapshot["hashes"]["dataset"]["sha256"] == sha256_file(dataset)
    assert snapshot["hashes"]["prompt_config"]["available"] is False
    assert snapshot["model"]["deployment"] == "gpt-5-mini"
    assert snapshot["metrics"] == {"pass_rate": 1.0}
    assert snapshot["approvals"] == [{"approver": "alice", "role": "eng-lead"}]
    assert "snapshot_id" in snapshot
    assert len(snapshot["snapshot_id"]) == 64


def test_append_snapshot_persists_jsonl_and_is_immutable(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    ledger = tmp_path / "runs" / "lineage" / "agent-a" / "manifest.jsonl"

    snapshot = build_snapshot(
        agent="agent-a", operation_id="op1", operation_kind="eval", dataset_path=dataset
    )
    appended = append_snapshot(ledger, snapshot)
    assert appended == snapshot
    assert ledger.exists()

    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["snapshot_id"] == snapshot["snapshot_id"]

    with pytest.raises(ValueError, match="already exists"):
        append_snapshot(ledger, snapshot)

    # A distinct snapshot for the same agent appends as a new line rather than overwriting.
    other = build_snapshot(
        agent="agent-a", operation_id="op2", operation_kind="eval", dataset_path=dataset
    )
    append_snapshot(ledger, other)
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2


def test_append_snapshot_requires_snapshot_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="snapshot must include snapshot_id"):
        append_snapshot(tmp_path / "manifest.jsonl", {"agent": "a"})


def test_read_snapshots_returns_empty_list_for_missing_ledger(tmp_path: Path) -> None:
    assert read_snapshots(tmp_path / "does-not-exist.jsonl") == []


def test_read_snapshots_raises_on_invalid_json_line(tmp_path: Path) -> None:
    ledger = tmp_path / "manifest.jsonl"
    ledger.write_text("not valid json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid lineage snapshot JSON"):
        read_snapshots(ledger)


def test_latest_and_find_snapshot(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    ledger = tmp_path / "manifest.jsonl"

    first = build_snapshot(
        agent="agent-a", operation_id="op1", operation_kind="eval", dataset_path=dataset
    )
    append_snapshot(ledger, first)
    second = build_snapshot(
        agent="agent-a", operation_id="op2", operation_kind="eval", dataset_path=dataset
    )
    append_snapshot(ledger, second)

    assert latest_snapshot(tmp_path / "missing.jsonl") is None
    latest = latest_snapshot(ledger, agent="agent-a")
    assert latest is not None
    assert latest["operation_id"] in {"op1", "op2"}

    found = find_snapshot(ledger, first["snapshot_id"])
    assert found == first
    assert find_snapshot(ledger, "not-a-real-id") is None


def test_verify_snapshot_current_when_all_supplied_hashes_match(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    snapshot = build_snapshot(
        agent="a",
        operation_id="op1",
        operation_kind="eval",
        dataset_path=dataset,
        model_deployment="gpt-5-mini",
    )
    result = verify_snapshot(snapshot, dataset_path=dataset, model_deployment="gpt-5-mini")
    assert result["status"] == "current"
    assert result["components"]["dataset"]["matches"] is True
    assert result["components"]["model_deployment"]["matches"] is True
    assert result["components"]["prompt_config"]["supplied"] is False


def test_verify_snapshot_stale_when_dataset_changes(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    snapshot = build_snapshot(
        agent="a", operation_id="op1", operation_kind="eval", dataset_path=dataset
    )

    dataset.write_text('{"changed": true}\n', encoding="utf-8")
    result = verify_snapshot(snapshot, dataset_path=dataset)
    assert result["status"] == "stale"
    assert result["components"]["dataset"]["matches"] is False


def test_verify_snapshot_unverifiable_when_nothing_supplied(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    snapshot = build_snapshot(
        agent="a", operation_id="op1", operation_kind="eval", dataset_path=dataset
    )
    result = verify_snapshot(snapshot)
    assert result["status"] == "unverifiable"


def test_verify_snapshot_reference_only_never_reports_current(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    snapshot = build_snapshot(
        agent="a",
        operation_id="op1",
        operation_kind="agent_optimizer",
        dataset_path=dataset,
        reference_only=True,
    )
    # Even with a perfectly matching current source, a reference_only snapshot
    # must never be reported as "current" -- its raw sources are historical.
    result = verify_snapshot(snapshot, dataset_path=dataset)
    assert result["status"] == "reference_only"


def test_verify_status_values_are_exactly_the_documented_set() -> None:
    assert {"current", "stale", "reference_only", "unverifiable"} == VERIFY_STATUSES


def test_load_reference_snapshots_requires_reference_only_true(tmp_path: Path) -> None:
    path = tmp_path / "reference-lineage.json"
    path.write_text(
        json.dumps({"snapshots": [{"agent": "a", "reference_only": False}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="reference_only: true"):
        load_reference_snapshots(path)


def test_load_reference_snapshots_rejects_missing_or_empty_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        load_reference_snapshots(tmp_path / "missing.json")

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"snapshots": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty snapshot list"):
        load_reference_snapshots(empty)


def test_load_reference_snapshots_accepts_conformant_file(tmp_path: Path) -> None:
    path = tmp_path / "reference-lineage.json"
    path.write_text(
        json.dumps(
            {
                "snapshots": [
                    {"agent": "a", "reference_only": True, "snapshot_id": "abc"},
                    {"agent": "a", "reference_only": True, "snapshot_id": "def"},
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = load_reference_snapshots(path)
    assert len(rows) == 2


def test_lineage_report_merges_ledger_and_reference_snapshots(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    ledger = tmp_path / "manifest.jsonl"
    live = build_snapshot(
        agent="agent-a", operation_id="op-live", operation_kind="eval", dataset_path=dataset
    )
    append_snapshot(ledger, live)

    reference_path = tmp_path / "reference-lineage.json"
    reference_path.write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "agent": "agent-a",
                        "operation_id": "op-ref",
                        "operation_kind": "rft",
                        "reference_only": True,
                        "snapshot_id": "ref-1",
                        "review_status": "accepted",
                        "created_at": "2025-01-01T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = lineage_report(ledger, reference_path=reference_path)
    assert report["total_snapshots"] == 2
    assert len(report["agents"]) == 1
    summary = report["agents"][0]
    assert summary["agent"] == "agent-a"
    assert summary["live_snapshot_count"] == 1
    assert summary["reference_snapshot_count"] == 1
    # Live snapshots take precedence for "latest" reporting over reference-only ones.
    assert summary["latest_operation_id"] == "op-live"
    assert summary["status"] == "current_pending_verify"


def test_lineage_report_reports_reference_only_status_when_no_live_snapshots(
    tmp_path: Path,
) -> None:
    reference_path = tmp_path / "reference-lineage.json"
    reference_path.write_text(
        json.dumps(
            {
                "snapshots": [
                    {
                        "agent": "agent-a",
                        "operation_id": "op-ref",
                        "operation_kind": "rft",
                        "reference_only": True,
                        "snapshot_id": "ref-1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    report = lineage_report(tmp_path / "missing-ledger.jsonl", reference_path=reference_path)
    assert report["agents"][0]["status"] == "reference_only"


def test_lineage_report_reports_missing_status_with_no_snapshots(tmp_path: Path) -> None:
    report = lineage_report(tmp_path / "missing-ledger.jsonl")
    assert report["total_snapshots"] == 0
    assert report["agents"] == []
