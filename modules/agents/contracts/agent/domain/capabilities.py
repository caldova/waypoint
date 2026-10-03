"""Capability-mode responses shared across protocols."""

from __future__ import annotations

from typing import Any

from agent.integrations.activity_identity import has_agentic_user_identity


def is_capabilities_prompt(text: str) -> bool:
    normalized = text.strip().lower()
    return (
        normalized in {"hi", "hello", "help", "start"}
        or "what can" in normalized
        or "capabilit" in normalized
        or "what do you do" in normalized
    )


def capabilities_response(*, activity: Any = None) -> str:
    identity_ready = has_agentic_user_identity(activity)
    graph_status = (
        "ready on this Teams turn"
        if identity_ready
        else "registered, but waiting for an Agent 365 Activity turn with agentic-user identity"
    )
    return (
        "I can help with contract and invoice intake workflows without pretending "
        "the unfinished Caldova APIs are live.\n\n"
        "**Good paths to try now**\n"
        "- Ask what the agent can do and what is still stubbed.\n"
        "- Ask for **latest invoices** to see the fixture summary pattern.\n"
        "- Use `/health`, `/state`, `/whoami`, or `/tools` for debugging.\n\n"
        "**Identity-aware tools**\n"
        f"- Mailbox/OneDrive Graph tools are **{graph_status}**.\n"
        "- Responses and invocations stay in safe scaffold mode."
    )
