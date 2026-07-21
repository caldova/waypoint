"""OpenTelemetry tracing utilities.

Provides decorators and context managers for adding distributed tracing
to service methods and code blocks.
"""

import contextlib
import inspect
import logging
from collections.abc import Callable, Generator
from functools import partial, wraps
from typing import Any

from opentelemetry import trace as otel_trace
from opentelemetry.trace import Span, Status, StatusCode

logger = logging.getLogger(__name__)

DEFAULT_TRACER_NAME = "waypoint.api"

# Patterns that indicate sensitive data that should be masked
SENSITIVE_PATTERNS = ["key", "secret", "password", "credential", "token", "connection"]


def sanitize(key: str, value: Any) -> Any:
    """Mask sensitive data in trace attributes.

    Args:
        key: The attribute key name
        value: The attribute value

    Returns:
        The original value or a masked placeholder for sensitive data
    """
    if isinstance(value, str) and any(s in key.lower() for s in SENSITIVE_PATTERNS):
        return "**********"
    return value


def _set_span_attributes(span: Span, attributes: dict[str, Any]) -> None:
    """Set attributes on a span, sanitizing sensitive values."""
    for key, value in attributes.items():
        try:
            sanitized = sanitize(key, value)
            if sanitized is not None:
                # Convert to string if not a basic type
                if not isinstance(sanitized, str | int | float | bool):
                    sanitized = str(sanitized)
                span.set_attribute(key, sanitized)
        except Exception:
            pass  # Skip attributes that can't be set


def _trace_sync(
    func: Callable[..., Any],
    tracer: otel_trace.Tracer,
    capture_args: bool = True,
    ignore_params: list[str] | None = None,
) -> Callable[..., Any]:
    """Wrap a synchronous function with tracing."""
    ignore_params = ignore_params or []

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        span_name = f"{func.__module__}.{func.__qualname__}"
        with tracer.start_as_current_span(span_name) as span:
            try:
                # Capture function arguments as attributes
                if capture_args:
                    sig = inspect.signature(func)
                    bound = sig.bind_partial(*args, **kwargs)
                    for param_name, param_value in bound.arguments.items():
                        if param_name not in ignore_params and param_name != "self":
                            _set_span_attributes(span, {f"arg.{param_name}": param_value})

                result = func(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    return wrapper


def _trace_async(
    func: Callable[..., Any],
    tracer: otel_trace.Tracer,
    capture_args: bool = True,
    ignore_params: list[str] | None = None,
) -> Callable[..., Any]:
    """Wrap an asynchronous function with tracing."""
    ignore_params = ignore_params or []

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        span_name = f"{func.__module__}.{func.__qualname__}"
        with tracer.start_as_current_span(span_name) as span:
            try:
                # Capture function arguments as attributes
                if capture_args:
                    sig = inspect.signature(func)
                    bound = sig.bind_partial(*args, **kwargs)
                    for param_name, param_value in bound.arguments.items():
                        if param_name not in ignore_params and param_name != "self":
                            _set_span_attributes(span, {f"arg.{param_name}": param_value})

                result = await func(*args, **kwargs)
                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    return wrapper


def trace(
    func: Callable[..., Any] | None = None,
    *,
    tracer_name: str = DEFAULT_TRACER_NAME,
    capture_args: bool = True,
    ignore_params: list[str] | None = None,
) -> Callable[..., Any]:
    """Decorator to trace function execution with OpenTelemetry spans.

    Usage:
        @trace
        async def my_function(arg1, arg2):
            ...

        @trace(ignore_params=["password"])
        def my_sync_function(username, password):
            ...

    Args:
        func: The function to wrap (when used without parentheses)
        tracer_name: Name for the tracer instance
        capture_args: Whether to capture function arguments as span attributes
        ignore_params: List of parameter names to exclude from tracing

    Returns:
        Decorated function with tracing enabled
    """
    if func is None:
        return partial(
            trace,
            tracer_name=tracer_name,
            capture_args=capture_args,
            ignore_params=ignore_params,
        )

    tracer = otel_trace.get_tracer(tracer_name)

    if inspect.iscoroutinefunction(func):
        return _trace_async(func, tracer, capture_args, ignore_params)
    else:
        return _trace_sync(func, tracer, capture_args, ignore_params)


@contextlib.contextmanager
def trace_span(
    name: str,
    tracer_name: str = DEFAULT_TRACER_NAME,
    attributes: dict[str, Any] | None = None,
) -> Generator[Span]:
    """Context manager for creating a traced span.

    Usage:
        with trace_span("process_data", attributes={"item_count": 10}) as span:
            # Do work
            span.set_attribute("result", "success")

    Args:
        name: Name for the span
        tracer_name: Name for the tracer instance
        attributes: Optional attributes to set on the span

    Yields:
        The created span for additional attribute setting
    """
    tracer = otel_trace.get_tracer(tracer_name)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            _set_span_attributes(span, attributes)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
