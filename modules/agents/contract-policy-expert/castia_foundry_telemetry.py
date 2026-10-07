"""Foundry telemetry helpers that should move into Castia.

The helpers are intentionally tiny and opt-in so hosted runtime behavior is
unchanged unless local telemetry export is explicitly enabled.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping, Sequence
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from opentelemetry import propagate, trace
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.trace import SpanKind, Status, StatusCode

LEAF_CUSTOMER_SPAN_ID_HEADER = "leaf_customer_span_id"
TOOLBOX_POST_SPAN_ATTRIBUTE = "castia.foundry.toolbox.post"
_HOSTED_ENV_MARKERS = (
    "FOUNDRY_AGENT_ENDPOINT",
    "WEBSITE_SITE_NAME",
    "CONTAINER_APP_NAME",
    "AZURE_CONTAINER_APP_NAME",
)


def leaf_customer_span_id() -> str | None:
    """Return the active span context in W3C traceparent wire format."""
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
    """Create the visible client span used to parent remote toolbox work."""
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


def configure_foundry_local_telemetry(*, agent_name: str) -> bool:
    """Configure a clean local Azure Monitor trace exporter for Castia agents.

    Enabled only when APPLICATIONINSIGHTS_CONNECTION_STRING is present and either
    WAYPOINT_TRACE_FILTER or CASTIA_TRACE_FILTER is set. Filter modes:
    - off: no local exporter
    - full: export all spans
    - agent: export only the agent/model/tool path
    """
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    mode = os.getenv("WAYPOINT_TRACE_FILTER") or os.getenv("CASTIA_TRACE_FILTER")
    if not connection_string or not mode or mode.lower() == "off":
        return False
    if any(os.getenv(marker) for marker in _HOSTED_ENV_MARKERS):
        return False

    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

    agent_version = os.getenv("FOUNDRY_AGENT_VERSION")

    class FoundryAgentIdentityProcessor(SpanProcessor):
        def on_start(self, span: Span, parent_context: object | None = None) -> None:
            span.set_attribute("gen_ai.agent.name", agent_name)
            if agent_version:
                span.set_attribute("gen_ai.agent.id", f"{agent_name}:{agent_version}")
                span.set_attribute("gen_ai.agent.version", agent_version)
            _set_if_present(span, "microsoft.foundry.project.id", "FOUNDRY_PROJECT_ID")
            _set_if_present(span, "microsoft.foundry.subscription.id", "FOUNDRY_SUBSCRIPTION_ID")
            _set_if_present(span, "microsoft.foundry.account.name", "FOUNDRY_ACCOUNT_NAME")
            _set_if_present(span, "microsoft.foundry.project.name", "FOUNDRY_PROJECT_NAME")
            span.set_attribute("waypoint.execution.mode", "local")

        def on_end(self, span: ReadableSpan) -> None:
            pass

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    class FilteringSpanExporter(SpanExporter):
        def __init__(self, inner: SpanExporter) -> None:
            self._inner = inner

        def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
            if mode.lower() == "full":
                kept = list(spans)
            else:
                kept = [span for span in spans if _is_agent_span(span)]
            if not kept:
                return SpanExportResult.SUCCESS
            return self._inner.export(kept)

        def shutdown(self) -> None:
            return self._inner.shutdown()

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return self._inner.force_flush(timeout_millis)

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", f"{agent_name}-local"),
                "deployment.environment.name": "local",
            }
        )
    )
    provider.add_span_processor(FoundryAgentIdentityProcessor())
    provider.add_span_processor(
        BatchSpanProcessor(
            FilteringSpanExporter(
                AzureMonitorTraceExporter.from_connection_string(connection_string)
            )
        )
    )
    trace.set_tracer_provider(provider)
    if trace.get_tracer_provider() is not provider:
        return False
    os.environ.setdefault(
        "OTEL_PYTHON_HTTPX_EXCLUDED_URLS",
        "169\\.254\\.169\\.254,settings\\.sdk\\.monitor\\.azure\\.com",
    )
    HTTPXClientInstrumentor().instrument()
    return True


def _set_if_present(span: Any, attribute: str, env_var: str) -> None:
    value = os.getenv(env_var)
    if value:
        span.set_attribute(attribute, value)


def _is_agent_span(span: Any) -> bool:
    name = span.name or ""
    attributes = span.attributes or {}
    if attributes.get(TOOLBOX_POST_SPAN_ATTRIBUTE):
        return True
    if name in {
        "POST /responses",
        "POST /activity/messages",
        "POST /invocations",
    }:
        return True
    if attributes.get("gen_ai.tool.type") == "foundry_iq" and name.startswith("execute_tool "):
        return True
    if name.startswith("invoke_agent ") or name.startswith("chat "):
        return True
    return name.startswith("POST /api/projects/") and "/toolboxes/" in name
