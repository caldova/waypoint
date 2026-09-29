"""Small helpers for Activity identity access."""

from __future__ import annotations

from typing import Any


def activity_from(target: Any) -> Any:
    return getattr(target, "activity", target)


def call_or_none(target: Any, method: str) -> Any:
    if target is None:
        return None
    func = getattr(target, method, None)
    if not callable(func):
        return None
    return func()


def agentic_user_id(target: Any) -> str | None:
    if target is None:
        return None

    message_value = getattr(target, "agentic_user_id", None)
    if isinstance(message_value, str) and message_value:
        return message_value

    raw = activity_from(target)
    legacy_value = call_or_none(raw, "get_agentic_user")
    if legacy_value:
        return str(legacy_value)

    recipient = getattr(raw, "recipient", None)
    if getattr(recipient, "role", None) == "agenticUser":
        value = getattr(recipient, "agentic_user_id", None)
        return str(value) if value else None

    return None


def has_agentic_user_identity(target: Any) -> bool:
    return bool(agentic_user_id(target))
