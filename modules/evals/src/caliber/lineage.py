"""Quality evidence lineage: immutable, hash-anchored snapshots for FT/eval gates.

A lineage snapshot is a versioned, content-hashed record of everything that
went into one quality-evidence claim (an eval run, an optimizer candidate, an
RFT job): the agent prompt/config, the dataset, the rubric/eval config, the
grader, and the model/deployment, plus the source commit, a non-secret
environment label, timestamps, and an operation id.

Snapshots are appended to a JSONL ledger and are never overwritten or
mutated in place. `verify_snapshot` recomputes hashes from the *current*
source files and reports whether a snapshot is still `current`, has gone
`stale`, or is `reference_only` (a historical record whose raw sources are
no longer available to re-hash, so freshness cannot be proven either way).

This module never applies a candidate, deploys a checkpoint, promotes a
model, or mutates anything outside its own ledger file.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .paths import git_sha

SCHEMA_VERSION = "1"

HASH_COMPONENTS = (
    "prompt_config",
    "dataset",
    "rubric_eval_config",
    "grader",
    "model_deployment",
)

REVIEW_STATUSES = {"draft", "accepted", "rejected", "superseded"}

VERIFY_STATUSES = {"current", "stale", "reference_only", "unverifiable"}


def sha256_file(path: Path) -> str:
    """Hash a file's bytes. Raises if the file does not exist."""
    if not path.exists():
        raise ValueError(f"file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"path is not a file: {path}")
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_path_component(label: str, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"label": label, "identifier": "", "sha256": None, "available": False}
    resolved = path.expanduser()
    if not resolved.exists() or not resolved.is_file():
        return {"label": label, "identifier": str(path), "sha256": None, "available": False}
    return {
        "label": label,
        "identifier": str(path),
        "sha256": sha256_file(resolved),
        "available": True,
    }


def _hash_identifier_component(label: str, identifier: str | None) -> dict[str, Any]:
    if not identifier or not identifier.strip():
        return {"label": label, "identifier": "", "sha256": None, "available": False}
    return {
        "label": label,
        "identifier": identifier,
        "sha256": sha256_text(identifier),
        "available": True,
    }


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_ledger_path(agent: str) -> Path:
    return Path("runs") / "lineage" / agent / "manifest.jsonl"


def build_snapshot(
    *,
    agent: str,
    operation_id: str,
    operation_kind: str,
    review_status: str = "draft",
    environment: str = "local",
    prompt_config_path: Path | None = None,
    dataset_path: Path | None = None,
    rubric_eval_config_path: Path | None = None,
    grader_path: Path | None = None,
    model_deployment: str | None = None,
    base_model: str | None = None,
    source_path: Path | None = None,
    reference_only: bool = False,
    notes: str = "",
    metrics: dict[str, Any] | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one immutable quality-evidence lineage snapshot.

    Every hashable component is optional individually (some operations do not
    touch every component), but at least one must be supplied so the snapshot
    is anchored to something concrete.
    """
    if not agent.strip():
        raise ValueError("agent is required")
    if not operation_id.strip():
        raise ValueError("operation_id is required")
    if not operation_kind.strip():
        raise ValueError("operation_kind is required")
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"review_status must be one of {sorted(REVIEW_STATUSES)}")

    hashes = {
        "prompt_config": _hash_path_component("prompt_config", prompt_config_path),
        "dataset": _hash_path_component("dataset", dataset_path),
        "rubric_eval_config": _hash_path_component("rubric_eval_config", rubric_eval_config_path),
        "grader": _hash_path_component("grader", grader_path),
        "model_deployment": _hash_identifier_component("model_deployment", model_deployment),
    }
    if not any(component["available"] for component in hashes.values()):
        raise ValueError(
            "at least one of prompt_config, dataset, rubric_eval_config, grader, or "
            "model_deployment must be supplied to anchor the snapshot"
        )

    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "agent": agent,
        "operation_id": operation_id,
        "operation_kind": operation_kind,
        "review_status": review_status,
        "environment": environment,
        "reference_only": bool(reference_only),
        "created_at": _now_iso(),
        "source_commit": git_sha(source_path or Path.cwd()),
        "hashes": hashes,
        "model": {"base_model": base_model, "deployment": model_deployment},
        "metrics": metrics or {},
        "approvals": approvals or [],
        "notes": notes,
    }
    body["snapshot_id"] = _snapshot_id(body)
    return body


def _snapshot_id(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_snapshot(ledger_path: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Append a snapshot to the ledger. Never overwrites or rewrites existing lines."""
    if "snapshot_id" not in snapshot:
        raise ValueError("snapshot must include snapshot_id; build it with build_snapshot()")

    existing_ids = {row.get("snapshot_id") for row in read_snapshots(ledger_path)}
    if snapshot["snapshot_id"] in existing_ids:
        raise ValueError(
            f"snapshot {snapshot['snapshot_id']} already exists in {ledger_path}; "
            "lineage snapshots are immutable and cannot be overwritten"
        )

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True) + "\n")
    return snapshot


def read_snapshots(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{ledger_path}:{line_number}: invalid lineage snapshot JSON") from exc
    return rows


def _sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row.get("created_at") or "", row.get("snapshot_id") or "")


