"""Server-side Foundry **toolbox** retrieval for the single agent.

A toolbox is a curated set of tools the platform exposes behind one
MCP-compatible endpoint, resolved **server-side** by the model service within a
turn — no local impl, no client-side MCP session (castia 0.4.0 `toolbox`). This
is how the demo's FoundryIQ contract/policy knowledge base reaches the agent:
the model calls the KB's ``knowledge_base_retrieve`` over the toolbox and folds
the grounded passages into its reasoning.

It is **read-only by construction**: the demo toolbox is a curated read
projection (the legacy fleet folded WaypointIQ down to GET-only reads for exactly
this reason). The one path that mutates Waypoint remains ``record_assurance`` in
``write_tools.py``, governed by the deterministic policy check — a retrieval
toolbox can never persist a case, run, or recommendation.

Everything here is env-gated: with no ``TOOLBOX_*`` configured,
:func:`assurance_specs` / :func:`read_specs` return ``[]`` and the agent falls
back to the direct-REST ``gather_evidence`` tool with no code change.
"""

from __future__ import annotations

import os

from castia import resolve_toolbox_endpoint, toolbox_mcp_tool, toolbox_token


def is_toolbox_configured() -> bool:
    """Whether a Foundry toolbox endpoint resolves from the environment."""
    return resolve_toolbox_endpoint() is not None


def _server_label() -> str:
    return os.environ.get("TOOLBOX_SERVER_LABEL") or os.environ.get("TOOLBOX_NAME") or "toolbox"


#: Fail-closed default allow-list: the FoundryIQ knowledge-base retrieval tool.
#: An absent ``TOOLBOX_ALLOWED_TOOLS`` restricts the model to *read* retrieval
#: rather than "expose every tool the endpoint publishes", so a toolbox that is
#: later (mis)provisioned with a mutation tool cannot become a second write path.
#: Set ``TOOLBOX_ALLOWED_TOOLS`` to a curated read list when the demo toolbox
#: exposes more than the KB, or to ``*`` to explicitly expose all of its tools.
_DEFAULT_ALLOWED_TOOLS = ("knowledge_base_retrieve",)


def _allowed_tools() -> tuple[str, ...] | None:
    """The read-only allow-list of toolbox tools the model may call.

    Fails closed to :data:`_DEFAULT_ALLOWED_TOOLS`. ``TOOLBOX_ALLOWED_TOOLS``
    (comma-separated) overrides it for a broader curated read toolbox; the single
    literal ``*`` is an explicit opt-out that exposes every tool the endpoint
    publishes. The provisioned toolbox must be a read projection regardless — the
    sole Waypoint writer is ``record_assurance``.
    """
    raw = os.environ.get("TOOLBOX_ALLOWED_TOOLS", "").strip()
    if not raw:
        return _DEFAULT_ALLOWED_TOOLS
    if raw == "*":
        return None
    return tuple(t.strip() for t in raw.split(",") if t.strip())


async def _toolbox_specs() -> list[dict]:
    """The server-side toolbox ``mcp`` spec(s), or ``[]`` when unconfigured.

    Auth prefers a stored ``TOOLBOX_PROJECT_CONNECTION_ID`` (no token mint); else
    it mints an ``https://ai.azure.com`` bearer from the container's managed
    identity — validated to work without a stored connection (see
    ``castia.toolbox``). The token is minted only once an endpoint resolves, so
    an unconfigured agent never touches the network here.
    """
    endpoint = resolve_toolbox_endpoint()
    if not endpoint:
        return []
    connection_id = os.environ.get("TOOLBOX_PROJECT_CONNECTION_ID") or None
    token = None if connection_id else await toolbox_token()
    spec = toolbox_mcp_tool(
        endpoint,
        server_label=_server_label(),
        allowed_tools=_allowed_tools(),
        project_connection_id=connection_id,
        token=token,
    )
    return [spec] if spec else []


async def read_specs() -> list[dict]:
    """Read-only server-side toolbox specs for the Q&A / evidence surfaces."""
    return await _toolbox_specs()


async def assurance_specs() -> list[dict]:
    """Read-only server-side toolbox specs offered on the assurance path.

    Same retrieval toolbox as :func:`read_specs`: the assurance run grounds via
    the toolbox for narration, while the persisted decision is still owned by the
    deterministic REST policy check in ``write_tools.py``.
    """
    return await _toolbox_specs()
