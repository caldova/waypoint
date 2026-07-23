#!/usr/bin/env python3
"""Initialize the Forge contracts knowledge base from Ledgerfield documents.

This is an explicit data-plane operation. It uploads Ledgerfield contract/policy
Markdown into Forge storage, creates an Azure AI Search knowledge source and
knowledge base, then updates the Foundry RemoteTool MCP connection.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_SEARCH_API_VERSION = "2026-05-01-preview"
DEFAULT_KNOWLEDGE_SOURCE_API_VERSION = "2025-11-01-preview"
DEFAULT_CONNECTION_API_VERSION = "2025-10-01-preview"
DEFAULT_KB_NAME = "contracts-kb"
DEFAULT_KNOWLEDGE_SOURCE_NAME = "contracts-ks"
DEFAULT_CONNECTION_NAME = "kb-mcp-connection"
DEFAULT_CONTAINER = "knowledge"
DEFAULT_CONTRACTS_FOLDER = "contracts"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _run_indexer(search_endpoint: str, token: str, knowledge_source_name: str) -> None:
    """Trigger an immediate run of the knowledge-source's auto-generated indexer.

    Foundry IQ blob knowledge sources generate an indexer whose name is
    system-derived. It is conventionally ``<knowledge-source-name>-indexer``, but
    to stay robust against naming changes we resolve it dynamically from the live
    indexer list and only fall back to the conventional name if resolution fails.
    Note: the primary reingest path is re-PUTting the knowledge source (which this
    script always does); running the indexer just accelerates ingestion of a fresh
    blob set instead of waiting for the daily schedule.
    """
    indexer_name = _resolve_indexer_name(search_endpoint, token, knowledge_source_name)
    run_uri = f"{search_endpoint}/indexers('{indexer_name}')/run?api-version=2024-07-01"
    print(f"Triggering indexer run: {indexer_name}")
    _json_request("POST", run_uri, token, allow_not_found=True)


def _resolve_indexer_name(search_endpoint: str, token: str, knowledge_source_name: str) -> str:
    fallback = f"{knowledge_source_name}-indexer"
    try:
        listing = _json_request(
            "GET",
            f"{search_endpoint}/indexers?api-version=2024-07-01&$select=name",
            token,
            allow_not_found=True,
        )
    except RuntimeError as error:
        print(f"Could not list indexers ({error}); using conventional name {fallback}.", file=sys.stderr)
        return fallback
    names = [item.get("name", "") for item in (listing or {}).get("value", [])]
    if fallback in names:
        return fallback
    matches = [name for name in names if knowledge_source_name in name]
    if len(matches) == 1:
        print(f"Resolved indexer '{matches[0]}' for knowledge source '{knowledge_source_name}'.")
        return matches[0]
    if matches:
        print(f"Multiple candidate indexers for '{knowledge_source_name}': {matches}; using {matches[0]}.")
        return matches[0]
    return fallback


NATIVE_SOFT_DELETE_POLICY = {
    "@odata.type": "#Microsoft.Azure.Search.NativeBlobSoftDeleteDeletionDetectionPolicy"
}


def _resolve_datasource_name(search_endpoint: str, token: str, knowledge_source_name: str) -> str:
    """Resolve the knowledge source's auto-generated datasource name.

    Conventionally ``<knowledge-source-name>-datasource``; fall back to matching
    the knowledge-source name against the live datasource list.
    """
    fallback = f"{knowledge_source_name}-datasource"
    try:
        listing = _json_request(
            "GET",
            f"{search_endpoint}/datasources?api-version=2024-07-01&$select=name",
            token,
            allow_not_found=True,
        )
    except RuntimeError as error:
        print(f"Could not list datasources ({error}); using conventional name {fallback}.", file=sys.stderr)
        return fallback
    names = [item.get("name", "") for item in (listing or {}).get("value", [])]
    if fallback in names:
        return fallback
    matches = [name for name in names if knowledge_source_name in name]
    if len(matches) == 1:
        return matches[0]
    return fallback


def _ensure_deletion_detection(
    search_endpoint: str,
    token: str,
    knowledge_source_name: str,
    attempts: int = 4,
    delay_seconds: float = 5.0,
) -> None:
    """Patch the auto-generated blob datasource with native soft-delete deletion detection.

    Foundry IQ blob knowledge sources generate a datasource with NO
    ``dataDeletionDetectionPolicy``, so deleting a blob (e.g. a cmo-/sup- rename)
    leaves an orphaned document in the index — a plain indexer run does not remove
    it. Setting ``NativeBlobSoftDeleteDeletionDetectionPolicy`` makes a normal
    indexer run reconcile deletions, provided the storage account has blob
    soft-delete enabled (a normal delete then becomes a soft-delete the indexer
    can detect).

    Foundry IQ **regenerates the datasource on every knowledge-source PUT**
    (verified: a KS PUT reverts the datasource's ``dataDeletionDetectionPolicy``
    to null), and that regeneration can be asynchronous. This helper therefore
    applies the policy, re-reads to confirm it stuck, and retries — so it is
    robust to the datasource not existing yet AND to a late regeneration wiping a
    freshly applied policy. Best-effort and idempotent: it never fails the overall
    run.
    """
    datasource_name = _resolve_datasource_name(search_endpoint, token, knowledge_source_name)
    uri = f"{search_endpoint}/datasources('{datasource_name}')?api-version=2024-07-01"
    for attempt in range(1, attempts + 1):
        try:
            datasource = _json_request("GET", uri, token, allow_not_found=True)
        except RuntimeError as error:
            print(f"Skipping deletion-detection ensure — could not read datasource '{datasource_name}': {error}", file=sys.stderr)
            return
        if not datasource:
            if attempt < attempts:
                print(
                    f"Datasource '{datasource_name}' not present yet (attempt {attempt}/{attempts}); "
                    f"waiting {delay_seconds:.0f}s for Foundry IQ to provision it...",
                    file=sys.stderr,
                )
                time.sleep(delay_seconds)
                continue
            print(
                f"Skipping deletion-detection ensure — datasource '{datasource_name}' still not found "
                f"after {attempts} attempts (Foundry IQ may still be provisioning it); re-run the "
                "initializer once it exists.",
                file=sys.stderr,
            )
            return
        if datasource.get("dataDeletionDetectionPolicy") == NATIVE_SOFT_DELETE_POLICY:
            print(f"Deletion detection configured on datasource '{datasource_name}'.")
            return
        datasource["dataDeletionDetectionPolicy"] = NATIVE_SOFT_DELETE_POLICY
        # Strip read-only/system fields that a PUT rejects.
        for read_only in ("@odata.context", "@odata.etag"):
            datasource.pop(read_only, None)
        try:
            _json_request("PUT", uri, token, datasource)
            print(f"Enabled native blob soft-delete deletion detection on datasource '{datasource_name}'.")
        except (RuntimeError, HTTPError) as error:
            print(
                f"Could not set deletion-detection policy on datasource '{datasource_name}': {error}. "
                "Blob deletions will not auto-reconcile until this succeeds (re-run with sufficient "
                "Search Service Contributor rights).",
                file=sys.stderr,
            )
            return
        # Verify it stuck — a late async datasource regeneration can wipe it.
        if attempt < attempts:
            time.sleep(delay_seconds)
            try:
                check = _json_request("GET", uri, token, allow_not_found=True)
            except RuntimeError:
                return
            if check and check.get("dataDeletionDetectionPolicy") == NATIVE_SOFT_DELETE_POLICY:
                print(f"Verified deletion-detection policy persisted on datasource '{datasource_name}'.")
                return
            print(
                f"Deletion-detection policy was cleared again (likely a late Foundry IQ datasource "
                f"regeneration); re-applying (attempt {attempt}/{attempts})...",
                file=sys.stderr,
            )
    print(
        f"Applied deletion-detection policy on datasource '{datasource_name}' but could not confirm it "
        f"persisted after {attempts} attempts; the next initializer run will re-apply it.",
        file=sys.stderr,
    )


def _prune_stale_blobs(storage_account: str, container: str, folder: str, keep_names: set[str]) -> None:
    """Delete blobs under ``<container>/<folder>/`` that are not in ``keep_names``.

    Used only on the standalone forge upload path so a prefix rename (e.g. cmo-* to
    sup-*) does not leave both sets indexed. The Keystone path relies on Ledgerfield's
    self-cleaning sync instead.
    """
    prefix = f"{folder.rstrip('/')}/"
    listing = _az_json(
        [
            "storage",
            "blob",
            "list",
            "--account-name",
            storage_account,
            "--auth-mode",
            "login",
            "--container-name",
            container,
            "--prefix",
            prefix,
            "--query",
            "[].name",
            "-o",
            "json",
        ]
    )
    existing = json.loads(listing) if listing.strip() else []
    stale = [name for name in existing if name not in keep_names]
    if not stale:
        print("No stale blobs to prune.")
        return
    for name in stale:
        print(f"Pruning stale blob: {name}")
        _az(
            [
                "storage",
                "blob",
                "delete",
                "--account-name",
                storage_account,
                "--auth-mode",
                "login",
                "--container-name",
                container,
                "--name",
                name,
                "--output",
                "none",
            ]
        )
    print(f"Pruned {len(stale)} stale blob(s) under {container}/{prefix}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledgerfield-root", default=os.getenv("LEDGERFIELD_ROOT"))
    parser.add_argument("--resource-group", default=os.getenv("AZURE_RESOURCE_GROUP", "rg-forge"))
    parser.add_argument("--subscription-id", default=os.getenv("AZURE_SUBSCRIPTION_ID"))
    parser.add_argument("--ai-account-name", default=os.getenv("AZURE_AI_ACCOUNT_NAME"))
    parser.add_argument("--ai-project-name", default=os.getenv("AZURE_AI_PROJECT_NAME", "ai-project-forge"))
    parser.add_argument("--ai-services-endpoint", default=os.getenv("AZURE_AI_SERVICES_ENDPOINT"))
    parser.add_argument("--search-service-name", default=os.getenv("AZURE_AI_SEARCH_SERVICE_NAME"))
    parser.add_argument("--storage-account-name", default=os.getenv("AZURE_STORAGE_ACCOUNT_NAME"))
    parser.add_argument("--storage-container-name", default=os.getenv("AZURE_STORAGE_CONTAINER_NAME", DEFAULT_CONTAINER))
    parser.add_argument("--knowledge-base-name", default=os.getenv("AZURE_AI_SEARCH_KNOWLEDGE_BASE_NAME", DEFAULT_KB_NAME))
    parser.add_argument("--knowledge-source-name", default=os.getenv("AZURE_AI_SEARCH_KNOWLEDGE_SOURCE_NAME", DEFAULT_KNOWLEDGE_SOURCE_NAME))
    parser.add_argument("--mcp-connection-name", default=os.getenv("AZURE_AI_SEARCH_KB_MCP_CONNECTION_NAME", DEFAULT_CONNECTION_NAME))
    parser.add_argument("--contracts-folder", default=os.getenv("AZURE_AI_SEARCH_CONTRACTS_FOLDER", DEFAULT_CONTRACTS_FOLDER))
    parser.add_argument(
        "--chat-deployment-name",
        default=os.getenv("AZURE_AI_SEARCH_KB_CHAT_DEPLOYMENT_NAME")
        or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME"),
    )
    parser.add_argument(
        "--chat-model-name",
        default=os.getenv("AZURE_AI_SEARCH_KB_CHAT_MODEL_NAME")
        or os.getenv("AZURE_AI_MODEL_NAME")
        or os.getenv("MODEL_NAME"),
    )
    parser.add_argument("--embedding-deployment-name", default=os.getenv("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME"))
    parser.add_argument(
        "--embedding-model-name",
        default=os.getenv("AZURE_AI_EMBEDDING_MODEL_NAME")
        or os.getenv("EMBEDDING_MODEL_NAME")
        or "text-embedding-3-large",
    )
    parser.add_argument("--search-api-version", default=os.getenv("AZURE_SEARCH_KB_API_VERSION", DEFAULT_SEARCH_API_VERSION))
    parser.add_argument(
        "--retrieval-reasoning-effort",
        default=os.getenv("AZURE_AI_SEARCH_KB_RETRIEVAL_REASONING_EFFORT", "low"),
        help=(
            "Knowledge-base answer synthesis reasoning effort. Set to 'none' to omit "
            "retrievalReasoningEffort for model/API combinations that do not support it."
        ),
    )
    parser.add_argument("--force", action="store_true", help="Delete and recreate incompatible preview resources on update failure.")
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        default=_env_flag("AZURE_AI_SEARCH_SKIP_UPLOAD"),
        help=(
            "Ensure the knowledge source / knowledge base / MCP connection without staging or "
            "uploading blobs. Use when Ledgerfield (or another owner) already synced the corpus "
            "into the container. No Ledgerfield checkout is required in this mode."
        ),
    )
    parser.add_argument(
        "--run-indexer",
        action="store_true",
        default=_env_flag("AZURE_AI_SEARCH_RUN_INDEXER"),
        help=(
            "After ensuring the knowledge source, trigger an immediate run of the auto-generated "
            "indexer (resolved from the live indexer list, conventionally "
            "'<knowledge-source-name>-indexer') so a fresh blob corpus is reindexed now instead of "
            "waiting for the daily schedule."
        ),
    )
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        default=_env_flag("AZURE_AI_SEARCH_PRUNE_STALE"),
        help=(
            "Standalone forge upload path only: after uploading, delete blobs under the contracts "
            "folder that are not part of the current upload set (fixes cmo-/sup- prefix-rename "
            "leftovers). Ignored with --skip-upload (the Keystone path relies on Ledgerfield's "
            "self-cleaning sync)."
        ),
    )
    parser.add_argument(
        "--skip-deletion-detection",
        action="store_true",
        default=_env_flag("AZURE_AI_SEARCH_SKIP_DELETION_DETECTION"),
        help=(
            "Do NOT ensure native blob soft-delete deletion detection on the knowledge source's "
            "auto-generated datasource. By default the initializer patches the datasource with a "
            "NativeBlobSoftDeleteDeletionDetectionPolicy so that when stale blobs are (soft-)deleted "
            "— e.g. a cmo-/sup- rename — a normal indexer run removes the orphaned index documents. "
            "Requires blob soft-delete enabled on the storage account (provisioned in bicep)."
        ),
    )
    args = parser.parse_args()

    if not args.skip_upload:
        ledgerfield_root = _resolve_ledgerfield_root(args.ledgerfield_root)
        _require_path(ledgerfield_root / "data" / "contracts" / "source-markdown", "Ledgerfield contracts folder")
    else:
        ledgerfield_root = None
        print("Skipping blob staging/upload (--skip-upload); ensuring KB/KS/MCP over existing corpus.")

    _hydrate_defaults_from_azure(args)
    _require_args(
        args,
        "subscription_id",
        "resource_group",
        "ai_account_name",
        "ai_services_endpoint",
        "ai_project_name",
        "search_service_name",
        "storage_account_name",
        "chat_deployment_name",
        "embedding_deployment_name",
    )

    args.chat_model_name = args.chat_model_name or args.chat_deployment_name
    search_endpoint = f"https://{args.search_service_name}.search.windows.net"
    ai_endpoint = args.ai_services_endpoint.rstrip("/")
    storage_resource_id = (
        f"/subscriptions/{args.subscription_id}/resourceGroups/{args.resource_group}"
        f"/providers/Microsoft.Storage/storageAccounts/{args.storage_account_name}"
    )

    _validate_deployment(args.resource_group, args.ai_account_name, args.chat_deployment_name)
    _validate_deployment(args.resource_group, args.ai_account_name, args.embedding_deployment_name)

    with tempfile.TemporaryDirectory(prefix="forge-contracts-kb-") as tmp:
        if args.skip_upload:
            pass
        else:
            staging = Path(tmp) / "knowledge"
            _stage_ledgerfield_contracts(ledgerfield_root, staging, args.contracts_folder)
            _upload_documents(args.storage_account_name, args.storage_container_name, staging)
            if args.prune_stale:
                folder = args.contracts_folder.rstrip("/")
                keep = {
                    f"{folder}/{path.name}"
                    for path in (staging / folder).glob("*")
                    if path.is_file()
                }
                _prune_stale_blobs(
                    args.storage_account_name,
                    args.storage_container_name,
                    folder,
                    keep,
                )

    search_token = _az_token("https://search.azure.com")
    management_token = _az_token("https://management.azure.com")
    source_api_version = (
        DEFAULT_KNOWLEDGE_SOURCE_API_VERSION
        if args.search_api_version == DEFAULT_SEARCH_API_VERSION
        else args.search_api_version
    )

    knowledge_source_uri = (
        f"{search_endpoint}/knowledgesources('{args.knowledge_source_name}')"
        f"?api-version={source_api_version}"
    )
    knowledge_base_uri = (
        f"{search_endpoint}/knowledgebases('{args.knowledge_base_name}')"
        f"?api-version={args.search_api_version}"
    )

    knowledge_source_body = _knowledge_source_body(
        args=args,
        storage_resource_id=storage_resource_id,
        ai_endpoint=ai_endpoint,
    )
    knowledge_base_body = _knowledge_base_body(args=args, ai_endpoint=ai_endpoint)

    if args.force:
        print(f"Force recreating knowledge base {args.knowledge_base_name} and source {args.knowledge_source_name}")
        _json_request("DELETE", knowledge_base_uri, search_token, allow_not_found=True)
        _json_request("DELETE", knowledge_source_uri, search_token, allow_not_found=True)

    print(f"Creating/updating knowledge source {args.knowledge_source_name}")
    _put_search_resource(
        uri=knowledge_source_uri,
        token=search_token,
        body=knowledge_source_body,
        force=args.force,
        dependent_uri=knowledge_base_uri,
        display_name=args.knowledge_source_name,
    )

    print(f"Creating/updating knowledge base {args.knowledge_base_name}")
    _put_search_resource(
        uri=knowledge_base_uri,
        token=search_token,
        body=knowledge_base_body,
        force=args.force,
        dependent_uri=None,
        display_name=args.knowledge_base_name,
    )

    # Ensure the auto-generated datasource can detect (soft-)deleted blobs so a
    # rename cleanup (cmo-* → sup-*) removes orphaned index documents on the next
    # indexer run — Foundry IQ leaves this unset by default. Best-effort.
    if not args.skip_deletion_detection:
        _ensure_deletion_detection(search_endpoint, search_token, args.knowledge_source_name)

    if args.run_indexer:
        _run_indexer(search_endpoint, search_token, args.knowledge_source_name)
    mcp_endpoint = (
        f"{search_endpoint}/knowledgebases/{args.knowledge_base_name}/mcp"
        f"?api-version={args.search_api_version}"
    )
    connection_uri = (
        f"https://management.azure.com/subscriptions/{args.subscription_id}"
        f"/resourceGroups/{args.resource_group}/providers/Microsoft.CognitiveServices"
        f"/accounts/{args.ai_account_name}/projects/{args.ai_project_name}"
        f"/connections/{args.mcp_connection_name}?api-version={DEFAULT_CONNECTION_API_VERSION}"
    )
    print(f"Creating/updating Foundry MCP connection {args.mcp_connection_name}")
    _json_request(
        "PUT",
        connection_uri,
        management_token,
        {
            "properties": {
                "authType": "ProjectManagedIdentity",
                "category": "RemoteTool",
                "target": mcp_endpoint,
                "isSharedToAll": True,
                "audience": "https://search.azure.com/",
                "metadata": {
                    "ApiType": "Azure",
                    "audience": "https://search.azure.com/",
                    "knowledgeBaseName": args.knowledge_base_name,
                    "tokenAudience": "https://search.azure.com/",
                    "type": "knowledgeBase_MCP",
                },
            }
        },
    )
    print(f"Knowledge base MCP endpoint: {mcp_endpoint}")
    return 0


def _resolve_ledgerfield_root(value: str | None) -> Path:
    candidates = []
    if value:
        candidates.append(Path(value))
    candidates.extend(
        [
            Path.cwd().parent / "ledgerfield",
            Path.home() / ".copilot" / "repos" / "ledgerfield",
            Path.home() / ".copilot" / "copilot-worktrees" / "ledgerfield",
        ]
    )
    for candidate in candidates:
        if (candidate / "data").is_dir():
            return candidate.resolve()
    raise SystemExit(
        "Ledgerfield root not found. Pass --ledgerfield-root or set LEDGERFIELD_ROOT."
    )


def _hydrate_defaults_from_azure(args: argparse.Namespace) -> None:
    if not args.subscription_id:
        args.subscription_id = _az_json(["account", "show", "--query", "id", "-o", "tsv"]).strip()

    if (
        not args.ai_account_name
        or not args.ai_services_endpoint
        or not args.search_service_name
        or not args.storage_account_name
    ):
        resources = _az_json(["resource", "list", "-g", args.resource_group, "-o", "json"])
        for resource in json.loads(resources):
            resource_type = resource.get("type", "")
            name = resource.get("name", "")
            kind = resource.get("kind", "")
            if not args.ai_account_name and resource_type == "Microsoft.CognitiveServices/accounts" and kind == "AIServices":
                args.ai_account_name = name
            if (
                not args.ai_services_endpoint
                and resource_type == "Microsoft.CognitiveServices/accounts"
                and kind == "AIServices"
            ):
                properties = resource.get("properties") or {}
                args.ai_services_endpoint = (
                    properties.get("endpoint")
                    or f"https://{name}.cognitiveservices.azure.com/"
                )
            elif not args.search_service_name and resource_type == "Microsoft.Search/searchServices":
                args.search_service_name = name
            elif not args.storage_account_name and resource_type == "Microsoft.Storage/storageAccounts":
                args.storage_account_name = name

    if args.ai_account_name and not args.ai_services_endpoint:
        args.ai_services_endpoint = _az_json(
            [
                "cognitiveservices",
                "account",
                "show",
                "-g",
                args.resource_group,
                "-n",
                args.ai_account_name,
                "--query",
                "properties.endpoint",
                "-o",
                "tsv",
            ]
        ).strip()


def _stage_ledgerfield_contracts(ledgerfield_root: Path, staging: Path, contracts_folder: str) -> None:
    source_dir = ledgerfield_root / "data" / "contracts" / "source-markdown"
    target_dir = staging / contracts_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    contract_count = 0
    for source in sorted(source_dir.glob("*.md")):
        shutil.copy2(source, target_dir / source.name)
        contract_count += 1
    if contract_count == 0:
        raise SystemExit(f"No Ledgerfield contract Markdown files found in {source_dir}")
    print(f"Staged {contract_count} Ledgerfield contract files under {contracts_folder}/")


def _upload_documents(storage_account: str, container: str, source: Path) -> None:
    print(f"Uploading Ledgerfield documents from {source}")
    _az(
        [
            "storage",
            "blob",
            "upload-batch",
            "--account-name",
            storage_account,
            "--auth-mode",
            "login",
            "--destination",
            container,
            "--source",
            str(source),
            "--overwrite",
            "true",
            "--output",
            "none",
        ]
    )


def _knowledge_source_body(
    *,
    args: argparse.Namespace,
    storage_resource_id: str,
    ai_endpoint: str,
) -> dict[str, Any]:
    return {
        "name": args.knowledge_source_name,
        "kind": "azureBlob",
        "description": "Ledgerfield supplier contract documents for Forge invoice assurance.",
        "encryptionKey": None,
        "azureBlobParameters": {
            "connectionString": f"ResourceId={storage_resource_id};",
            "containerName": args.storage_container_name,
            "folderPath": args.contracts_folder,
            "isADLSGen2": False,
            "ingestionParameters": {
                "identity": None,
                "disableImageVerbalization": True,
                "contentExtractionMode": "standard",
                "ingestionSchedule": None,
                "ingestionPermissionOptions": [],
                "embeddingModel": {
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": {
                        "resourceUri": ai_endpoint,
                        "deploymentId": args.embedding_deployment_name,
                        "modelName": args.embedding_model_name,
                    },
                },
                "aiServices": {"uri": ai_endpoint},
            },
        },
    }


def _knowledge_base_body(*, args: argparse.Namespace, ai_endpoint: str) -> dict[str, Any]:
    body = {
        "name": args.knowledge_base_name,
        "description": "Ledgerfield supplier contracts for contract-manufacturing invoice assurance.",
        "retrievalInstructions": (
            "Retrieve governing contract clauses for the supplier already resolved by the invoice workflow. "
            "Prefer evidence from matching supplier names or aliases in the contract source and avoid "
            "cross-supplier evidence unless the caller explicitly asks for comparison."
        ),
        "answerInstructions": (
            "Answer with concise contract evidence. Cite source documents and clause/section names whenever "
            "available. Do not invent missing contract terms or supplier relationships."
        ),
        "outputMode": "answerSynthesis",
        "knowledgeSources": [{"name": args.knowledge_source_name}],
        "models": [
            {
                "kind": "azureOpenAI",
                "azureOpenAIParameters": {
                    "resourceUri": ai_endpoint,
                    "deploymentId": args.chat_deployment_name,
                    "modelName": args.chat_model_name,
                },
            }
        ],
        "encryptionKey": None,
    }
    effort = str(args.retrieval_reasoning_effort or "").strip()
    if effort and effort.lower() not in {"0", "false", "no", "none", "off", "disabled"}:
        body["retrievalReasoningEffort"] = {"kind": effort}
    return body


def _put_search_resource(
    *,
    uri: str,
    token: str,
    body: dict[str, Any],
    force: bool,
    dependent_uri: str | None,
    display_name: str,
) -> None:
    try:
        _json_request("PUT", uri, token, body)
    except HTTPError:
        if not force:
            raise
        print(f"Recreating {display_name} because update failed and --force was provided.")
        if dependent_uri:
            _json_request("DELETE", dependent_uri, token, allow_not_found=True)
        _json_request("DELETE", uri, token, allow_not_found=True)
        _json_request("PUT", uri, token, body)


def _json_request(
    method: str,
    uri: str,
    token: str,
    body: dict[str, Any] | None = None,
    *,
    allow_not_found: bool = False,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        uri,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
    )
    try:
        with urlopen(request, timeout=120) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else None
    except HTTPError as error:
        if allow_not_found and error.code == 404:
            return None
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} from {method} {uri}: {details}") from error


def _validate_deployment(resource_group: str, ai_account: str, deployment: str) -> None:
    try:
        _az(
            [
                "cognitiveservices",
                "account",
                "deployment",
                "show",
                "-g",
                resource_group,
                "-n",
                ai_account,
                "--deployment-name",
                deployment,
                "--only-show-errors",
                "-o",
                "none",
            ]
        )
    except RuntimeError as error:
        raise SystemExit(
            f"Required model deployment '{deployment}' was not found on {ai_account}. "
            "Create it first or pass the correct deployment name."
        ) from error


def _az_token(resource: str) -> str:
    return _az_json(
        ["account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"]
    ).strip()


def _az_json(args: list[str]) -> str:
    return _az(args, capture=True)


def _az(args: list[str], *, capture: bool = False) -> str:
    az_executable = shutil.which("az") or shutil.which("az.cmd")
    if az_executable is None:
        raise RuntimeError("Azure CLI executable 'az' was not found on PATH.")
    process = subprocess.run(
        [az_executable, *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"az {' '.join(args)} failed with exit code {process.returncode}: "
            f"{process.stdout}{process.stderr}"
        )
    if process.stderr.strip():
        print(process.stderr.strip(), file=sys.stderr)
    return process.stdout if capture else ""


def _require_path(path: Path, description: str) -> None:
    if not path.exists():
        raise SystemExit(f"{description} not found: {path}")


def _require_args(args: argparse.Namespace, *names: str) -> None:
    missing = [name.replace("_", "-") for name in names if not getattr(args, name)]
    if missing:
        raise SystemExit(f"Missing required values: {', '.join(missing)}")


if __name__ == "__main__":
    raise SystemExit(main())