def latest_snapshot(ledger_path: Path, *, agent: str | None = None) -> dict[str, Any] | None:
    rows = read_snapshots(ledger_path)
    if agent:
        rows = [row for row in rows if row.get("agent") == agent]
    if not rows:
        return None
    return sorted(rows, key=_sort_key)[-1]


def find_snapshot(ledger_path: Path, snapshot_id: str) -> dict[str, Any] | None:
    for row in read_snapshots(ledger_path):
        if row.get("snapshot_id") == snapshot_id:
            return row
    return None


def verify_snapshot(
    snapshot: dict[str, Any],
    *,
    prompt_config_path: Path | None = None,
    dataset_path: Path | None = None,
    rubric_eval_config_path: Path | None = None,
    grader_path: Path | None = None,
    model_deployment: str | None = None,
) -> dict[str, Any]:
    """Recompute hashes from the current sources and classify freshness.

    - `reference_only`: the snapshot is explicitly flagged as a historical
      reference whose raw sources are gone; freshness cannot be proven either
      way, so it is never reported as `current`.
    - `unverifiable`: no current source was supplied to compare against.
    - `current`: every supplied current source hash matches the stored hash.
    - `stale`: at least one supplied current source hash differs from stored.
    """
    if snapshot.get("reference_only"):
        return {
            "status": "reference_only",
            "snapshot_id": snapshot.get("snapshot_id"),
            "reason": (
                "snapshot is marked reference_only; source artifacts are not available "
                "to re-hash, so it can never be reported as current"
            ),
            "components": {},
        }

    current = {
        "prompt_config": _hash_path_component("prompt_config", prompt_config_path),
        "dataset": _hash_path_component("dataset", dataset_path),
        "rubric_eval_config": _hash_path_component("rubric_eval_config", rubric_eval_config_path),
        "grader": _hash_path_component("grader", grader_path),
        "model_deployment": _hash_identifier_component("model_deployment", model_deployment),
    }
    stored = snapshot.get("hashes", {})

    components: dict[str, Any] = {}
    any_supplied = False
    all_match = True
    for key in HASH_COMPONENTS:
        stored_component = stored.get(key) or {}
        current_component = current[key]
        supplied = current_component["available"]
        stored_hash = stored_component.get("sha256")
        current_hash = current_component["sha256"]
        matches = None
        if supplied:
            any_supplied = True
            matches = stored_hash is not None and stored_hash == current_hash
            if not matches:
                all_match = False
        components[key] = {
            "stored_sha256": stored_hash,
            "current_sha256": current_hash,
            "supplied": supplied,
            "matches": matches,
        }

    if not any_supplied:
        status = "unverifiable"
    elif all_match:
        status = "current"
    else:
        status = "stale"

    return {"status": status, "snapshot_id": snapshot.get("snapshot_id"), "components": components}


def load_reference_snapshots(path: Path) -> list[dict[str, Any]]:
    """Load a committed reference-lineage file (a schema-conformant snapshot array).

    Every snapshot loaded this way must set `reference_only: true`; this is a
    hard requirement so committed historical evidence can never silently be
    reported as freshly verified.
    """
    if not path.exists():
        raise ValueError(f"reference lineage file does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    snapshots = data.get("snapshots") if isinstance(data, dict) else data
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError(f"reference lineage file must contain a non-empty snapshot list: {path}")
    for snapshot in snapshots:
        if not snapshot.get("reference_only"):
            raise ValueError(
                f"reference lineage file entries must set reference_only: true: {path}"
            )
    return snapshots


def lineage_report(
    ledger_path: Path,
    *,
    agent: str | None = None,
    reference_path: Path | None = None,
) -> dict[str, Any]:
    """Summarize ledger + optional committed reference snapshots per agent."""
    rows = read_snapshots(ledger_path)
    reference_rows = load_reference_snapshots(reference_path) if reference_path else []
    all_rows = rows + reference_rows
    if agent:
        all_rows = [row for row in all_rows if row.get("agent") == agent]

    agents = sorted({row.get("agent") for row in all_rows if row.get("agent")})
    summary = []
    for agent_name in agents:
        agent_rows = [row for row in all_rows if row.get("agent") == agent_name]
        live_rows = [row for row in agent_rows if not row.get("reference_only")]
        reference_only_rows = [row for row in agent_rows if row.get("reference_only")]
        latest_live = _latest(live_rows)
        latest_reference = _latest(reference_only_rows)
        latest = latest_live or latest_reference
        summary.append(
            {
                "agent": agent_name,
                "snapshot_count": len(agent_rows),
                "live_snapshot_count": len(live_rows),
                "reference_snapshot_count": len(reference_only_rows),
                "latest_snapshot_id": latest.get("snapshot_id") if latest else None,
                "latest_operation_id": latest.get("operation_id") if latest else None,
                "latest_operation_kind": latest.get("operation_kind") if latest else None,
                "latest_review_status": latest.get("review_status") if latest else None,
                "latest_reference_only": bool(latest.get("reference_only")) if latest else None,
                "latest_created_at": latest.get("created_at") if latest else None,
                "status": (
                    "reference_only"
                    if latest and latest.get("reference_only")
                    else "current_pending_verify"
                    if latest
                    else "missing"
                ),
            }
        )
    return {
        "ledger_path": str(ledger_path),
        "reference_path": str(reference_path) if reference_path else None,
        "total_snapshots": len(all_rows),
        "agents": summary,
    }


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=_sort_key)[-1]
