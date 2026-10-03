"""Turn-scoped capture of invoice tool results so Teams can render them as cards."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

_captured: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "contracts_invoice_results", default=None
)


@contextlib.contextmanager
def capture_invoice_results() -> Iterator[list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    token = _captured.set(results)
    try:
        yield results
    finally:
        _captured.reset(token)


def record_invoice_result(result: dict[str, Any]) -> None:
    """Keep a successful query_invoices result when a capture is open; no-op otherwise."""
    results = _captured.get()
    if results is not None and result.get("ok") and result.get("invoices"):
        results.append(result)


def record_review_document(result: dict[str, Any]) -> None:
    """Keep a published invoice review document when a capture is open; no-op otherwise."""
    results = _captured.get()
    if results is not None and result.get("ok"):
        results.append({**result, "kind": "review_document"})
