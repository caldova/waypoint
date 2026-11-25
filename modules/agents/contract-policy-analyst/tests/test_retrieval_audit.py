import asyncio
import json

import pytest

import retrieval_audit


def test_capture_retains_real_payload_and_isolates_turns():
    payload = {"ok": True, "content": [{"type": "text", "text": "actual retrieved source"}]}
    with retrieval_audit.capture("outer", {"model": "one"}) as outer:
        retrieval_audit.record_tool("query one", payload)
        with retrieval_audit.capture("inner", {"model": "two"}) as inner:
            retrieval_audit.record_tool("query two", {"ok": False, "error": "timeout"})
        retrieval_audit.record_tool("query three", payload)
    assert len(outer["tool_calls"]) == 2
    assert inner["tool_calls"][0]["status"] == "failed"
    assert outer["tool_calls"][0]["result"] == payload


def test_offline_capture_does_not_acquire_credentials(monkeypatch):
    import azure.identity.aio

    monkeypatch.delenv("CPA_AUDIT_ACCOUNT_URL", raising=False)
    monkeypatch.setattr(
        azure.identity.aio, "DefaultAzureCredential",
        lambda: pytest.fail("Offline capture must not acquire credentials."),
    )
    with retrieval_audit.capture("task", {"model": "test"}) as record:
        asyncio.run(retrieval_audit.persist(record, "output"))


def test_storage_audit_is_immutable_and_failure_is_not_suppressed(monkeypatch):
    import azure.identity.aio
    import azure.storage.blob.aio

    uploads = []

    class Credential:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Service(Credential):
        def __init__(self, *args, **kwargs):
            pass

        def get_container_client(self, name):
            assert name == "cpa-eval-audits"
            return self

        async def upload_blob(self, **kwargs):
            uploads.append(kwargs)
            raise RuntimeError("storage unavailable")

    monkeypatch.setenv("CPA_AUDIT_ACCOUNT_URL", "https://example.blob.core.windows.net")
    monkeypatch.setattr(azure.identity.aio, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(azure.storage.blob.aio, "BlobServiceClient", Service)
    with retrieval_audit.capture("task", {"model": "test"}) as record:
        retrieval_audit.record_tool("query", {"ok": True, "content": []})
        with pytest.raises(RuntimeError, match="storage unavailable"):
            asyncio.run(retrieval_audit.persist(record, "answer"))
    assert not uploads[0]["overwrite"]
    saved = json.loads(uploads[0]["data"])
    assert saved["task_sha256"] == record["task_sha256"]
    assert saved["tool_calls"] == record["tool_calls"]
