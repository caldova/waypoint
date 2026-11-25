import asyncio
import json
import re

import httpx

PLATFORM_RESPONSE_ID = re.compile(r"resp_[0-9a-f]{16}00[0-9a-f]{32}")
PLATFORM_MESSAGE_ID = re.compile(r"msg_[0-9a-f]{16}00[0-9a-f]{32}")


def test_castia_responses_emit_platform_format_ids():
    from castia import Agent
    from castia.hosting import server

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
