"""Publish generated Contracts reports to local storage or agent-owned SharePoint."""

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


def sharepoint_report_publishing_configured() -> bool:
    return bool(_usable_env("CONTRACTS_REPORTS_DRIVE_ID") and _usable_env("CONTRACTS_REPORTS_FOLDER_ITEM_ID"))


def report_publisher() -> LocalReportPublisher | GraphSharePointReportPublisher:
    mode = (_usable_env("CONTRACTS_REPORTS_PUBLISH_MODE") or "auto").lower()
    if mode == "local":
        return LocalReportPublisher()
    if mode == "sharepoint" or sharepoint_report_publishing_configured():
        return GraphSharePointReportPublisher()
    return LocalReportPublisher()
