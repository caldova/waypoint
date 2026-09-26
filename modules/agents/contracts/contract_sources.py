"""Contract document sources for local and hosted Contracts runs."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ArtifactType = Literal["contract", "invoice"]


@dataclass(frozen=True)
class ContractAttachment:
    mailbox_id: str
    message_id: str
    attachment_id: str
    sender: str
    owner_user_id: str
    subject: str
    artifact_type: ArtifactType
    file_name: str
    content_type: str
    sha256: str
    size_bytes: int
    original_file_uri: str
    source_mode: str
    pdf_bytes: bytes


def _usable_env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


def _is_local_base_url(value: str | None) -> bool:
    value = (value or "").rstrip("/")
    return value.startswith(
        (
            "http://127.0.0.1",
            "https://127.0.0.1",
            "http://localhost",
            "https://localhost",
        )
    )


def _fixture_pdf_path(artifact_type: ArtifactType | None = None) -> Path:
    configured = _usable_env("CONTRACTS_LOCAL_PDF_PATH")
    if configured:
        return Path(configured)
    artifact_type = artifact_type or _local_document_kind()
    if artifact_type == "invoice":
        invoice_path = _usable_env("CONTRACTS_LOCAL_INVOICE_PDF_PATH")
        if invoice_path:
            return Path(invoice_path)
        return (
            Path(__file__).resolve().parent
            / "fixtures"
            / "invoices"
            / "sup-001-inv-sup-001-2026-10.pdf"
        )
    return Path(__file__).resolve().parent / "fixtures" / "contracts" / "aster-ridge-sow.pdf"


def _local_document_kind(artifact_type: str | None = None) -> ArtifactType:
    configured = (artifact_type or _usable_env("CONTRACTS_LOCAL_DOCUMENT_KIND") or "contract").lower()
    if configured == "invoice":
        return "invoice"
    return "contract"


def _source_mode() -> str:
    configured = (_usable_env("CONTRACTS_DOCUMENT_SOURCE_MODE") or "auto").lower()
    if configured in {"local", "hosted"}:
        return configured
    base_url = _usable_env("WAYPOINT_API_BASE_URL")
    return "local" if _is_local_base_url(base_url) or not base_url else "hosted"


class LocalPdfContractSource:
    def next_contract(
        self,
        *,
        mailbox_id: str,
        owner_user_id: str,
        artifact_type: str | None = None,
    ) -> ContractAttachment:
        artifact_type = _local_document_kind(artifact_type)
        pdf_path = _fixture_pdf_path(artifact_type)
        pdf_bytes = pdf_path.read_bytes()
        digest = hashlib.sha256(pdf_bytes).hexdigest()
        subject = (
            "Ledgerfield supplier invoice"
            if artifact_type == "invoice"
            else "Aster Ridge Biomanufacturing Statement of Work"
        )
        return ContractAttachment(
            mailbox_id=mailbox_id,
            message_id=f"local-pdf-fixture-message-{digest[:12]}",
            attachment_id=f"local-pdf-fixture-attachment-{digest[:12]}",
            sender=owner_user_id,
            owner_user_id=owner_user_id,
            subject=subject,
            artifact_type=artifact_type,
            file_name=pdf_path.name,
            content_type="application/pdf",
            sha256=digest,
            size_bytes=len(pdf_bytes),
            original_file_uri=pdf_path.resolve().as_uri(),
            source_mode="local_pdf",
            pdf_bytes=pdf_bytes,
        )


class HostedMailboxContractSource:
    def next_contract(
        self,
        *,
        mailbox_id: str,
        owner_user_id: str,
        artifact_type: str | None = None,
    ) -> ContractAttachment:
        raise NotImplementedError(
            "Hosted mailbox polling is not implemented yet; configure "
            "CONTRACTS_DOCUMENT_SOURCE_MODE=local for local fixture PDF smoke tests."
        )


def contract_source() -> LocalPdfContractSource | HostedMailboxContractSource:
    if _source_mode() == "local":
        return LocalPdfContractSource()
    return HostedMailboxContractSource()
