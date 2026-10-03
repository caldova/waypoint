"""Resolve who is asking on an Agent 365 turn, using the hire's own Graph token."""

from __future__ import annotations

from typing import Any

from agent.integrations.activity_identity import activity_from, agentic_user_id

_GRAPH = "https://graph.microsoft.com/v1.0"
_EMAILS: dict[str, str] = {}


async def agentic_graph_token(activity: Any) -> str:
    """Delegated Graph token for the hire's agentic user; raises off an Agent 365 turn."""
    from castia.hosting.credentials import agentic_user_token

    user_id = agentic_user_id(activity)
    if not user_id:
        raise RuntimeError("This needs an Agent 365 (Teams) turn with the agent's identity.")
    return await agentic_user_token(user_id)


def requester_object_id(activity: Any) -> str | None:
    raw = activity_from(activity)
    sender = getattr(raw, "from_property", None) or getattr(raw, "from_", None)
    object_id = getattr(sender, "aad_object_id", None) if sender else None
    return str(object_id) if object_id else None


async def requester_email(activity: Any, token: str) -> str:
    """The requester's mail address (or UPN), looked up once per Entra object id."""
    import httpx
    from castia.hosting.credentials import bearer

    object_id = requester_object_id(activity)
    if not object_id:
        raise RuntimeError("The turn has no requester Entra object id.")
    if object_id in _EMAILS:
        return _EMAILS[object_id]
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_GRAPH}/users/{object_id}",
            params={"$select": "mail,userPrincipalName"},
            headers={"Authorization": bearer(token)},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph user lookup failed with HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    email = str(body.get("mail") or body.get("userPrincipalName") or "").lower()
    if not email:
        raise RuntimeError("The requester has no mail or userPrincipalName.")
    _EMAILS[object_id] = email
    return email
