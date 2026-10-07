"""Foundry telemetry helpers that should move into Castia."""

from __future__ import annotations

from collections.abc import MutableMapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from opentelemetry import propagate, trace
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.trace import SpanKind, Status, StatusCode

LEAF_CUSTOMER_SPAN_ID_HEADER = "leaf_customer_span_id"
TOOLBOX_POST_SPAN_ATTRIBUTE = "castia.foundry.toolbox.post"


def leaf_customer_span_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return (
        f"00-{span_context.trace_id:032x}-"
        f"{span_context.span_id:016x}-{int(span_context.trace_flags):02x}"
    )


def add_leaf_customer_span_id_header(headers: MutableMapping[str, str]) -> None:
    value = leaf_customer_span_id()
    if value:
        headers[LEAF_CUSTOMER_SPAN_ID_HEADER] = value


@contextmanager
def foundry_toolbox_post_span(endpoint: str, headers: MutableMapping[str, str]) -> Any:
    tracer = trace.get_tracer("castia.foundry.telemetry")
    parsed = urlparse(endpoint)
    span_name = f"POST {parsed.path}" if parsed.path else "POST"

    with tracer.start_as_current_span(span_name, kind=SpanKind.CLIENT) as span:
        span.set_attribute(TOOLBOX_POST_SPAN_ATTRIBUTE, True)
        span.set_attribute("http.request.method", "POST")
        span.set_attribute("http.method", "POST")
        span.set_attribute("url.full", endpoint)
        span.set_attribute("http.url", endpoint)
        if parsed.hostname:
            span.set_attribute("server.address", parsed.hostname)
        propagate.inject(headers)
        add_leaf_customer_span_id_header(headers)
        with suppress_instrumentation():
            yield span


def record_toolbox_post_response(span: Any, status_code: int, *, is_error: bool) -> None:
    span.set_attribute("http.response.status_code", status_code)
    span.set_attribute("http.status_code", status_code)
    if is_error:
        span.set_status(Status(StatusCode.ERROR))
