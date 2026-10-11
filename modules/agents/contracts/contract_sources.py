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
    source: str = "email"


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


_GRAPH = "https://graph.microsoft.com/v1.0"
_MAX_MESSAGES = 25
_MAX_PAGES = 4


class HostedMailboxContractSource:
    """Reads PDF attachments from the agent's own mailbox (its Agent 365 agentic user).

    The delegated Graph token must come from an Agent 365 turn: only then does the
    platform bind the hosted credential to the hired instance that owns the mailbox.
    """

    async def recent_attachments(
        self,
        *,
        token: str,
        mailbox_id: str,
        lookback_minutes: int,
        artifact_type: str | None = None,
        sender: str | None = None,
    ) -> list[ContractAttachment]:
        import base64
        from datetime import UTC, datetime, timedelta

        import httpx
        from castia.hosting.credentials import bearer

        since = (datetime.now(UTC) - timedelta(minutes=max(1, lookback_minutes))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        wanted = sender.lower() if sender else None
        headers = {"Authorization": bearer(token)}
        found: list[ContractAttachment] = []
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            messages: list[dict] = []
            url: str | None = f"{_GRAPH}/me/mailFolders/inbox/messages"
            params: dict[str, str] | None = {
                "$filter": f"receivedDateTime ge {since} and hasAttachments eq true",
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime",
                "$top": str(_MAX_MESSAGES),
            }
            for _ in range(_MAX_PAGES):
                listing = await client.get(url, params=params)
                _raise_for_graph(listing, "list inbox messages")
                page = listing.json()
                messages.extend(page.get("value", []))
                url, params = page.get("@odata.nextLink"), None
                if not url:
                    break
            for message in messages:
                from_address = (
                    ((message.get("from") or {}).get("emailAddress") or {}).get("address")
                    or mailbox_id
                ).lower()
                if wanted and from_address != wanted:
                    continue
                if not _sender_allowed(from_address, mailbox_id):
                    continue
                attachments = await client.get(
                    f"{_GRAPH}/me/messages/{message['id']}/attachments"
                )
                _raise_for_graph(attachments, "list message attachments")
                subject = message.get("subject") or ""
                for item in attachments.json().get("value", []):
                    if not _is_pdf_file_attachment(item):
                        continue
                    pdf_bytes = base64.b64decode(item["contentBytes"])
                    found.append(
                        ContractAttachment(
                            mailbox_id=mailbox_id,
                            message_id=message["id"],
                            attachment_id=item["id"],
                            sender=from_address,
                            owner_user_id=from_address,
                            subject=subject,
                            artifact_type=_classify(artifact_type, subject, item.get("name")),
                            file_name=item.get("name") or "attachment.pdf",
                            content_type="application/pdf",
                            sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                            size_bytes=len(pdf_bytes),
                            original_file_uri=(
                                f"graph://users/{mailbox_id}/messages/{message['id']}"
                                f"/attachments/{item['id']}"
                            ),
                            source_mode="hosted_mailbox",
                            pdf_bytes=pdf_bytes,
                        )
                    )
        return found


_TEAMS_FILE = "application/vnd.microsoft.teams.file.download.info"


def activity_attachments(activity: object) -> list[dict]:
    """Raw inbound attachments on a Teams activity (kept as wire extras by the model)."""
    raw = getattr(activity, "activity", activity)
    value = getattr(raw, "attachments", None)
    if value is None:
        extra = getattr(raw, "model_extra", None) or {}
        value = extra.get("attachments")
    return [item for item in value or [] if isinstance(item, dict)]


def _attachment_name(item: dict) -> str:
    return str(item.get("name") or (item.get("content") or {}).get("name") or "")


def is_pdf_activity_attachment(item: dict) -> bool:
    content_type = str(item.get("contentType") or "")
    if content_type == "application/pdf":
        return True
    if content_type == _TEAMS_FILE:
        file_type = str((item.get("content") or {}).get("fileType") or "").lower()
        return file_type == "pdf" or _attachment_name(item).lower().endswith(".pdf")
    return False


async def teams_attachments(
    activity: object,
    *,
    token: str,
    owner: str,
    artifact_type: str | None = None,
) -> list[ContractAttachment]:
    """Download PDF files the user attached to this Teams message.

    Teams file uploads arrive as ``file.download.info`` with a short-lived,
    pre-authenticated ``downloadUrl``. Inline ``application/pdf`` attachments
    with a SharePoint/OneDrive ``contentUrl`` are fetched via Graph ``/shares``
    with the hire's delegated token.
    """
    import base64

    import httpx
    from castia.hosting.credentials import bearer

    async def _guard(request: httpx.Request) -> None:
        # Every hop, including redirects, must stay on Graph or tenant SharePoint over HTTPS.
        if not _trusted_file_url(str(request.url)):
            raise ValueError(f"Refusing to fetch attachment from {request.url.host!r}.")

    raw = getattr(activity, "activity", activity)
    activity_id = str(getattr(raw, "id", "") or "teams-message")
    conversation = getattr(getattr(raw, "conversation", None), "id", None) or "teams"
    found: list[ContractAttachment] = []
    async with httpx.AsyncClient(
        timeout=60.0, follow_redirects=True, event_hooks={"request": [_guard]}
    ) as client:
        for index, item in enumerate(activity_attachments(activity)):
            if not is_pdf_activity_attachment(item):
                continue
            content = item.get("content") or {}
            if item.get("contentType") == _TEAMS_FILE and content.get("downloadUrl"):
                url, headers = str(content["downloadUrl"]), {}
            elif item.get("contentUrl") and _trusted_file_url(str(item["contentUrl"])):
                share_url = str(item["contentUrl"])
                share = "u!" + base64.urlsafe_b64encode(share_url.encode()).decode().rstrip("=")
                url = f"{_GRAPH}/shares/{share}/driveItem/content"
                headers = {"Authorization": bearer(token)}
            else:
                continue
            pdf_bytes = await _bounded_download(client, url, headers)
            if not pdf_bytes.startswith(b"%PDF"):
                raise ValueError(f"Attachment {_attachment_name(item)!r} is not a PDF.")
            name = _attachment_name(item) or f"attachment-{index}.pdf"
            attachment_id = str(content.get("uniqueId") or f"{index}-{name}")
            found.append(
                ContractAttachment(
                    mailbox_id=f"teams:{conversation}",
                    message_id=activity_id,
                    attachment_id=attachment_id,
                    sender=owner,
                    owner_user_id=owner,
                    subject=name,
                    artifact_type=_classify(artifact_type, "", name),
                    file_name=name,
                    content_type="application/pdf",
                    sha256=hashlib.sha256(pdf_bytes).hexdigest(),
                    size_bytes=len(pdf_bytes),
                    original_file_uri=str(item.get("contentUrl") or content.get("downloadUrl") or name).split("?")[0],
                    source_mode="teams_upload",
                    pdf_bytes=pdf_bytes,
                    source="teams_upload",
                )
            )
    return found


_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def _trusted_file_url(url: str) -> bool:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (
        host == "graph.microsoft.com" or host.endswith(".sharepoint.com")
    )


async def _bounded_download(client: object, url: str, headers: dict[str, str]) -> bytes:
    async with client.stream("GET", url, headers=headers) as resp:  # type: ignore[attr-defined]
        if resp.status_code >= 400:
            await resp.aread()
            _raise_for_graph(resp, "download Teams attachment")
        declared = int(resp.headers.get("content-length") or 0)
        if declared > _MAX_ATTACHMENT_BYTES:
            raise ValueError(f"Attachment is larger than {_MAX_ATTACHMENT_BYTES} bytes.")
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _MAX_ATTACHMENT_BYTES:
                raise ValueError(f"Attachment is larger than {_MAX_ATTACHMENT_BYTES} bytes.")
            chunks.append(chunk)
    return b"".join(chunks)


def _allowed_sender_domains(mailbox_id: str) -> set[str]:
    """Sender domains whose attachments are read; defaults to the inbox's own domain."""
    configured = _usable_env("CONTRACTS_ALLOWED_SENDER_DOMAINS")
    if configured:
        return {d.strip().lower().lstrip("@") for d in configured.split(",") if d.strip()}
    _, _, domain = mailbox_id.rpartition("@")
    return {domain.lower()} if domain else set()


def _sender_allowed(address: str, mailbox_id: str) -> bool:
    _, at, domain = address.lower().rpartition("@")
    return bool(at) and domain in _allowed_sender_domains(mailbox_id)


def _raise_for_graph(response: object, action: str) -> None:
    status = getattr(response, "status_code", 0)
    if status >= 400:
        text = getattr(response, "text", "")[:300]
        raise RuntimeError(f"Graph {action} failed with HTTP {status}: {text}")


def _is_pdf_file_attachment(item: dict) -> bool:
    if item.get("@odata.type") != "#microsoft.graph.fileAttachment" or not item.get(
        "contentBytes"
    ):
        return False
    name = str(item.get("name") or "").lower()
    return item.get("contentType") == "application/pdf" or name.endswith(".pdf")


def _classify(requested: str | None, subject: str, file_name: str | None) -> ArtifactType:
    if requested in ("contract", "invoice"):
        return requested  # type: ignore[return-value]
    text = f"{subject} {file_name or ''}".lower()
    return "invoice" if "invoice" in text else "contract"


def contract_source() -> LocalPdfContractSource | HostedMailboxContractSource:
    if _source_mode() == "local":
        return LocalPdfContractSource()
    return HostedMailboxContractSource()
