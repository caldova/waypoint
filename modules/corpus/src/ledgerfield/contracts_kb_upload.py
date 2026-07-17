"""Seed the ``contracts-kb`` Foundry IQ knowledge base from the Ledgerfield corpus.

The Foundry IQ knowledge base ``contracts-kb`` (Microsoft Foundry project ``ai-project-forge``)
is backed by a knowledge source ``contracts-ks`` of type **Azure Blob Storage**: Azure AI Search
indexes the blobs in a container, and the ``foundryiq-expert`` agent retrieves grounded contract
evidence from that index.

This module is the *writer* side of that pipeline. It performs an **idempotent, self-cleaning
sync** of the supplier contract documents into the blob container:

* every current contract document is uploaded (overwrite) under ``{prefix}/`` , and
* any blob already under ``{prefix}/`` that is *not* part of the current corpus is deleted.

The delete pass is what makes a rename safe: when the corpus moves from ``cmo-0NN-*`` to
``sup-0NN-*`` the stale ``cmo-*`` blobs are removed automatically, so the index never mixes old
and new supplier ids. Re-running with an unchanged corpus is a no-op beyond re-uploading identical
bytes, so the command is safe to run on every deploy.

Optionally the Azure AI Search indexer that feeds the knowledge source can be triggered so the
index reflects the new blobs immediately instead of waiting for its schedule.

Authentication uses ``DefaultAzureCredential`` throughout, so the same code path works for a CI
OIDC identity and a developer's ``az login``. Heavy Azure SDK imports are done lazily inside the
functions that need them, so the rest of the ``ledgerfield`` CLI keeps working without them
installed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .paths import data_path, repo_root

logger = logging.getLogger(__name__)

DEFAULT_CONTAINER = "knowledge"
DEFAULT_PREFIX = "contracts"
DEFAULT_SEARCH_API_VERSION = "2024-07-01"

# Token scope for the Azure AI Search data/control plane (used to trigger an indexer run with the
# caller's Azure AD identity instead of an admin key).
_SEARCH_TOKEN_SCOPE = "https://search.azure.com/.default"

# On-disk contract/policy sources mapped to a blob "folder" (virtual directory) under the prefix.
# Filenames are preserved verbatim so retrieval can cite them and so the self-cleaning sync can
# match desired vs existing blobs by exact name. Policies are opt-in because ``contracts-kb`` is
# scoped to supplier contracts; enable them with ``include_policies=True``.
_CONTRACT_SOURCES: tuple[tuple[str, str], ...] = (
    ("contracts/source-markdown", "*.md"),
)
_POLICY_SOURCES: tuple[tuple[str, str], ...] = (
    ("policies/source-markdown", "*.md"),
)


@dataclass
class BlobDocument:
    """A single document to place in the knowledge-source container."""

    name: str
    data: bytes


@dataclass
class ContractsKbSummary:
    """Counts returned to the CLI for human/agent-readable logging."""

    storage_account: str
    container: str
    prefix: str
    uploaded: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    reindex: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "storage_account": self.storage_account,
            "container": self.container,
            "prefix": self.prefix,
            "uploaded": sorted(self.uploaded),
            "uploaded_total": len(self.uploaded),
            "deleted": sorted(self.deleted),
            "deleted_total": len(self.deleted),
            "reindex": self.reindex,
        }


# --------------------------------------------------------------------------------------
# Document discovery
# --------------------------------------------------------------------------------------


def _collect_documents(data_root: Path, *, include_policies: bool) -> list[BlobDocument]:
    sources = list(_CONTRACT_SOURCES)
    if include_policies:
        sources += list(_POLICY_SOURCES)

    documents: list[BlobDocument] = []
    seen: set[str] = set()
    for relative_folder, pattern in sources:
        folder = data_root / relative_folder
        if not folder.exists():
            logger.warning("contracts-kb: source folder missing, skipping: %s", folder)
            continue
        for path in sorted(folder.glob(pattern)):
            if path.name in seen:
                raise ValueError(
                    f"Duplicate document name '{path.name}' across contracts-kb sources; "
                    "blob names must be unique within the container prefix."
                )
            seen.add(path.name)
            documents.append(BlobDocument(name=path.name, data=path.read_bytes()))
    return documents


def _regenerate_artifacts(root: Path) -> None:
    """Deterministically regenerate contract DOCX before upload (source markdown is canonical).

    Only relevant when uploading DOCX; the default markdown upload reads the canonical source
    files directly. Kept as a hook so ``--format docx`` stays consistent with the OneLake path.
    """

    from .docx_docs import generate_docx_documents

    generate_docx_documents(root)


# --------------------------------------------------------------------------------------
# Blob container client + sync
# --------------------------------------------------------------------------------------


def _container_client(storage_account: str, container: str, account_url: str | None):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    endpoint = account_url or f"https://{storage_account}.blob.core.windows.net"
    service = BlobServiceClient(account_url=endpoint, credential=DefaultAzureCredential())
    return service.get_container_client(container)


def _blob_path(prefix: str, name: str) -> str:
    prefix = prefix.strip("/")
    return f"{prefix}/{name}" if prefix else name


def _existing_blob_names(container_client, prefix: str) -> Iterator[str]:
    listing_prefix = prefix.strip("/")
    listing_prefix = f"{listing_prefix}/" if listing_prefix else None
    for blob in container_client.list_blobs(name_starts_with=listing_prefix):
        yield blob.name


def _sync_documents(
    container_client,
    prefix: str,
    documents: list[BlobDocument],
    summary: ContractsKbSummary,
) -> None:
    desired: dict[str, BlobDocument] = {_blob_path(prefix, doc.name): doc for doc in documents}

    # Upload / overwrite every desired document.
    for blob_path, doc in sorted(desired.items()):
        container_client.upload_blob(name=blob_path, data=doc.data, overwrite=True)
        summary.uploaded.append(blob_path)
        logger.info("Uploaded blob %s", blob_path)

    # Delete any blob under the prefix that is not part of the current corpus (removes stale
    # renamed documents so the index never mixes old and new supplier ids).
    for existing in _existing_blob_names(container_client, prefix):
        if existing not in desired:
            container_client.delete_blob(existing)
            summary.deleted.append(existing)
            logger.info("Deleted stale blob %s", existing)


# --------------------------------------------------------------------------------------
# Optional Azure AI Search indexer trigger
# --------------------------------------------------------------------------------------


def _run_indexer(search_endpoint: str, indexer: str, api_version: str) -> dict[str, Any]:
    import json
    import urllib.error
    import urllib.request

    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token(_SEARCH_TOKEN_SCOPE).token
    url = f"{search_endpoint.rstrip('/')}/indexers/{indexer}/run?api-version={api_version}"
    request = urllib.request.Request(  # noqa: S310 - trusted Azure Search URL
        url,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Length": "0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            status = response.status
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise RuntimeError(
            f"Search indexer '{indexer}' run failed ({error.code}): {detail}"
        ) from error
    logger.info("Triggered Azure AI Search indexer '%s' (HTTP %s)", indexer, status)
    return {"triggered": True, "indexer": indexer, "status": status}


# --------------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------------


def upload_contracts_kb(
    root: Path | None = None,
    *,
    storage_account: str,
    container: str = DEFAULT_CONTAINER,
    prefix: str = DEFAULT_PREFIX,
    account_url: str | None = None,
    include_policies: bool = False,
    regenerate: bool = False,
    search_endpoint: str | None = None,
    indexer: str | None = None,
    search_api_version: str = DEFAULT_SEARCH_API_VERSION,
) -> dict[str, Any]:
    """Sync the supplier contracts into the ``contracts-ks`` blob container and optionally reindex.

    Idempotent: uploads the current contract corpus and deletes any stale blobs under ``prefix``.
    Raises on any failure so callers exit non-zero. ``storage_account`` (or ``account_url``) is
    required so the target container is unambiguous.
    """

    if not storage_account and not account_url:
        raise ValueError(
            "A storage account is required: pass --storage-account (or --account-url)."
        )

    root = root or repo_root()
    data_root = data_path(root)

    if regenerate:
        logger.info("Regenerating contract artifacts before upload.")
        _regenerate_artifacts(root)

    documents = _collect_documents(data_root, include_policies=include_policies)
    if not documents:
        raise ValueError("No contract documents found to upload; refusing to empty the container.")

    summary = ContractsKbSummary(
        storage_account=storage_account or (account_url or ""),
        container=container,
        prefix=prefix.strip("/"),
    )

    container_client = _container_client(storage_account, container, account_url)
    _sync_documents(container_client, prefix, documents, summary)

    if search_endpoint and indexer:
        summary.reindex = _run_indexer(search_endpoint, indexer, search_api_version)
    else:
        summary.reindex = {
            "triggered": False,
            "reason": "no --search-endpoint provided; relying on the daily indexer schedule",
        }

    return summary.as_dict()
