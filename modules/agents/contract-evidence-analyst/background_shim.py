"""Serve Responses `background=true` synchronously.

Foundry's native eval target (`azure_ai_target_completions` -> `azure_ai_agent`) calls hosted agents with
`background: true`, which castia rejects (`unsupported_parameter`). This middleware drops the flag and forces
`store: true`, so the caller receives an already-terminal response it can also GET by id. Turns are short,
so running them inline is fine.
"""

from __future__ import annotations

import json
from typing import Any

Scope = dict[str, Any]


def rewrite(body: bytes) -> bytes:
    try:
        payload = json.loads(body)
    except ValueError:
        return body
    if not isinstance(payload, dict) or payload.get("background") is not True:
        return body
    payload.pop("background")
    payload["store"] = True
    return json.dumps(payload).encode()


class BackgroundAsSync:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") != "POST" or not scope.get("path", "").endswith("/responses"):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self.app(scope, receive, send)  # disconnect before body completed
                return
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        body = rewrite(b"".join(chunks))
        headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app({**scope, "headers": headers}, replay, send)


def install() -> None:
    """Wrap castia's app factory so `app.run()` serves through the shim."""
    from castia.hosting import server

    if getattr(server.build_app, "_cea_background_shim", False):
        return
    original = server.build_app

    def build_app(*args: Any, **kwargs: Any) -> Any:
        app = original(*args, **kwargs)
        app.add_middleware(BackgroundAsSync)
        return app

    build_app._cea_background_shim = True  # type: ignore[attr-defined]
    server.build_app = build_app
