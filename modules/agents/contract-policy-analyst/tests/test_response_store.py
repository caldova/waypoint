import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
from response_store import BlobResponseStore


class FakeBlob:
    def __init__(self, status="in_progress", error=None):
        self.record = {"response": {"id": "resp_test", "status": status}}
        self.error = error
        self.writes = []
        self.properties = SimpleNamespace(etag='"original-etag"')

    async def download_blob(self):
        if self.error:
            raise self.error
        return self

    async def readall(self):
        return json.dumps(self.record).encode()

    async def upload_blob(self, data, **kwargs):
        self.writes.append((json.loads(data), kwargs))


class TestStore(BlobResponseStore):
    __test__ = False

    def __init__(self, blob):
        self.blob = blob

    @asynccontextmanager
    async def _blob(self, response_id):
        yield self.blob


def test_updates_are_conditional_and_preserve_complete_record():
    blob = FakeBlob()
    record = {
        "response": {"id": "resp_test", "status": "completed"},
        "user_id": "test-owner", "input_items": [{"text": "evidence"}], "background": True,
    }
    assert asyncio.run(TestStore(blob).update(record, expected_status="in_progress"))
    assert blob.writes == [(record, {
        "overwrite": True, "etag": '"original-etag"',
        "match_condition": MatchConditions.IfNotModified,
    })]


def test_terminal_state_is_not_overwritten_by_stale_worker():
    blob = FakeBlob(status="cancelled")
    record = {"response": {"id": "resp_test", "status": "completed"}}
    assert not asyncio.run(TestStore(blob).update(record, expected_status="in_progress"))
    assert not blob.writes


@pytest.mark.parametrize("error", [ResourceNotFoundError(), ResourceModifiedError()])
def test_missing_or_concurrently_changed_record_is_not_upserted(error):
    blob = FakeBlob(error=error)
    record = {"response": {"id": "resp_test", "status": "completed"}}
    assert not asyncio.run(TestStore(blob).update(record, expected_status="in_progress"))
    assert not blob.writes


def test_backend_failure_is_not_a_missing_response():
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(TestStore(FakeBlob(error=RuntimeError("unavailable"))).get("resp_test"))


def test_create_is_create_only():
    blob = FakeBlob()
    asyncio.run(TestStore(blob).create(blob.record))
    assert blob.writes[0][1] == {"overwrite": False}


def test_capture_operator_settings_are_required_for_background_store(monkeypatch):
    monkeypatch.delenv("CASTIA_TOOL_CAPTURE", raising=False)
    assert BlobResponseStore.from_env() is None
    monkeypatch.setenv("CASTIA_TOOL_CAPTURE", "blob")
    monkeypatch.setenv("CASTIA_TOOL_CAPTURE_BLOB_ACCOUNT_URL", "http://example.invalid")
    with pytest.raises(ValueError, match="HTTPS"):
        BlobResponseStore.from_env()
