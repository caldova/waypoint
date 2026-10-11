"""Publish generated Contracts reports to local storage, the agent's OneDrive, or SharePoint."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from azure.identity.aio import DefaultAzureCredential


def _usable_env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


@dataclass(frozen=True)
class PublishedReport:
    file_url: str
    share_status: str
    storage: str
    web_url: str | None = None
    share_url: str | None = None
    drive_item: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @property
    def teams_link_url(self) -> str:
        return self.share_url or self.web_url or self.file_url


class LocalReportPublisher:
    async def publish(self, *, docx_path: Path, markdown_path: Path, title: str) -> PublishedReport:
        return PublishedReport(
            file_url=docx_path.as_uri(),
            share_status="not_shared_local_file",
            storage="local",
            metadata={
                "docx_file_url": docx_path.as_uri(),
                "markdown_file_url": markdown_path.as_uri(),
                "report_format": "docx",
            },
        )


class GraphSharePointReportPublisher:
    def __init__(self) -> None:
        drive_id = _usable_env("CONTRACTS_REPORTS_DRIVE_ID")
        folder_item_id = _usable_env("CONTRACTS_REPORTS_FOLDER_ITEM_ID")
        if not drive_id or not folder_item_id:
            raise RuntimeError(
                "CONTRACTS_REPORTS_DRIVE_ID and CONTRACTS_REPORTS_FOLDER_ITEM_ID are required "
                "for SharePoint report publishing."
            )
        self._drive_id = drive_id
        self._folder_item_id = folder_item_id
        self._scope = _usable_env("CONTRACTS_REPORTS_SCOPE") or "https://graph.microsoft.com/.default"
        self._link_type = _usable_env("CONTRACTS_REPORTS_LINK_TYPE") or "view"
        self._link_scope = _usable_env("CONTRACTS_REPORTS_LINK_SCOPE") or "organization"
        self._graph_base = (_usable_env("CONTRACTS_REPORTS_GRAPH_BASE_URL") or "https://graph.microsoft.com/v1.0").rstrip("/")
        self._credential: DefaultAzureCredential | None = None

    async def _headers(self, *, content_type: str = "application/json") -> dict[str, str]:
        if self._credential is None:
            self._credential = DefaultAzureCredential()
        token = await self._credential.get_token(self._scope)
        return {
            "Authorization": f"Bearer {token.token}",
            "Accept": "application/json",
            "Content-Type": content_type,
        }

    async def publish(self, *, docx_path: Path, markdown_path: Path, title: str) -> PublishedReport:
        file_name = docx_path.name
        encoded_name = quote(file_name, safe="")
        upload_url = (
            f"{self._graph_base}/drives/{self._drive_id}/items/"
            f"{self._folder_item_id}:/{encoded_name}:/content"
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            upload_response = await client.put(
                upload_url,
                headers=await self._headers(
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content=docx_path.read_bytes(),
            )
            if upload_response.is_error:
                raise RuntimeError(
                    "SharePoint report upload failed with HTTP "
                    f"{upload_response.status_code}: {upload_response.text[:500]}"
                )
            drive_item = upload_response.json()
            item_id = str(drive_item.get("id") or "")
            if not item_id:
                raise RuntimeError("SharePoint report upload succeeded but did not return a drive item id.")

            share_response = await client.post(
                f"{self._graph_base}/drives/{self._drive_id}/items/{item_id}/createLink",
                headers=await self._headers(),
                json={"type": self._link_type, "scope": self._link_scope},
            )
            if share_response.is_error:
                raise RuntimeError(
                    "SharePoint report link creation failed with HTTP "
                    f"{share_response.status_code}: {share_response.text[:500]}"
                )
            permission = share_response.json()

        share_url = None
        link = permission.get("link") if isinstance(permission, dict) else None
        if isinstance(link, dict):
            share_url = link.get("webUrl")
        web_url = drive_item.get("webUrl")
        file_url = share_url or web_url
        if not file_url:
            raise RuntimeError("SharePoint report publishing did not return a webUrl or sharing link.")

        return PublishedReport(
            file_url=file_url,
            share_status="shared_link_created",
            storage="sharepoint",
            web_url=web_url,
            share_url=share_url,
            drive_item=drive_item,
            metadata={
                "docx_file_url": docx_path.as_uri(),
                "markdown_file_url": markdown_path.as_uri(),
                "report_format": "docx",
                "sharepoint_drive_id": self._drive_id,
                "sharepoint_folder_item_id": self._folder_item_id,
                "sharepoint_item_id": item_id,
                "sharepoint_web_url": web_url,
                "sharepoint_share_url": share_url,
            },
        )


_DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class AgentOneDriveReportPublisher:
    """Upload to the agent's own OneDrive as its agentic user, then share with the requester."""

    def __init__(self, activity: Any) -> None:
        from agent.integrations.activity_identity import activity_from

        self._activity = activity_from(activity)
        self._folder = (_usable_env("CONTRACTS_REPORTS_ONEDRIVE_FOLDER") or "Contracts Reports").strip("/")
        self._role = _usable_env("CONTRACTS_REPORTS_SHARE_ROLE") or "read"
        self._graph_base = (_usable_env("CONTRACTS_REPORTS_GRAPH_BASE_URL") or "https://graph.microsoft.com/v1.0").rstrip("/")

    def _requester_object_id(self) -> str:
        sender = getattr(self._activity, "from_property", None) or getattr(self._activity, "from_", None)
        object_id = getattr(sender, "aad_object_id", None) if sender else None
        if not object_id:
            raise RuntimeError("Cannot share the report: the turn has no requester Entra object id.")
        return str(object_id)

    async def _ensure_folder(self, client: httpx.AsyncClient, auth: str, segments: list[str]) -> None:
        """Create each missing folder in the path; Graph path uploads do not create parents."""
        parent = ""
        for seg in segments:
            current = f"{parent}/{quote(seg, safe='')}" if parent else quote(seg, safe="")
            found = await client.get(f"{self._graph_base}/me/drive/root:/{current}", headers={"Authorization": auth})
            if found.status_code == 404:
                children = f"root:/{parent}:/children" if parent else "root/children"
                created = await client.post(
                    f"{self._graph_base}/me/drive/{children}",
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                    json={"name": seg, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
                )
                if created.is_error and created.status_code != 409:
                    raise RuntimeError(
                        f"OneDrive folder create failed with HTTP {created.status_code}: {created.text[:500]}"
                    )
            elif found.is_error:
                raise RuntimeError(f"OneDrive folder lookup failed with HTTP {found.status_code}: {found.text[:500]}")
            parent = current

    async def publish(self, *, docx_path: Path, markdown_path: Path, title: str) -> PublishedReport:
        from castia.hosting.credentials import agentic_user_token, bearer
        from castia.hosting.identity import require_agentic_user

        requester = self._requester_object_id()
        auth = bearer(await agentic_user_token(require_agentic_user(self._activity)))
        segments = [seg for seg in self._folder.split("/") if seg]
        path = "/".join(quote(seg, safe="") for seg in [*segments, docx_path.name])

        async with httpx.AsyncClient(timeout=60.0) as client:
            await self._ensure_folder(client, auth, segments)
            upload = await client.put(
                f"{self._graph_base}/me/drive/root:/{path}:/content",
                headers={"Authorization": auth, "Content-Type": _DOCX_CONTENT_TYPE},
                content=docx_path.read_bytes(),
            )
            if upload.is_error:
                raise RuntimeError(
                    f"OneDrive report upload failed with HTTP {upload.status_code}: {upload.text[:500]}"
                )
            drive_item = upload.json()
            item_id = str(drive_item.get("id") or "")
            if not item_id:
                raise RuntimeError("OneDrive report upload succeeded but did not return a drive item id.")

            invite = await client.post(
                f"{self._graph_base}/me/drive/items/{item_id}/invite",
                headers={"Authorization": auth, "Content-Type": "application/json"},
                json={
                    "recipients": [{"objectId": requester}],
                    "requireSignIn": True,
                    "sendInvitation": False,
                    "roles": [self._role],
                },
            )
            if invite.is_error:
                raise RuntimeError(
                    f"OneDrive report sharing failed with HTTP {invite.status_code}: {invite.text[:500]}"
                )

        web_url = drive_item.get("webUrl")
        if not web_url:
            raise RuntimeError("OneDrive report upload did not return a webUrl.")
        return PublishedReport(
            file_url=web_url,
            share_status="shared_link_created",
            storage="onedrive",
            web_url=web_url,
            drive_item=drive_item,
            metadata={
                "docx_file_url": docx_path.as_uri(),
                "markdown_file_url": markdown_path.as_uri(),
                "report_format": "docx",
                "onedrive_item_id": item_id,
                "onedrive_web_url": web_url,
                "shared_with_object_id": requester,
                "share_role": self._role,
            },
        )


def sharepoint_report_publishing_configured() -> bool:
    return bool(_usable_env("CONTRACTS_REPORTS_DRIVE_ID") and _usable_env("CONTRACTS_REPORTS_FOLDER_ITEM_ID"))


def report_publisher(
    activity: Any = None,
) -> LocalReportPublisher | GraphSharePointReportPublisher | AgentOneDriveReportPublisher:
    from agent.integrations.activity_identity import has_agentic_user_identity

    mode = (_usable_env("CONTRACTS_REPORTS_PUBLISH_MODE") or "auto").lower()
    if mode == "local":
        return LocalReportPublisher()
    if mode == "onedrive" or (mode == "auto" and has_agentic_user_identity(activity)):
        return AgentOneDriveReportPublisher(activity)
    if mode == "sharepoint" or sharepoint_report_publishing_configured():
        return GraphSharePointReportPublisher()
    return LocalReportPublisher()
