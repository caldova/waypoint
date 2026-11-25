"""Shared Responses state for native Foundry evaluation and optimization."""

from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager

from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from castia.hosting.responses_store import StoredResponse


class BlobResponseStore:
    def __init__(self, account_url: str, container: str):
        if not account_url.startswith("https://"):
            raise ValueError("Responses storage requires an HTTPS account URL.")
        self.account_url = account_url
        self.container = container

    @classmethod
    def from_env(cls) -> BlobResponseStore | None:
        if os.getenv("CASTIA_TOOL_CAPTURE") != "blob":
            return None
        return cls(
            os.environ["CASTIA_TOOL_CAPTURE_BLOB_ACCOUNT_URL"],
            os.getenv("CASTIA_TOOL_CAPTURE_BLOB_CONTAINER", "castia-tool-captures"),
        )

    @asynccontextmanager
    async def _blob(self, response_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", response_id):
            raise ValueError("Invalid response ID.")
        async with (
            DefaultAzureCredential() as credential,
            BlobServiceClient(self.account_url, credential=credential) as service,
        ):
            yield service.get_blob_client(
                self.container, f"responses/contract-policy-analyst/{response_id}.json",
            )

    async def create(self, record: StoredResponse) -> None:
        async with self._blob(record["response"]["id"]) as blob:
            await blob.upload_blob(json.dumps(record, ensure_ascii=False), overwrite=False)

    async def get(self, response_id: str) -> StoredResponse | None:
        async with self._blob(response_id) as blob:
            try:
                download = await blob.download_blob()
            except ResourceNotFoundError:
                return None
            return json.loads(await download.readall())

    async def update(self, record: StoredResponse, *, expected_status: str) -> bool:
        async with self._blob(record["response"]["id"]) as blob:
            try:
                download = await blob.download_blob()
                current = json.loads(await download.readall())
                if current["response"]["status"] != expected_status:
                    return False
                await blob.upload_blob(
                    json.dumps(record, ensure_ascii=False), overwrite=True,
                    etag=download.properties.etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            except (ResourceModifiedError, ResourceNotFoundError):
                return False
            return True

    async def delete(self, response_id: str) -> bool:
        async with self._blob(response_id) as blob:
            try:
                await blob.delete_blob()
            except ResourceNotFoundError:
                return False
            return True
