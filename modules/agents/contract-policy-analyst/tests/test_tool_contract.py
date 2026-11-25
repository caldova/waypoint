import asyncio
import copy
import json
from pathlib import Path

import configuration
import httpx
import pytest

import toolbox


def baseline():
    return json.loads(
        (Path(__file__).parents[1] / ".agent_configs" / "baseline" / "tools.json").read_text()
    )


def test_optimizer_provider_matches_model_visible_runtime(monkeypatch):
    monkeypatch.setattr(toolbox, "resolve_toolbox_endpoint", lambda: "https://example.invalid/mcp")
    expected = baseline()[0]["function"]
    for tool in (
        toolbox.foundryiq_toolbox_tools()[0],
        toolbox.foundryiq_runtime_tools(baseline())[0],
    ):
        assert tool.name == expected["name"]
        assert tool.description == expected["description"]
        assert tool.parameters == expected["parameters"]


def test_descriptions_can_change_but_schema_cannot():
    tools = baseline()
    tools[0]["function"]["description"] = "Retrieve evidence before making material claims."
    tools[0]["function"]["parameters"]["properties"]["query"]["description"] = "Supplier and clause."
    toolbox.validate_tool_definitions(tools)
    tools[0]["function"]["parameters"]["required"] = []
    with pytest.raises(ValueError, match="schema"):
        toolbox.validate_tool_definitions(tools)


@pytest.mark.parametrize(
    "change", ["wrong_name", "extra_tool", "extra_property", "empty", "strict", "mcp_envelope"]
)
def test_rejects_non_dispatchable_candidate(change):
    tools = copy.deepcopy(baseline())
    if change == "wrong_name":
        tools[0]["function"]["name"] = "other"
    elif change == "extra_tool":
        tools.append(copy.deepcopy(tools[0]))
    elif change == "extra_property":
        tools[0]["function"]["parameters"]["properties"]["invoice"] = {"type": "string"}
    elif change == "strict":
        tools[0]["function"]["strict"] = True
    elif change == "mcp_envelope":
        tools[0]["type"] = "mcp"
    else:
        tools[0]["function"]["description"] = ""
    with pytest.raises(ValueError):
        toolbox.validate_tool_definitions(tools)


def test_release_rejects_environment_fallback(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("OPTIMIZATION_LOCAL_DIR", raising=False)
    monkeypatch.setattr(
        configuration, "load_agent_config",
        lambda _: SimpleNamespace(instructions=None, source="default"),
    )
    with pytest.raises(ValueError, match="instructions"):
        configuration.load_release()


def test_release_cannot_escape_agent(monkeypatch):
    monkeypatch.setenv("OPTIMIZATION_LOCAL_DIR", "..")
    with pytest.raises(ValueError, match="inside"):
        configuration.release_directory()


def test_release_rejects_wrong_model(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.delenv("OPTIMIZATION_LOCAL_DIR", raising=False)
    config = SimpleNamespace(
        instructions=(configuration.ROOT / ".agent_configs" / "baseline" / "instructions.md")
        .read_text(encoding="utf-8"),
        source="local",
        tool_definitions=baseline(),
        model="wrong-model",
    )
    monkeypatch.setattr(configuration, "load_agent_config", lambda _: config)
    with pytest.raises(ValueError, match="model"):
        configuration.load_release()


def test_dispatches_real_tool_name_and_query_variants(monkeypatch):
    requests = []

    async def token():
        return "test-token"

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, endpoint, **kwargs):
            requests.append((endpoint, kwargs))
            return httpx.Response(
                200, json={"result": {"content": [{"type": "text", "text": "clause"}]}}
            )

    monkeypatch.setattr(toolbox, "resolve_toolbox_endpoint", lambda: "https://example.invalid/mcp")
    monkeypatch.setattr(toolbox, "toolbox_token", token)
    monkeypatch.setattr(toolbox.httpx, "AsyncClient", Client)
    result = asyncio.run(toolbox._call_foundryiq_toolbox(None, query="  Supplier clause  "))
    assert result["ok"]
    assert requests[0][1]["json"]["params"] == {
        "name": "contracts-kb-mcp___knowledge_base_retrieve",
        "arguments": {"query_variants": ["Supplier clause"]},
    }


def test_canary_hash_ignores_generated_summary_and_request_ids():
    from scripts.retrieval_canary import reference_fingerprint

    reference = {"kind": "reference", "uri": "source.md", "sourceData": {"snippet": "clause"}}
    first = {"content": [
        {"type": "text", "text": "Summary one", "_meta": {"x-request-id": "one"}},
        {"type": "text", "text": json.dumps(reference)},
    ]}
    second = copy.deepcopy(first)
    second["content"][0] = {"type": "text", "text": "Different summary"}
    assert reference_fingerprint(first) == reference_fingerprint(second)
    second["content"][1]["text"] = json.dumps(
        {**reference, "sourceData": {"snippet": "different clause"}}
    )
    assert reference_fingerprint(first) != reference_fingerprint(second)


def test_canary_keeps_native_references_with_shared_request_metadata():
    from scripts.corpus_canaries import references

    fake = {"kind": "reference", "uri": "invented.md", "sourceData": {"snippet": "fake"}}
    actual = {"kind": "reference", "uri": "actual.md", "sourceData": {"snippet": "clause"}}
    result = {"content": [
        {"type": "text", "text": json.dumps(fake), "_meta": {"x-request-id": "shared"}},
        {"type": "text", "text": json.dumps(actual), "_meta": {"x-request-id": "shared"}},
    ]}
    assert references(result) == [actual]
