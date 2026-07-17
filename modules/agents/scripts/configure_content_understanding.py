"""Configure Content Understanding model defaults for the Forge AI Services account."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_SCOPE = "https://cognitiveservices.azure.com/.default"
DEFAULT_API_VERSION = "2025-11-01"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PATCH /contentunderstanding/defaults with Forge model deployments."
    )
    parser.add_argument("--endpoint", default=os.getenv("CONTENT_UNDERSTANDING_ENDPOINT"))
    parser.add_argument(
        "--api-version",
        default=os.getenv("CONTENT_UNDERSTANDING_API_VERSION", DEFAULT_API_VERSION),
    )
    parser.add_argument(
        "--scope",
        default=os.getenv("CONTENT_UNDERSTANDING_SCOPE", DEFAULT_SCOPE),
    )
    parser.add_argument(
        "--completion-model",
        default=os.getenv("CONTENT_UNDERSTANDING_COMPLETION_MODEL_NAME", "gpt-5.5"),
    )
    parser.add_argument(
        "--completion-deployment",
        default=os.getenv("CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME")
        or os.getenv("CONTENT_UNDERSTANDING_GPT_DEPLOYMENT")
        or "gpt-5.5",
    )
    parser.add_argument(
        "--embedding-deployment",
        default=os.getenv("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME")
        or os.getenv("CONTENT_UNDERSTANDING_EMBEDDING_DEPLOYMENT")
        or "text-embedding-3-large",
    )
    parser.add_argument(
        "--account-name",
        default=os.getenv("AZURE_AI_ACCOUNT_NAME") or _account_name_from_endpoint(os.getenv("CONTENT_UNDERSTANDING_ENDPOINT")),
        help="AI Services account name used to validate model deployments before PATCHing.",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP") or os.getenv("AZURE_RESOURCE_GROUP_NAME"),
        help="Azure resource group for the AI Services account.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the request payload without PATCHing the service.",
    )
    args = parser.parse_args()
    if not args.account_name:
        args.account_name = _account_name_from_endpoint(args.endpoint)

    missing = [
        name
        for name, value in {
            "CONTENT_UNDERSTANDING_ENDPOINT": args.endpoint,
            "CONTENT_UNDERSTANDING_COMPLETION_DEPLOYMENT_NAME": args.completion_deployment,
            "AZURE_AI_EMBEDDING_DEPLOYMENT_NAME": args.embedding_deployment,
        }.items()
        if not value
    ]
    if missing:
        print(f"Missing required values: {', '.join(missing)}", file=sys.stderr)
        return 2

    payload = {
        "modelDeployments": {
            args.completion_model: args.completion_deployment,
            "text-embedding-3-large": args.embedding_deployment,
        }
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.dry_run:
        return 0

    validation = _validate_deployments(
        resource_group=args.resource_group,
        account_name=args.account_name,
        deployments=[
            args.completion_deployment,
            args.embedding_deployment,
        ],
    )
    if validation:
        print(validation, file=sys.stderr)
        return 1

    token = _az_access_token(args.scope)
    url = (
        f"{args.endpoint.rstrip('/')}/contentunderstanding/defaults"
        f"?api-version={args.api_version}"
    )
    try:
        current_defaults = _get_defaults(url, token)
    except urllib.error.HTTPError:
        return 1
    except urllib.error.URLError as exc:
        print(f"Content Understanding defaults GET failed: {exc}", file=sys.stderr)
        return 1
    if _defaults_match(current_defaults, payload["modelDeployments"]):
        print("Content Understanding defaults already configured.")
        print(json.dumps(current_defaults, indent=2, sort_keys=True))
        return 0

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/merge-patch+json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(
            f"Content Understanding defaults PATCH failed with HTTP {exc.code}: {body}",
            file=sys.stderr,
        )
        return 1

    print(body)
    return 0


def _account_name_from_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    host = urlparse(endpoint).hostname or ""
    if host.endswith(".services.ai.azure.com"):
        return host.removesuffix(".services.ai.azure.com")
    return None


def _validate_deployments(
    *,
    resource_group: str | None,
    account_name: str | None,
    deployments: list[str],
) -> str | None:
    if not resource_group or not account_name:
        return (
            "Missing AZURE_RESOURCE_GROUP or AZURE_AI_ACCOUNT_NAME; cannot validate "
            "Content Understanding model deployments before PATCHing."
        )
    az_executable = _az_executable()
    missing: list[str] = []
    for deployment in sorted(set(deployments)):
        completed = subprocess.run(
            [
                az_executable,
                "cognitiveservices",
                "account",
                "deployment",
                "show",
                "--resource-group",
                resource_group,
                "--name",
                account_name,
                "--deployment-name",
                deployment,
                "--query",
                "name",
                "-o",
                "tsv",
            ],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            missing.append(f"{deployment} ({detail or 'not found'})")
    if missing:
        return (
            "Content Understanding model deployment validation failed. Missing or "
            f"unavailable deployments on {resource_group}/{account_name}: "
            + "; ".join(missing)
        )
    return None


def _get_defaults(url: str, token: str) -> dict | None:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "DefaultsNotSet" in body:
            return None
        print(
            f"Content Understanding defaults GET failed with HTTP {exc.code}: {body}",
            file=sys.stderr,
        )
        raise
    return json.loads(body) if body else {}


def _defaults_match(current: dict | None, desired: dict[str, str]) -> bool:
    if not current:
        return False
    current_deployments = current.get("modelDeployments")
    if not isinstance(current_deployments, dict):
        return False
    return all(current_deployments.get(model) == deployment for model, deployment in desired.items())


def _az_executable() -> str:
    az_executable = shutil.which("az") or shutil.which("az.cmd")
    if not az_executable:
        raise RuntimeError("Azure CLI executable 'az' was not found on PATH.")
    return az_executable


def _az_access_token(scope: str) -> str:
    completed = subprocess.run(
        [
            _az_executable(),
            "account",
            "get-access-token",
            "--scope",
            scope,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
