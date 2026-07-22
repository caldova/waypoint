#!/usr/bin/env python3
"""Read-only preflight for Forge Content Understanding readiness.

The check verifies the AI Services account has the model deployments that
Content Understanding defaults reference, confirms the defaults are configured,
and optionally inspects the active hosted AssuranceOrchestrator version for the required
runtime environment variable names. It does not create, update, or delete
resources.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_API_VERSION = "2025-11-01"
DEFAULT_SCOPE = "https://cognitiveservices.azure.com/.default"
FOUNDRY_API_VERSION = "2025-05-15-preview"
FOUNDRY_FEATURES = "AgentEndpoints=V1Preview,HostedAgents=V1Preview"
REQUIRED_ASSURANCE_ORCHESTRATOR_ENV = (
    "CONTENT_UNDERSTANDING_ENDPOINT",
    "CONTENT_UNDERSTANDING_API_VERSION",
    "CONTENT_UNDERSTANDING_ANALYZER_ID",
    "CONTENT_UNDERSTANDING_SCOPE",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-group", default=os.getenv("FORGE_RESOURCE_GROUP", "rg-forge"))
    parser.add_argument("--account-name", default=os.getenv("FORGE_AI_ACCOUNT_NAME", "ai-account-wi2egf4sh4hfq"))
    parser.add_argument("--project-name", default=os.getenv("FORGE_AI_PROJECT_NAME", "ai-project-forge"))
    parser.add_argument(
        "--endpoint",
        default=os.getenv("CONTENT_UNDERSTANDING_ENDPOINT")
        or os.getenv("AZURE_AI_SERVICES_ENDPOINT")
        or "https://ai-account-wi2egf4sh4hfq.services.ai.azure.com",
    )
    parser.add_argument("--api-version", default=os.getenv("CONTENT_UNDERSTANDING_API_VERSION", DEFAULT_API_VERSION))
    parser.add_argument("--scope", default=os.getenv("CONTENT_UNDERSTANDING_SCOPE", DEFAULT_SCOPE))
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
    parser.add_argument("--agent-name", default=os.getenv("CONTENT_UNDERSTANDING_AGENT_NAME", "assurance-orchestrator"))
    parser.add_argument(
        "--skip-hosted-agent",
        action="store_true",
        help="Skip active hosted agent env-var inspection.",
    )
    parser.add_argument(
        "--require-hosted-env",
        action="store_true",
        help="Fail when the active hosted agent version is missing Content Understanding env vars.",
    )
    args = parser.parse_args()

    deployment_names = _deployment_names(args.resource_group, args.account_name)
    missing_deployments = sorted(
        {args.completion_deployment, args.embedding_deployment} - deployment_names
    )
    if missing_deployments:
        raise SystemExit(
            "Missing Content Understanding model deployments on "
            f"{args.resource_group}/{args.account_name}: {missing_deployments}"
        )

    token = _az_access_token(args.scope)
    defaults = _get_defaults(args.endpoint, args.api_version, token)
    required_defaults = {
        args.completion_model: args.completion_deployment,
        "text-embedding-3-large": args.embedding_deployment,
    }
    defaults_match = _defaults_match(defaults, required_defaults)
    if not defaults_match:
        raise SystemExit(
            "Content Understanding defaults do not include required model mappings: "
            f"{json.dumps(required_defaults, sort_keys=True)}"
        )

    hosted_agent: dict[str, Any] | None = None
    if not args.skip_hosted_agent:
        project_endpoint = f"{args.endpoint.rstrip('/')}/api/projects/{args.project_name}"
        hosted_agent = _hosted_agent_env_summary(project_endpoint, args.agent_name)
        missing_env = hosted_agent.get("missingEnv", [])
        if missing_env and args.require_hosted_env:
            raise SystemExit(
                f"Hosted agent {args.agent_name} active version is missing env vars: {missing_env}"
            )

    print(
        json.dumps(
            {
                "status": "passed",
                "account": args.account_name,
                "endpoint": args.endpoint,
                "apiVersion": args.api_version,
                "modelDeployments": {
                    args.completion_model: args.completion_deployment,
                    "text-embedding-3-large": args.embedding_deployment,
                },
                "contentUnderstandingDefaults": defaults.get("modelDeployments", {}),
                "hostedAgent": hosted_agent,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _deployment_names(resource_group: str, account_name: str) -> set[str]:
    result = _run_az_json(
        [
            "cognitiveservices",
            "account",
            "deployment",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            account_name,
            "--query",
            "[?properties.provisioningState=='Succeeded'].name",
            "-o",
            "json",
        ]
    )
    if not isinstance(result, list):
        raise SystemExit("Azure CLI returned an unexpected deployment list shape.")
    return {str(name) for name in result}


def _get_defaults(endpoint: str, api_version: str, token: str) -> dict[str, Any]:
    url = f"{endpoint.rstrip('/')}/contentunderstanding/defaults?api-version={api_version}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(
            f"Content Understanding defaults GET failed with HTTP {exc.code}: {detail}"
        ) from exc
    return json.loads(body) if body else {}


def _defaults_match(current: dict[str, Any], desired: dict[str, str]) -> bool:
    deployments = current.get("modelDeployments")
    if not isinstance(deployments, dict):
        return False
    return all(deployments.get(model) == deployment for model, deployment in desired.items())


def _hosted_agent_env_summary(project_endpoint: str, agent_name: str) -> dict[str, Any]:
    token = _az_access_token("https://ai.azure.com/.default")
    url = f"{project_endpoint.rstrip('/')}/agents/{agent_name}?api-version={FOUNDRY_API_VERSION}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Foundry-Features": FOUNDRY_FEATURES,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Hosted agent GET failed with HTTP {exc.code}: {detail}") from exc

    agent = json.loads(body)
    latest = ((agent.get("versions") or {}).get("latest") or {})
    env = ((latest.get("definition") or {}).get("environment_variables") or {})
    present = sorted(name for name in REQUIRED_ASSURANCE_ORCHESTRATOR_ENV if env.get(name))
    missing = sorted(name for name in REQUIRED_ASSURANCE_ORCHESTRATOR_ENV if not env.get(name))
    return {
        "name": agent_name,
        "version": latest.get("version"),
        "status": latest.get("status"),
        "presentEnv": present,
        "missingEnv": missing,
    }


def _az_access_token(scope: str) -> str:
    resource = scope.removesuffix(".default")
    result = _run_az(
        [
            "account",
            "get-access-token",
            "--resource",
            resource,
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ]
    )
    token = result.stdout.strip()
    if not token:
        raise SystemExit(f"Azure CLI did not return a token for {scope}.")
    return token


def _run_az_json(args: list[str]) -> Any:
    completed = _run_az(args)
    return json.loads(completed.stdout)


def _run_az(args: list[str]) -> subprocess.CompletedProcess[str]:
    az_executable = shutil.which("az") or shutil.which("az.cmd")
    if not az_executable:
        raise SystemExit("Azure CLI executable 'az' was not found on PATH.")
    completed = subprocess.run(
        [az_executable, *args],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(f"Azure CLI failed: az {' '.join(args)}\n{detail}")
    return completed


if __name__ == "__main__":
    sys.exit(main())
