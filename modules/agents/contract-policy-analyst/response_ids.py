"""Platform-format Responses identifiers for castia-hosted responses.

castia mints ``resp_{uuid4().hex}`` (32-char body). Foundry's Responses
endpoint rejects that as ``400 Malformed identifier``; its IdGenerator format is
``{prefix}_{16 hex partition key}00{32 hex entropy}``. The Agent Optimizer
fetches each agent response by id, so castia-format ids make every optimizer
evaluation item fail with TARGET_INVOCATION_FAILED and score an empty output.

``install()`` swaps castia's module-level ``uuid4`` for a factory whose ``.hex``
is a platform-format body. ``str()`` still yields a normal UUID, so activity
ids are unchanged.

TEMPORARY SHIM for sethjuarez/castia#143 (fix: sethjuarez/castia#144). It is a
no-op once castia ships ``_platform_id``; remove it after Waypoint pins that
release.
"""

from __future__ import annotations

import re
import secrets
import uuid

PLATFORM_ID_BODY = re.compile(r"[0-9a-f]{16}00[0-9a-f]{32}")


class _PlatformUuid:
    __slots__ = ("_uuid", "hex")

    def __init__(self) -> None:
        self._uuid = uuid.uuid4()
        self.hex = f"{secrets.token_hex(8)}00{self._uuid.hex}"

    def __str__(self) -> str:
        return str(self._uuid)


def platform_uuid4() -> _PlatformUuid:
    return _PlatformUuid()


def install() -> bool:
    from castia.hosting import server

    if hasattr(server, "_platform_id"):
        return False
    server.uuid4 = platform_uuid4
    return True
