"""Server-side Foundry **toolbox** dispatcher for the single agent.

Every investigative / retrieval capability reaches the agent as a **server-side**
MCP toolbox tool — resolved by the model service within a turn, with no
client-side session and no re-owned call path. FoundryIQ's contract/policy
knowledge base is the first such lane (its ``knowledge_base_retrieve`` is the
demo's live grounding call); WorkIQ, WebIQ, FabricIQ, and anything provisioned
later join the exact same way.

Design goal — **add a toolbox and it just works.** Lanes are *discovered from the
environment*, not hand-registered here: the azd toolbox extension writes
``TOOLBOX_<NAME>_MCP_ENDPOINT`` for every provisioned toolbox, and this
dispatcher turns each one into a spec automatically. Provision a toolbox → set
(or forward) its endpoint var → the agent offers it, with **zero code change**.

Identity is by convention, and safe by default:

* **managed identity (headless-safe).** A lane with no project connection mints a
  bearer from the container's managed identity and is offered on *every* surface.
  This is the default — the common case is a single env var (the endpoint).
* **user identity / OBO (Activity only).** A lane that carries
  ``TOOLBOX_<NAME>_PROJECT_CONNECTION_ID`` (e.g. a WorkIQ UserEntraToken
  connection) authenticates through that connection and is **withheld from the
  headless** assurance / invocations surfaces, where there is no signed-in user
  to act on behalf of. Set ``TOOLBOX_<NAME>_HEADLESS=1`` to opt an app-only
  connection back onto the headless surfaces.

Read-only by construction: the toolbox is a retrieval projection. The one path
that mutates Waypoint stays ``record_assurance`` in ``write_tools.py``, governed
by the deterministic policy check — a retrieval toolbox can never persist a case,
run, or recommendation.

Fail-closed: with nothing configured, both :func:`read_specs` and
:func:`assurance_specs` return ``[]`` and the agent falls back to the
deterministic local tools with no code change. A managed-identity token is minted
only for a lane that actually resolves, so an unconfigured agent never touches the
network here.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from castia import (
    resolve_toolbox_endpoint,
    toolbox_mcp_tool,
    toolbox_token,
)

#: The azd toolbox extension's per-toolbox endpoint var, capturing the normalized
#: slug: ``TOOLBOX_MARKET_EVIDENCE_MCP_ENDPOINT`` -> ``MARKET_EVIDENCE``. The bare
#: passthrough ``TOOLBOX_MCP_ENDPOINT`` (no slug) does not match and is handled as
#: the default lane below via castia's resolver.
_ENDPOINT_RE = re.compile(r"^TOOLBOX_(?P<slug>.+)_MCP_ENDPOINT$")

#: FoundryIQ read default: with only the legacy generic toolbox configured, the
#: model is restricted to *read* retrieval rather than every tool the endpoint
#: publishes, so a toolbox later (mis)provisioned with a mutation tool cannot
#: become a second write path. Per-lane ``TOOLBOX_<NAME>_ALLOWED_TOOLS`` overrides.
_DEFAULT_ALLOWED_TOOLS = ("knowledge_base_retrieve",)

_FALSEY = {"0", "false", "no", "off"}


def _env(name: str, env: Mapping[str, str]) -> str | None:
    value = env.get(name)
    value = value.strip() if value else ""
    return value or None


def _truthy(value: str | None) -> bool:
    return bool(value) and value.lower() not in _FALSEY


def _parse_allowed(raw: str | None, *, default: tuple[str, ...] | None) -> tuple[str, ...] | None:
    """Parse an ``ALLOWED_TOOLS`` value: unset -> ``default``; ``*`` -> all; else a list."""
    if raw is None:
        return default
    if raw == "*":
        return None
    return tuple(t.strip() for t in raw.split(",") if t.strip())


@dataclass(frozen=True)
class _Lane:
    """One discovered server-side toolbox lane."""

    endpoint: str
    server_label: str
    allowed_tools: tuple[str, ...] | None
    connection_id: str | None
    #: Whether the lane is offered on the headless assurance / invocations surface.
    #: True for managed-identity lanes; False for OBO lanes unless opted back in.
    headless: bool

    async def spec(self) -> dict | None:
        # Managed-identity lanes mint a bearer from the container identity;
        # connection-based (OBO) lanes let the toolbox resolve auth from the
        # stored connection — never mint the container identity for those, or the
        # call would run as the wrong principal.
        token = None if self.connection_id else await toolbox_token()
        return toolbox_mcp_tool(
            self.endpoint,
            server_label=self.server_label,
            allowed_tools=self.allowed_tools,
            project_connection_id=self.connection_id,
            token=token,
        )


def _lane_from_slug(slug: str, endpoint: str, env: Mapping[str, str]) -> _Lane:
    """Build a discovered named lane from ``TOOLBOX_<slug>_*`` convention vars."""
    connection_id = _env(f"TOOLBOX_{slug}_PROJECT_CONNECTION_ID", env)
    # Safe default: a connection-based lane may carry user identity, so it is
    # Activity-only unless explicitly marked headless. A managed-identity lane
    # (no connection) is headless-safe.
    headless = True if connection_id is None else _truthy(_env(f"TOOLBOX_{slug}_HEADLESS", env))
    return _Lane(
        endpoint=endpoint,
        server_label=_env(f"TOOLBOX_{slug}_SERVER_LABEL", env) or slug.lower(),
        allowed_tools=_parse_allowed(_env(f"TOOLBOX_{slug}_ALLOWED_TOOLS", env), default=None),
        connection_id=connection_id,
        headless=headless,
    )


def _default_lane(env: Mapping[str, str]) -> _Lane | None:
    """The legacy / FoundryIQ single toolbox, resolved via castia's 3-tier resolver.

    Preserves today's live contract (bare ``TOOLBOX_MCP_ENDPOINT``, or composed
    from ``TOOLBOX_NAME`` + ``FOUNDRY_PROJECT_ENDPOINT``) with the FoundryIQ read
    allow-list default, so the ``knowledge_base_retrieve`` demo keeps working.
    """
    endpoint = resolve_toolbox_endpoint(env)
    if not endpoint:
        return None
    connection_id = _env("TOOLBOX_PROJECT_CONNECTION_ID", env)
    headless = True if connection_id is None else _truthy(_env("TOOLBOX_HEADLESS", env))
    return _Lane(
        endpoint=endpoint,
        server_label=_env("TOOLBOX_SERVER_LABEL", env) or _env("TOOLBOX_NAME", env) or "toolbox",
        allowed_tools=_parse_allowed(_env("TOOLBOX_ALLOWED_TOOLS", env), default=_DEFAULT_ALLOWED_TOOLS),
        connection_id=connection_id,
        headless=headless,
    )


def _discover_lanes(env: Mapping[str, str] | None = None) -> list[_Lane]:
    """Discover every configured toolbox lane from the environment.

    Named lanes come from each ``TOOLBOX_<NAME>_MCP_ENDPOINT`` the azd toolbox
    extension writes; the legacy / FoundryIQ single toolbox is added from castia's
    resolver unless it resolves to an endpoint a named lane already covers
    (dedup by URL, so ``TOOLBOX_NAME`` + its platform endpoint aren't counted twice).
    """
    env = os.environ if env is None else env
    lanes: dict[str, _Lane] = {}
    for key, value in env.items():
        match = _ENDPOINT_RE.match(key)
        if not match:
            continue
        endpoint = (value or "").strip()
        if not endpoint:
            continue
        lanes.setdefault(endpoint, _lane_from_slug(match.group("slug"), endpoint, env))
    default = _default_lane(env)
    if default and default.endpoint not in lanes:
        lanes[default.endpoint] = default
    return list(lanes.values())


def is_toolbox_configured() -> bool:
    """Whether at least one Foundry toolbox lane resolves from the environment."""
    return bool(_discover_lanes())


async def _specs(*, headless_only: bool) -> list[dict]:
    specs: list[dict] = []
    for lane in _discover_lanes():
        if headless_only and not lane.headless:
            continue
        spec = await lane.spec()
        if spec:
            specs.append(spec)
    return specs


async def read_specs() -> list[dict]:
    """Server-side toolbox specs for the Q&A / evidence (Activity) surface.

    Every configured lane, including OBO lanes that run as the signed-in user.
    """
    return await _specs(headless_only=False)


async def assurance_specs() -> list[dict]:
    """Server-side toolbox specs for the headless assurance / invocations surface.

    Only headless-safe (managed-identity) lanes; OBO lanes are withheld because
    there is no signed-in user to act on behalf of. The assurance run grounds via
    these lanes for narration, while the persisted decision stays owned by the
    deterministic REST policy check in ``write_tools.py``.
    """
    return await _specs(headless_only=True)
