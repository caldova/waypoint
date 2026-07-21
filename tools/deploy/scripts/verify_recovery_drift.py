#!/usr/bin/env python3
"""Verify deployment recovery and build bounded drift-reconciliation plans."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SUCCESS_STATUSES = {"passed", "succeeded", "success"}
COLLECTION_LABELS = {
    "role_assignments": "role assignments",
    "container_apps": "container apps",
    "hosted_agents": "hosted agents",
    "models": "models",
    "fabric_items": "Fabric items",
    "knowledge_bases": "knowledge bases",
    "seed_sets": "seed sets",
}
SENSITIVE_KEY_PARTS = {
    "access_token",
    "access_tokens",
    "account_key",
    "api_key",
    "authorization",
    "client_secret",
    "credential",
    "credentials",
    "connection_string",
    "password",
    "private_key",
    "refresh_token",
    "sas_token",
    "secret",
    "secrets",
    "token",
    "tokens",
}
REDACTED = "[REDACTED]"
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)(accountkey|sharedaccesssignature|clientsecret|password)="),
    re.compile(r"(?i)https?://\S*[?&]sig=[^&\s]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
DRIFT_TYPES = {
    "role_assignment_removal": ("role_assignments", None),
    "hosted_agent_tag_hash_drift": ("hosted_agents", ("state", "tag_hash")),
    "knowledge_base_content_hash_drift": (
        "knowledge_bases",
        ("state", "content_hash"),
    ),
    "seed_count_drift": ("seed_sets", ("state", "record_count")),
}
REQUIRED_DRIFT_TYPES = {*DRIFT_TYPES, "container_app_env_drift"}


class VerificationError(ValueError):
    """Raised when evidence or a drift definition violates the safety contract."""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="Compare baseline, interrupted, and rerun snapshots."
    )
    verify_parser.add_argument("--baseline", type=Path, required=True)
    verify_parser.add_argument("--interrupted", type=Path, required=True)
    verify_parser.add_argument("--rerun", type=Path, required=True)
    verify_parser.add_argument("--scenarios", type=Path, required=True)
    verify_parser.add_argument("--output", type=Path)

    drift_parser = subparsers.add_parser(
        "drift", help="Preview or apply a bounded reconciliation to a JSON snapshot."
    )
    drift_parser.add_argument("--baseline", type=Path, required=True)
    drift_parser.add_argument("--inventory", type=Path, required=True)
    drift_parser.add_argument("--scenarios", type=Path, required=True)
    drift_parser.add_argument("--mode", choices=("preview", "apply"), default="preview")
    drift_parser.add_argument("--confirm")
    drift_parser.add_argument("--output", type=Path)

    sanitize_parser = subparsers.add_parser(
        "sanitize", help="Redact sensitive values from a raw JSON snapshot."
    )
    sanitize_parser.add_argument("--input", type=Path, required=True)
    sanitize_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"Unable to load JSON from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise VerificationError(f"{path} must contain a JSON object.")
    return payload


def _normalized_key(key: str) -> str:
    snake_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", snake_key.casefold()).strip("_")


def _key_is_sensitive(key: str) -> bool:
    normalized = _normalized_key(key)
    return any(
        normalized == part
        or normalized.startswith(f"{part}_")
        or normalized.endswith(f"_{part}")
        for part in SENSITIVE_KEY_PARTS
    )


def _value_is_sensitive(value: str) -> bool:
    return value != REDACTED and any(
        pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS
    )


def sanitize_payload(payload: Any) -> Any:
    """Return a deep redacted copy suitable for persisted evidence."""
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            if _key_is_sensitive(str(key)) and value not in (None, "", REDACTED):
                sanitized[str(key)] = REDACTED
            else:
                sanitized[str(key)] = sanitize_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_payload(item) for item in payload]
    if isinstance(payload, str) and _value_is_sensitive(payload):
        return REDACTED
    return payload


def sensitive_paths(payload: Any, path: str = "$") -> list[str]:
    """Return JSON paths that still contain secret-shaped material."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            if (
                _key_is_sensitive(str(key))
                and value not in (None, "", REDACTED)
            ):
                found.append(child_path)
            else:
                found.extend(sensitive_paths(value, child_path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(sensitive_paths(value, f"{path}[{index}]"))
    elif isinstance(payload, str) and _value_is_sensitive(payload):
        found.append(path)
    return found


def _require_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"{path} must be a non-empty string.")
    return value


def validate_snapshot(snapshot: dict[str, Any], *, label: str) -> None:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError(
            f"{label}.schema_version must be {SCHEMA_VERSION}."
        )
    sensitive = sensitive_paths(snapshot)
    if sensitive:
        raise VerificationError(
            f"{label} is not sanitized; sensitive values remain at "
            + ", ".join(sensitive)
        )
    environment = snapshot.get("environment")
    if not isinstance(environment, dict):
        raise VerificationError(f"{label}.environment must be an object.")
    _require_string(environment.get("name"), f"{label}.environment.name")
    _require_string(
        environment.get("scope_id"), f"{label}.environment.scope_id"
    )
    stages = snapshot.get("stages")
    if not isinstance(stages, dict) or not stages:
        raise VerificationError(f"{label}.stages must be a non-empty object.")
    for name, status in stages.items():
        _require_string(name, f"{label}.stages key")
        _require_string(status, f"{label}.stages.{name}")

    inventory = snapshot.get("inventory")
    if not isinstance(inventory, dict):
        raise VerificationError(f"{label}.inventory must be an object.")
    for collection in COLLECTION_LABELS:
        items = inventory.get(collection)
        if not isinstance(items, list):
            raise VerificationError(
                f"{label}.inventory.{collection} must be an array."
            )
        for index, item in enumerate(items):
            item_path = f"{label}.inventory.{collection}[{index}]"
            if not isinstance(item, dict):
                raise VerificationError(f"{item_path} must be an object.")
            _require_string(item.get("id"), f"{item_path}.id")
            _require_string(item.get("name"), f"{item_path}.name")
            if not isinstance(item.get("state"), dict):
                raise VerificationError(f"{item_path}.state must be an object.")


def validate_scenarios(
    definition: dict[str, Any],
    *,
    scope_id: str,
) -> list[dict[str, Any]]:
    if definition.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError(
            f"scenarios.schema_version must be {SCHEMA_VERSION}."
        )
    if definition.get("environment_scope_id") != scope_id:
        raise VerificationError(
            "Scenario environment_scope_id does not exactly match the snapshot scope."
        )
    scenarios = definition.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise VerificationError("scenarios.scenarios must be a non-empty array.")
    scenario_ids: set[str] = set()
    scenario_types: set[str] = set()
    bounded_targets: set[tuple[str, str, str | None]] = set()
    for index, scenario in enumerate(scenarios):
        path = f"scenarios.scenarios[{index}]"
        if not isinstance(scenario, dict):
            raise VerificationError(f"{path} must be an object.")
        scenario_id = _require_string(scenario.get("id"), f"{path}.id")
        if scenario_id in scenario_ids:
            raise VerificationError(f"Duplicate scenario id '{scenario_id}'.")
        scenario_ids.add(scenario_id)
        scenario_type = _require_string(scenario.get("type"), f"{path}.type")
        if scenario_type not in DRIFT_TYPES and scenario_type != "container_app_env_drift":
            raise VerificationError(
                f"{path}.type '{scenario_type}' is not an allowed drift type."
            )
        scenario_types.add(scenario_type)
        target = scenario.get("target")
        if not isinstance(target, dict):
            raise VerificationError(f"{path}.target must be an object.")
        target_id = _require_string(target.get("resource_id"), f"{path}.target.resource_id")
        _require_string(target.get("resource_name"), f"{path}.target.resource_name")
        env_var: str | None = None
        if scenario_type == "container_app_env_drift":
            env_var = _require_string(scenario.get("env_var"), f"{path}.env_var")
        target_key = (scenario_type, target_id, env_var)
        if target_key in bounded_targets:
            raise VerificationError(
                f"Duplicate bounded target for scenario '{scenario_id}'."
            )
        bounded_targets.add(target_key)
    missing_types = sorted(REQUIRED_DRIFT_TYPES - scenario_types)
    if missing_types:
        raise VerificationError(
            "Scenario definition must cover every controlled drift type; missing: "
            + ", ".join(missing_types)
            + "."
        )
    return scenarios


def _snapshot_scope(snapshot: dict[str, Any]) -> str:
    return str(snapshot["environment"]["scope_id"])


def _inventory_items(
    snapshot: dict[str, Any], collection: str
) -> list[dict[str, Any]]:
    return snapshot["inventory"][collection]


def _find_exact(
    snapshot: dict[str, Any],
    collection: str,
    resource_id: str,
) -> dict[str, Any] | None:
    matches = [
        item
        for item in _inventory_items(snapshot, collection)
        if item["id"] == resource_id
    ]
    if len(matches) > 1:
        raise VerificationError(
            f"Resource id '{resource_id}' is duplicated in {collection}."
        )
    return matches[0] if matches else None


def duplicate_issues(snapshot: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    id_collections: dict[str, set[str]] = {}
    for collection, label in COLLECTION_LABELS.items():
        items = _inventory_items(snapshot, collection)
        ids = [str(item["id"]) for item in items]
        names = [str(item["name"]).casefold() for item in items]
        for identifier in ids:
            id_collections.setdefault(identifier.casefold(), set()).add(collection)
        duplicate_ids = sorted(
            identifier
            for identifier, count in Counter(
                item.casefold() for item in ids
            ).items()
            if count > 1
        )
        duplicate_names = sorted(
            name for name, count in Counter(names).items() if count > 1
        )
        if duplicate_ids:
            issues.append(f"Duplicate {label} ids: {', '.join(duplicate_ids)}.")
        if duplicate_names:
            issues.append(f"Duplicate {label} names: {', '.join(duplicate_names)}.")

    cross_collection_ids = sorted(
        identifier
        for identifier, collections in id_collections.items()
        if len(collections) > 1
    )
    if cross_collection_ids:
        issues.append(
            "Resource ids appear in multiple inventory collections: "
            + ", ".join(cross_collection_ids)
            + "."
        )

    seed_record_ids: list[str] = []
    for seed_set in _inventory_items(snapshot, "seed_sets"):
        record_ids = seed_set["state"].get("record_ids", [])
        if not isinstance(record_ids, list) or not all(
            isinstance(record_id, str) and record_id for record_id in record_ids
        ):
            issues.append(
                f"Seed set '{seed_set['name']}' state.record_ids must be an array "
                "of non-empty strings."
            )
            continue
        seed_record_ids.extend(record_ids)
    duplicate_records = sorted(
        record_id
        for record_id, count in Counter(seed_record_ids).items()
        if count > 1
    )
    if duplicate_records:
        issues.append("Duplicate seed record ids: " + ", ".join(duplicate_records) + ".")
    return issues


def _managed_inventory(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        collection: sorted(
            (
                {
                    "id": item["id"],
                    "name": item["name"],
                    "state": item["state"],
                }
                for item in _inventory_items(snapshot, collection)
            ),
            key=lambda item: item["id"],
        )
        for collection in COLLECTION_LABELS
    }


def _scenario_path(scenario: dict[str, Any]) -> tuple[str, tuple[str, ...] | None]:
    scenario_type = str(scenario["type"])
    if scenario_type == "container_app_env_drift":
        return "container_apps", (
            "state",
            "environment_hashes",
            str(scenario["env_var"]),
        )
    return DRIFT_TYPES[scenario_type]


def _get_path(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            raise VerificationError(
                f"Managed path '{'.'.join(path)}' is absent from resource "
                f"'{payload.get('id', '<unknown>')}'."
            )
        current = current[part]
    return current


def _set_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current: Any = payload
    for part in path[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise VerificationError(
                f"Managed path '{'.'.join(path)}' is absent from resource "
                f"'{payload.get('id', '<unknown>')}'."
            )
        current = current[part]
    if not isinstance(current, dict) or path[-1] not in current:
        raise VerificationError(
            f"Managed path '{'.'.join(path)}' is absent from resource "
            f"'{payload.get('id', '<unknown>')}'."
        )
    current[path[-1]] = copy.deepcopy(value)


def build_drift_plan(
    baseline: dict[str, Any],
    inventory: dict[str, Any],
    definition: dict[str, Any],
) -> dict[str, Any]:
    validate_snapshot(baseline, label="baseline")
    validate_snapshot(inventory, label="inventory")
    scope_id = _snapshot_scope(baseline)
    if _snapshot_scope(inventory) != scope_id:
        raise VerificationError(
            "Baseline and inventory environment scope ids do not exactly match."
        )
    scenarios = validate_scenarios(definition, scope_id=scope_id)
    baseline_issues = duplicate_issues(baseline)
    if baseline_issues:
        raise VerificationError(
            "Cannot plan from an ambiguous baseline: " + " ".join(baseline_issues)
        )
    issues = duplicate_issues(inventory)
    if issues:
        raise VerificationError(
            "Cannot plan against an ambiguous inventory: " + " ".join(issues)
        )

    operations: list[dict[str, Any]] = []
    evaluated: list[dict[str, Any]] = []
    for scenario in scenarios:
        collection, managed_path = _scenario_path(scenario)
        target = scenario["target"]
        target_id = str(target["resource_id"])
        target_name = str(target["resource_name"])
        desired_resource = _find_exact(baseline, collection, target_id)
        if desired_resource is None:
            raise VerificationError(
                f"Scenario '{scenario['id']}' target id '{target_id}' is not "
                "declared in the baseline."
            )
        if desired_resource["name"] != target_name:
            raise VerificationError(
                f"Scenario '{scenario['id']}' target name does not exactly match "
                "the baseline resource bound to that id."
            )
        observed_resource = _find_exact(inventory, collection, target_id)
        if managed_path is None:
            drifted = observed_resource is None
            evaluated.append(
                {
                    "scenario_id": scenario["id"],
                    "type": scenario["type"],
                    "target_id": target_id,
                    "drifted": drifted,
                }
            )
            if drifted:
                operations.append(
                    {
                        "scenario_id": scenario["id"],
                        "action": "restore_resource",
                        "collection": collection,
                        "target_id": target_id,
                        "target_name": target_name,
                        "desired_resource": desired_resource,
                    }
                )
            continue
        if observed_resource is None:
            raise VerificationError(
                f"Scenario '{scenario['id']}' target id '{target_id}' is absent. "
                "Only role_assignment_removal may restore an absent resource."
            )
        if observed_resource["name"] != target_name:
            raise VerificationError(
                f"Scenario '{scenario['id']}' observed target name does not "
                "exactly match the bounded resource id."
            )
        desired_value = _get_path(desired_resource, managed_path)
        observed_value = _get_path(observed_resource, managed_path)
        drifted = observed_value != desired_value
        evaluated.append(
            {
                "scenario_id": scenario["id"],
                "type": scenario["type"],
                "target_id": target_id,
                "managed_path": ".".join(managed_path),
                **(
                    {"env_var": scenario["env_var"]}
                    if scenario["type"] == "container_app_env_drift"
                    else {}
                ),
                "drifted": drifted,
            }
        )
        if drifted:
            operations.append(
                {
                    "scenario_id": scenario["id"],
                    "action": "replace_value",
                    "collection": collection,
                    "target_id": target_id,
                    "target_name": target_name,
                    "managed_path": list(managed_path),
                    "observed": observed_value,
                    "desired": desired_value,
                }
            )

    plan_body = {
        "schema_version": SCHEMA_VERSION,
        "environment_scope_id": scope_id,
        "evaluated_scenarios": evaluated,
        "operations": operations,
    }
    digest = hashlib.sha256(
        json.dumps(plan_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        **plan_body,
        "plan_digest": digest,
        "required_confirmation": f"APPLY {scope_id} {digest}",
        "safe_to_apply": True,
    }


def apply_drift_plan(
    baseline: dict[str, Any],
    inventory: dict[str, Any],
    definition: dict[str, Any],
    plan: dict[str, Any],
    *,
    confirmation: str | None,
) -> dict[str, Any]:
    expected_plan = build_drift_plan(baseline, inventory, definition)
    if plan != expected_plan:
        raise VerificationError(
            "Apply refused: plan contents do not match the bounded preview."
        )
    plan_body = {
        "schema_version": plan.get("schema_version"),
        "environment_scope_id": plan.get("environment_scope_id"),
        "evaluated_scenarios": plan.get("evaluated_scenarios"),
        "operations": plan.get("operations"),
    }
    computed_digest = hashlib.sha256(
        json.dumps(plan_body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    expected_confirmation = (
        f"APPLY {plan.get('environment_scope_id')} {computed_digest}"
    )
    if (
        plan.get("plan_digest") != computed_digest
        or plan.get("required_confirmation") != expected_confirmation
    ):
        raise VerificationError(
            "Apply refused: plan contents do not match the preview digest."
        )
    required_confirmation = plan["required_confirmation"]
    if confirmation != required_confirmation:
        raise VerificationError(
            "Apply refused: confirmation must exactly equal "
            f"'{required_confirmation}'."
        )
    if _snapshot_scope(inventory) != plan["environment_scope_id"]:
        raise VerificationError(
            "Apply refused: inventory scope no longer matches the plan."
        )
    evaluations = plan.get("evaluated_scenarios")
    operations = plan.get("operations")
    if not isinstance(evaluations, list) or not isinstance(operations, list):
        raise VerificationError("Apply refused: plan operations are malformed.")
    evaluation_by_id = {
        evaluation.get("scenario_id"): evaluation
        for evaluation in evaluations
        if isinstance(evaluation, dict)
    }
    if len(evaluation_by_id) != len(evaluations):
        raise VerificationError(
            "Apply refused: evaluated scenario ids must be unique."
        )
    drifted_ids = {
        scenario_id
        for scenario_id, evaluation in evaluation_by_id.items()
        if evaluation.get("drifted") is True
    }
    operation_ids = {
        operation.get("scenario_id")
        for operation in operations
        if isinstance(operation, dict)
    }
    if len(operation_ids) != len(operations) or operation_ids != drifted_ids:
        raise VerificationError(
            "Apply refused: operations do not exactly match drifted scenarios."
        )
    for operation in operations:
        evaluation = evaluation_by_id[operation["scenario_id"]]
        scenario_type = evaluation.get("type")
        if scenario_type == "container_app_env_drift":
            expected_collection = "container_apps"
            env_var = evaluation.get("env_var")
            if not isinstance(env_var, str) or not env_var:
                raise VerificationError(
                    "Apply refused: container app scenario has no bounded env var."
                )
            expected_path = ["state", "environment_hashes", env_var]
            expected_action = "replace_value"
        elif scenario_type in DRIFT_TYPES:
            expected_collection, path = DRIFT_TYPES[scenario_type]
            expected_path = list(path) if path is not None else None
            expected_action = (
                "restore_resource" if path is None else "replace_value"
            )
        else:
            raise VerificationError(
                f"Apply refused: scenario type '{scenario_type}' is not allowed."
            )
        if (
            operation.get("action") != expected_action
            or operation.get("collection") != expected_collection
            or operation.get("target_id") != evaluation.get("target_id")
            or operation.get("managed_path") != expected_path
        ):
            raise VerificationError(
                f"Apply refused: operation '{operation.get('scenario_id')}' "
                "escaped its controlled drift boundary."
            )
    updated = copy.deepcopy(inventory)
    for operation in operations:
        collection = str(operation["collection"])
        target_id = str(operation["target_id"])
        target_name = str(operation["target_name"])
        if operation["action"] == "restore_resource":
            if _find_exact(updated, collection, target_id) is not None:
                raise VerificationError(
                    f"Apply refused: target '{target_id}' changed after planning."
                )
            desired_resource = copy.deepcopy(operation["desired_resource"])
            if (
                desired_resource.get("id") != target_id
                or desired_resource.get("name") != target_name
            ):
                raise VerificationError(
                    "Apply refused: restore payload escaped its bounded target."
                )
            _inventory_items(updated, collection).append(desired_resource)
            continue
        if operation["action"] != "replace_value":
            raise VerificationError(
                f"Apply refused: action '{operation['action']}' is not allowed."
            )
        resource = _find_exact(updated, collection, target_id)
        if resource is None or resource["name"] != target_name:
            raise VerificationError(
                f"Apply refused: exact target '{target_id}' is unavailable."
            )
        managed_path = tuple(str(part) for part in operation["managed_path"])
        if _get_path(resource, managed_path) != operation["observed"]:
            raise VerificationError(
                f"Apply refused: target '{target_id}' changed after planning."
            )
        _set_path(resource, managed_path, operation["desired"])
    validate_snapshot(updated, label="applied_inventory")
    remaining = duplicate_issues(updated)
    if remaining:
        raise VerificationError(
            "Apply produced an invalid inventory: " + " ".join(remaining)
        )
    return updated


def verify_recovery(
    baseline: dict[str, Any],
    interrupted: dict[str, Any],
    rerun: dict[str, Any],
    *,
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    for label, snapshot in (
        ("baseline", baseline),
        ("interrupted", interrupted),
        ("rerun", rerun),
    ):
        validate_snapshot(snapshot, label=label)

    scope_id = _snapshot_scope(baseline)
    issues: list[str] = []
    checks: list[dict[str, Any]] = []
    if _snapshot_scope(interrupted) != scope_id or _snapshot_scope(rerun) != scope_id:
        issues.append("All snapshots must have the same exact environment scope id.")
    else:
        checks.append({"name": "environment_scope", "status": "passed"})

    duplicates_by_snapshot: dict[str, list[str]] = {}
    for label, snapshot in (
        ("baseline", baseline),
        ("interrupted", interrupted),
        ("rerun", rerun),
    ):
        snapshot_issues = duplicate_issues(snapshot)
        duplicates_by_snapshot[label] = snapshot_issues
        if snapshot_issues:
            issues.extend(f"{label}: {issue}" for issue in snapshot_issues)
        else:
            checks.append({"name": f"{label}_duplicates", "status": "passed"})

    interrupted_inventory_changes = sorted(
        collection
        for collection in COLLECTION_LABELS
        if _managed_inventory(baseline)[collection]
        != _managed_inventory(interrupted)[collection]
    )
    checks.append(
        {
            "name": "interrupted_inventory_comparison",
            "status": "passed",
            "changed_collections": interrupted_inventory_changes,
        }
    )

    recovered_stages: list[str] = []
    baseline_stages = baseline["stages"]
    interrupted_stages = interrupted["stages"]
    rerun_stages = rerun["stages"]
    for stage, baseline_status in baseline_stages.items():
        if baseline_status.casefold() not in SUCCESS_STATUSES:
            continue
        interrupted_status = str(interrupted_stages.get(stage, "missing")).casefold()
        rerun_status = str(rerun_stages.get(stage, "missing")).casefold()
        if rerun_status not in SUCCESS_STATUSES:
            issues.append(
                f"Rerun stage '{stage}' did not recover: status={rerun_status!r}."
            )
        if interrupted_status not in SUCCESS_STATUSES and rerun_status in SUCCESS_STATUSES:
            recovered_stages.append(stage)
    if not recovered_stages:
        issues.append(
            "Interrupted snapshot does not show a failed, cancelled, or missing "
            "baseline stage that the rerun recovered."
        )
    else:
        checks.append(
            {
                "name": "interrupted_stage_recovery",
                "status": "passed",
                "recovered_stages": sorted(recovered_stages),
            }
        )

    if _managed_inventory(baseline) != _managed_inventory(rerun):
        issues.append("Rerun managed inventory did not converge to the baseline.")
    else:
        checks.append({"name": "managed_inventory_convergence", "status": "passed"})

    if (
        not duplicates_by_snapshot["baseline"]
        and not duplicates_by_snapshot["rerun"]
        and _snapshot_scope(rerun) == scope_id
    ):
        plan = build_drift_plan(baseline, rerun, scenarios)
        drifted = [
            result["scenario_id"]
            for result in plan["evaluated_scenarios"]
            if result["drifted"]
        ]
        if drifted:
            issues.append(
                "Rerun did not reconcile intended drift scenarios: "
                + ", ".join(drifted)
                + "."
            )
        else:
            checks.append(
                {"name": "intended_drift_reconciliation", "status": "passed"}
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "environment_scope_id": scope_id,
        "passed": not issues,
        "checks": checks,
        "recovered_stages": sorted(recovered_stages),
        "interrupted_inventory_changes": interrupted_inventory_changes,
        "issues": issues,
    }


def _render(payload: dict[str, Any], output: Path | None = None) -> None:
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if output is not None:
        output.write_text(f"{rendered}\n", encoding="utf-8")


def main() -> int:
    args = _arguments()
    try:
        if args.command == "sanitize":
            sanitized = sanitize_payload(load_json(args.input))
            _render(sanitized, args.output)
            return 0
        if args.command == "verify":
            report = verify_recovery(
                load_json(args.baseline),
                load_json(args.interrupted),
                load_json(args.rerun),
                scenarios=load_json(args.scenarios),
            )
            _render(report, args.output)
            return 0 if report["passed"] else 1

        baseline = load_json(args.baseline)
        inventory = load_json(args.inventory)
        definition = load_json(args.scenarios)
        plan = build_drift_plan(
            baseline,
            inventory,
            definition,
        )
        if args.mode == "preview":
            _render(plan, args.output)
            return 0
        if args.output is None:
            raise VerificationError("--output is required in apply mode.")
        if args.output.resolve() == args.inventory.resolve():
            raise VerificationError(
                "Apply refuses in-place mutation; choose a distinct --output path."
            )
        updated = apply_drift_plan(
            baseline,
            inventory,
            definition,
            plan,
            confirmation=args.confirm,
        )
        _render(updated, args.output)
        return 0
    except VerificationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
