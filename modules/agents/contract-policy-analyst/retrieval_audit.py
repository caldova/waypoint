"""Durable evaluator-only capture of actual tool payloads; never model-visible gold."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Iterator

from castia.runtime.request_context import current_request_context
from opentelemetry.trace import get_current_span

_TURN: ContextVar[dict[str, Any] | None] = ContextVar("cpa_audit_turn", default=None)


@contextmanager
def capture(task: str, config: dict[str, str]) -> Iterator[dict[str, Any]]:
    context = current_request_context()
    span = get_current_span().get_span_context()
    record = {
        "id": uuid.uuid4().hex,
        "created_at": datetime.now(UTC).isoformat(),
        "task_sha256": hashlib.sha256(task.encode("utf-8")).hexdigest(),
        "config": config,
        "platform_call_id": context.call_id if context else None,
        "trace_id": f"{span.trace_id:032x}" if span.is_valid else None,
        "parent_span_id": f"{span.span_id:016x}" if span.is_valid else None,
        "tool_calls": [],
    }
    token = _TURN.set(record)
    try:
        yield record
    finally:
        _TURN.reset(token)


def record_tool(query: Any, result: dict[str, Any]) -> None:
    record = _TURN.get()
    if record is not None:
        span = get_current_span().get_span_context()
        record["tool_calls"].append({
            "name": "contracts-kb-mcp___knowledge_base_retrieve",
            "query": str(query or "").strip()[:400],
            "status": "succeeded" if result.get("ok") else "failed",
            "result": result,
            "tool_span_id": f"{span.span_id:016x}" if span.is_valid else None,
        })


async def persist(record: dict[str, Any], output: str | None) -> None:
    endpoint = os.getenv("CPA_AUDIT_ACCOUNT_URL", "").strip()
    if not endpoint:
        return
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    record["completed_at"] = datetime.now(UTC).isoformat()
    record["output_sha256"] = hashlib.sha256((output or "").encode("utf-8")).hexdigest()
    record["call_completed"] = output is not None
    name = f"attempts/{record['task_sha256']}/{record['output_sha256']}/{record['id']}.json"
    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(endpoint, credential=credential) as service:
            client = service.get_container_client("cpa-eval-audits")
            await client.upload_blob(
                name=name, data=json.dumps(record, ensure_ascii=False).encode("utf-8"),
                overwrite=False,
            )
