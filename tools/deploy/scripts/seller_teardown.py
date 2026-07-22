#!/usr/bin/env python3
"""Preview and remove one explicitly named Waypoint seller environment."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


SAFE_NAME = re.compile(r"^[A-Za-z0-9._()-]+$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
APP_STATE_KEYS = (
    "waypoint_msal_client_id",
    "keystone_msal_client_id",
    "WAYPOINT_MSAL_CLIENT_ID",
    "MSAL_CLIENT_ID",
)
POLL_ATTEMPTS = int(os.environ.get("WAYPOINT_TEARDOWN_POLL_ATTEMPTS", "20"))
POLL_SECONDS = int(os.environ.get("WAYPOINT_TEARDOWN_POLL_SECONDS", "15"))
COMMAND_TIMEOUT_SECONDS = int(os.environ.get("WAYPOINT_TEARDOWN_COMMAND_TIMEOUT_SECONDS", "120"))


class CommandError(RuntimeError):
    pass


def command(
    args: list[str],
    *,
    allow_failure: bool = False,
    timeout_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandError(
            f"{' '.join(args[:3])} exceeded the {timeout_seconds}-second command timeout"
        ) from exc
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise CommandError(f"{' '.join(args[:3])} failed: {detail}")
    return result


def json_command(args: list[str], *, allow_failure: bool = False, default: Any = None) -> Any:
    result = command(args, allow_failure=allow_failure)
    if result.returncode or not result.stdout.strip():
        return default
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CommandError(f"{' '.join(args[:3])} returned invalid JSON") from exc


def validate_name(label: str, value: str) -> None:
    if not SAFE_NAME.fullmatch(value):
        raise ValueError(f"{label} contains unsupported characters")


def mask(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:8]}...{value[-4:]}"


def group_inventory(name: str) -> dict[str, Any]:
    exists = command(["az", "group", "exists", "--name", name]).stdout.strip().lower() == "true"
    if not exists:
        return {"name": name, "exists": False, "location": None, "resources": []}
    group = json_command(["az", "group", "show", "--name", name, "-o", "json"], default={})
    resources = json_command(
        ["az", "resource", "list", "--resource-group", name, "-o", "json"],
        default=[],
    )
    return {
        "name": name,
        "exists": True,
        "location": group.get("location"),
        "resources": sorted(
            (
                {
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                    "location": item.get("location") or group.get("location"),
                }
                for item in resources
            ),
            key=lambda item: (item["type"], item["name"]),
        ),
        "_tags": group.get("tags") or {},
    }


def wait_for_deleted_inventory(
    label: str,
    list_command: list[str],
    *,
    present: bool,
) -> None:
    for _ in range(POLL_ATTEMPTS):
        inventory = json_command(list_command, default=[])
        if bool(inventory) == present:
            return
        time.sleep(POLL_SECONDS)
    expected = "appear" if present else "purge"
    raise CommandError(f"timed out after {POLL_ATTEMPTS * POLL_SECONDS} seconds waiting for {label} to {expected}")


def purge_soft_deleted_resources(group: dict[str, Any]) -> None:
    for resource in group["resources"]:
        resource_type = resource["type"].lower()
        name = resource["name"]
        if resource_type == "microsoft.keyvault/vaults":
            list_command = [
                "az",
                "keyvault",
                "list-deleted",
                "--query",
                f"[?name=='{name}'].name",
                "--output",
                "json",
            ]
            wait_for_deleted_inventory(f"Key Vault {name}", list_command, present=True)
            command(
                ["az", "keyvault", "purge", "--name", name],
                timeout_seconds=COMMAND_TIMEOUT_SECONDS,
            )
            wait_for_deleted_inventory(f"Key Vault {name}", list_command, present=False)
        elif resource_type == "microsoft.cognitiveservices/accounts":
            list_command = [
                "az",
                "cognitiveservices",
                "account",
                "list-deleted",
                "--query",
                f"[?name=='{name}'].name",
                "--output",
                "json",
            ]
            wait_for_deleted_inventory(f"AI Services account {name}", list_command, present=True)
            command(
                [
                    "az",
                    "cognitiveservices",
                    "account",
                    "purge",
                    "--name",
                    name,
                    "--resource-group",
                    group["name"],
                    "--location",
                    resource["location"],
                ],
                timeout_seconds=COMMAND_TIMEOUT_SECONDS,
            )
            wait_for_deleted_inventory(f"AI Services account {name}", list_command, present=False)


def wait_for_cli_absence(label: str, probes: list[list[str]]) -> None:
    for _ in range(POLL_ATTEMPTS):
        if all(command(probe, allow_failure=True).returncode != 0 for probe in probes):
            return
        time.sleep(POLL_SECONDS)
    raise CommandError(f"timed out after {POLL_ATTEMPTS * POLL_SECONDS} seconds waiting for {label} deletion")


def delete_app_dependencies(resource_group: str, resources: list[dict[str, str]]) -> None:
    app_names = [
        item["name"]
        for item in resources
        if item["type"].lower() == "microsoft.app/containerapps"
    ]
    environment_names = [
        item["name"]
        for item in resources
        if item["type"].lower() == "microsoft.app/managedenvironments"
    ]

    for app_name in app_names:
        command(
            [
                "az",
                "containerapp",
                "delete",
                "--resource-group",
                resource_group,
                "--name",
                app_name,
                "--yes",
                "--no-wait",
            ]
        )
    if app_names:
        wait_for_cli_absence(
            "Container App",
            [
                [
                    "az",
                    "containerapp",
                    "show",
                    "--resource-group",
                    resource_group,
                    "--name",
                    app_name,
                    "--output",
                    "none",
                ]
                for app_name in app_names
            ],
        )

    for environment_name in environment_names:
        components = json_command(
            [
                "az",
                "containerapp",
                "env",
                "dotnet-component",
                "list",
                "--resource-group",
                resource_group,
                "--environment",
                environment_name,
                "--output",
                "json",
            ],
            default=[],
        )
        for component in components:
            component_name = str(component.get("name") or "")
            if not component_name:
                raise CommandError(f"Container Apps environment {environment_name} returned an unnamed .NET component")
            command(
                [
                    "az",
                    "containerapp",
                    "env",
                    "dotnet-component",
                    "delete",
                    "--resource-group",
                    resource_group,
                    "--environment",
                    environment_name,
                    "--name",
                    component_name,
                    "--yes",
                ],
                timeout_seconds=COMMAND_TIMEOUT_SECONDS,
            )
        command(
            [
                "az",
                "containerapp",
                "env",
                "delete",
                "--resource-group",
                resource_group,
                "--name",
                environment_name,
                "--yes",
                "--no-wait",
            ]
        )
        wait_for_cli_absence(
            f"Container Apps environment {environment_name}",
            [
                [
                    "az",
                    "containerapp",
                    "env",
                    "show",
                    "--resource-group",
                    resource_group,
                    "--name",
                    environment_name,
                    "--output",
                    "none",
                ]
            ],
        )


def delete_group(name: str) -> None:
    exists = command(["az", "group", "exists", "--name", name]).stdout.strip().lower()
    if exists == "false":
        return
    command(["az", "group", "delete", "--name", name, "--yes", "--no-wait"])
    for _ in range(POLL_ATTEMPTS):
        exists = command(["az", "group", "exists", "--name", name]).stdout.strip().lower()
        if exists == "false":
            return
        time.sleep(POLL_SECONDS)
    raise CommandError(f"timed out after {POLL_ATTEMPTS * POLL_SECONDS} seconds waiting for resource group deletion")


def azd_values(environment: str) -> tuple[bool, dict[str, str]]:
    result = command(
        ["azd", "env", "get-values", "--environment", environment, "-o", "json"],
        allow_failure=True,
    )
    if result.returncode:
        return False, {}
    try:
        values = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise CommandError("azd env get-values returned invalid JSON") from exc
    return True, {str(key): str(value) for key, value in values.items()}


def discover_applications(
    environment: str,
    repository: str,
    state_tags: dict[str, str],
    environment_values: dict[str, str],
    deployment_client_id: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    deploy_object_id = command(
        ["az", "ad", "sp", "show", "--id", deployment_client_id, "--query", "id", "-o", "tsv"]
    ).stdout.strip()
    if not deploy_object_id:
        raise CommandError("could not resolve the deployment service principal")

    recorded: dict[str, set[str]] = {}
    for source, values in (("state resource-group tag", state_tags), ("azd environment", environment_values)):
        for key in APP_STATE_KEYS:
            value = values.get(key, "")
            if UUID.fullmatch(value):
                recorded.setdefault(value.lower(), set()).add(source)

    tagged_apps = json_command(["az", "ad", "app", "list", "--all", "-o", "json"], default=[])
    expected_tags = {f"waypoint-environment={environment}", "waypoint-managed"}
    if repository:
        expected_tags.add(f"waypoint-repository={repository}")

    by_id: dict[str, dict[str, Any]] = {}
    for app in tagged_apps:
        app_id = str(app.get("appId") or "")
        tags = set(app.get("tags") or [])
        tag_owned = expected_tags.issubset(tags)
        if tag_owned or app_id.lower() in recorded:
            by_id[app_id.lower()] = app

    accepted: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for app_id, app in sorted(by_id.items()):
        display_name = str(app.get("displayName") or "<unnamed>")
        if app_id == deployment_client_id.lower():
            skipped.append({"client_id": mask(app_id), "name": display_name, "reason": "deployment identity"})
            continue
        object_id = str(app.get("id") or "")
        owners = json_command(
            ["az", "ad", "app", "owner", "list", "--id", object_id, "--query", "[].id", "-o", "json"],
            default=[],
        )
        if deploy_object_id not in owners:
            skipped.append(
                {"client_id": mask(app_id), "name": display_name, "reason": "deployment principal is not an owner"}
            )
            continue
        tags = set(app.get("tags") or [])
        source = "ownership tags" if expected_tags.issubset(tags) else ", ".join(sorted(recorded[app_id]))
        accepted.append({"app_id": app_id, "object_id": object_id, "name": display_name, "source": source})
    return accepted, skipped


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(plan))
    result["subscription"] = mask(result["subscription"])
    for group in (result["app_resource_group"], result["state_resource_group"]):
        group.pop("_tags", None)
    for app in result["app_registrations"]["eligible"]:
        app["client_id"] = mask(app.pop("app_id"))
        app.pop("object_id", None)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--app-resource-group", required=True)
    parser.add_argument("--state-resource-group", required=True)
    parser.add_argument("--azd-env", required=True)
    parser.add_argument("--deployment-client-id", required=True)
    parser.add_argument("--repository", default="")
    parser.add_argument("--apply", action="store_true", help="Execute the emitted plan; the default is dry-run.")
    parser.add_argument("--confirm-environment", default="")
    parser.add_argument("--delete-app-registrations", action="store_true")
    parser.add_argument("--plan-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        for label, value in (
            ("app resource group", args.app_resource_group),
            ("state resource group", args.state_resource_group),
            ("azd environment", args.azd_env),
        ):
            validate_name(label, value)
        if not UUID.fullmatch(args.subscription_id) or not UUID.fullmatch(args.deployment_client_id):
            raise ValueError("subscription and deployment client IDs must be UUIDs")
        if args.app_resource_group == args.state_resource_group:
            raise ValueError("app and state resource groups must differ")
        if args.repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
            raise ValueError("repository must be owner/name")
        if args.apply and args.confirm_environment != args.azd_env:
            raise ValueError("--confirm-environment must exactly match --azd-env when --apply is used")
        for executable in ("az", "azd"):
            if shutil.which(executable) is None:
                raise ValueError(f"{executable} is required")

        account = json_command(["az", "account", "show", "-o", "json"], default={})
        if str(account.get("id", "")).lower() != args.subscription_id.lower():
            raise ValueError("active Azure subscription does not match --subscription-id")

        app_group = group_inventory(args.app_resource_group)
        state_group = group_inventory(args.state_resource_group)
        env_exists, env_values = azd_values(args.azd_env)
        eligible, skipped = discover_applications(
            args.azd_env,
            args.repository,
            state_group.get("_tags", {}),
            env_values,
            args.deployment_client_id,
        )
        plan = {
            "mode": "apply" if args.apply else "dry-run",
            "subscription": args.subscription_id,
            "azd_environment": {"name": args.azd_env, "exists": env_exists, "action": "remove local state"},
            "app_resource_group": app_group,
            "state_resource_group": state_group,
            "order": [
                "Container Apps",
                "Container Apps .NET components",
                "Container Apps environment",
                "app resource group",
                "owned soft-deleted app resources",
                "eligible app registrations",
                "state resource group",
                "owned soft-deleted state resources",
                "local azd state",
            ],
            "app_registrations": {
                "deletion_enabled": args.delete_app_registrations,
                "eligible": [
                    {
                        "app_id": item["app_id"],
                        "object_id": item["object_id"],
                        "name": item["name"],
                        "source": item["source"],
                    }
                    for item in eligible
                ],
                "skipped": skipped,
            },
        }
        rendered = json.dumps(public_plan(plan), indent=2, sort_keys=True)
        print(rendered)
        if args.plan_out:
            args.plan_out.write_text(rendered + "\n", encoding="utf-8")
        if not args.apply:
            return 0

        if app_group["exists"]:
            delete_app_dependencies(args.app_resource_group, app_group["resources"])
            delete_group(args.app_resource_group)
            purge_soft_deleted_resources(app_group)
        if args.delete_app_registrations:
            for app in eligible:
                command(["az", "ad", "app", "delete", "--id", app["app_id"]])
        if state_group["exists"]:
            delete_group(args.state_resource_group)
            purge_soft_deleted_resources(state_group)
        if env_exists:
            command(["azd", "env", "remove", args.azd_env, "--force"])
        return 0
    except (CommandError, ValueError, OSError) as exc:
        print(f"seller-teardown: {exc}", file=sys.stderr)
        print("State resource group and local azd state were preserved unless their deletion had already begun.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
