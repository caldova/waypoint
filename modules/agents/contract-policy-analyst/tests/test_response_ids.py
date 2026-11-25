import asyncio
import json
import re

import httpx
import pytest

PLATFORM_RESPONSE_ID = re.compile(r"resp_[0-9a-f]{16}00[0-9a-f]{32}")
PLATFORM_MESSAGE_ID = re.compile(r"msg_[0-9a-f]{16}00[0-9a-f]{32}")


@pytest.mark.parametrize("identity_source", ("mint", "body", "header"))
def test_castia_responses_emit_platform_format_ids(identity_source):
    from castia import Agent
    from castia.hosting import server

    app = Agent(name="response-id-fixture")

    @app.responses()
    async def reply(text: str) -> str:
        return f"echo {text}"

    async def invoke():
        asgi = server.build_app(app._routes, app._wire, app._invokes, app._commands, agent_name=app.name)
        transport = httpx.ASGITransport(app=asgi)
        payload = {"input": "hello", "store": False}
        headers = {}
        if identity_source != "mint":
            payload["response_id"] = "resp_" + "a" * 16 + "00" + "b" * 32
        if identity_source == "header":
            headers["x-agent-response-id"] = "caresp_" + "c" * 16 + "00" + "d" * 32
        async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
            return await client.post("/responses", json=payload, headers=headers)

    response = asyncio.run(invoke())
    assert response.status_code == 200, response.text
    body = response.json()
    if identity_source == "header":
        assert body["id"] == "caresp_" + "c" * 16 + "00" + "d" * 32
    elif identity_source == "body":
        assert body["id"] == "resp_" + "a" * 16 + "00" + "b" * 32
    else:
        assert PLATFORM_RESPONSE_ID.fullmatch(body["id"]), body["id"]
    message_ids = [item["id"] for item in body["output"] if item.get("type") == "message"]
    assert message_ids and all(PLATFORM_MESSAGE_ID.fullmatch(i) for i in message_ids)
    assert "echo hello" in json.dumps(body)
