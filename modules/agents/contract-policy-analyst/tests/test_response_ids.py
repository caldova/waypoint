import asyncio
import json
import re

import httpx

import response_ids

PLATFORM_RESPONSE_ID = re.compile(r"resp_[0-9a-f]{16}00[0-9a-f]{32}")
PLATFORM_MESSAGE_ID = re.compile(r"msg_[0-9a-f]{16}00[0-9a-f]{32}")


def test_castia_responses_emit_platform_format_ids(monkeypatch):
    from castia import Agent
    from castia.hosting import server

    monkeypatch.setattr(server, "uuid4", server.uuid4)
    response_ids.install()
    app = Agent(name="response-id-fixture")

    @app.responses()
    async def reply(text: str) -> str:
        return f"echo {text}"

    async def invoke():
        asgi = server.build_app(app._routes, app._wire, app._invokes, app._commands, agent_name=app.name)
        transport = httpx.ASGITransport(app=asgi)
        async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
            return await client.post("/responses", json={"input": "hello", "store": False})

    response = asyncio.run(invoke())
    assert response.status_code == 200, response.text
    body = response.json()
    assert PLATFORM_RESPONSE_ID.fullmatch(body["id"]), body["id"]
    message_ids = [item["id"] for item in body["output"] if item.get("type") == "message"]
    assert message_ids and all(PLATFORM_MESSAGE_ID.fullmatch(i) for i in message_ids)
    assert "echo hello" in json.dumps(body)


def test_platform_uuid_keeps_uuid_string_and_unique_bodies():
    first, second = response_ids.platform_uuid4(), response_ids.platform_uuid4()
    assert response_ids.PLATFORM_ID_BODY.fullmatch(first.hex)
    assert first.hex != second.hex
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", str(first))


def test_shim_is_noop_when_castia_mints_platform_ids(monkeypatch):
    from castia.hosting import server

    original = server.uuid4
    monkeypatch.setattr(server, "_platform_id", lambda prefix, like=None: prefix, raising=False)
    assert response_ids.install() is False
    assert server.uuid4 is original
