import asyncio
import copy
import importlib
import json
from pathlib import Path

import configuration
import httpx
import pytest

import toolbox


@pytest.fixture
def clean_optimizer_env(monkeypatch):
    for name in (
        "OPTIMIZATION_CONFIG", "OPTIMIZATION_CANDIDATE_ID",
        "OPTIMIZATION_RESOLVE_ENDPOINT", "OPTIMIZATION_LOCAL_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CASTIA_TOOL_CAPTURE", "")


def injected_candidate():
    return {
        "model": "gpt-6-astra",
        "instructions": "Use only retrieved contract evidence. Return strict expert_evidence JSON.",
        "tools": baseline(),
    }


def test_native_startup_candidate_reaches_model_and_effective_provenance(monkeypatch, clean_optimizer_env):
    from types import SimpleNamespace

    import model_route
    import response_store
    from castia.observe.tool_capture import tool_capture_scope, verify_tool_capture

    original = configuration.load_release()
    candidate = injected_candidate()
    candidate["tools"][0]["function"]["description"] = "Retrieve the exact billed item's source evidence."
    candidate["tools"][0]["function"]["parameters"]["properties"]["query"]["description"] = "Supplier, item, and applicable term."
    monkeypatch.setenv("OPTIMIZATION_CONFIG", json.dumps(candidate))
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://offline.invalid/api/projects/offline")
    monkeypatch.setenv("CPA_MODEL_ROUTE", "account")
    monkeypatch.setenv("CPA_REASONING_EFFORT", "low")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(response_store.BlobResponseStore, "from_env", lambda: None)
    monkeypatch.setattr(toolbox, "resolve_toolbox_endpoint", lambda: "https://offline.invalid/mcp")
    calls = []

    class AccountClient:
        def __init__(self, base_url):
            assert base_url == "https://offline.invalid/openai/v1/"

        def get_openai_client(self):
            return SimpleNamespace(responses=SimpleNamespace(create=self.create))

        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output=[], output_text="offline response", usage=None)

    monkeypatch.setattr(model_route, "_AccountClient", AccountClient)
    import main
    importlib.reload(main)
    captures = []
    model = main.chat_model()

    async def invoke():
        async with tool_capture_scope(input_text="offline training fixture", sink=captures.append):
            return await main.reply("offline training fixture", model)

    assert asyncio.run(invoke()) == "offline response"
    assert calls[0]["instructions"] == candidate["instructions"]
    assert calls[0]["tools"][0]["name"] == candidate["tools"][0]["function"]["name"]
    assert calls[0]["tools"][0]["description"] == candidate["tools"][0]["function"]["description"]
    assert calls[0]["tools"][0]["parameters"] == candidate["tools"][0]["function"]["parameters"]
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert len(captures) == 1 and verify_tool_capture(captures[0])["record"] == "verified"
    provenance = captures[0]["provenance"]
    assert provenance["config_source"] == "env:OPTIMIZATION_CONFIG"
    assert provenance["instructions_sha256"] == configuration.config_evidence(main._config)["instructions_sha256"]
    assert provenance["instructions_sha256"] != configuration.config_evidence(original)["instructions_sha256"]
    assert provenance["tools_sha256"] != configuration.config_evidence(original)["tools_sha256"]
    monkeypatch.delenv("OPTIMIZATION_CONFIG")
    assert configuration.load_release() == original


@pytest.mark.parametrize("change", [
    "empty_instructions", "unknown_field", "wrong_model", "wrong_name",
    "schema", "skills", "temperature", "malformed", "duplicate",
])
def test_native_startup_candidate_fails_closed(monkeypatch, clean_optimizer_env, change):
    candidate = injected_candidate()
    if change == "empty_instructions":
        candidate["instructions"] = ""
    elif change == "unknown_field":
        candidate["enable_capture"] = True
    elif change == "wrong_model":
        candidate["model"] = "gpt-6.2-astra"
    elif change == "wrong_name":
        candidate["tools"][0]["function"]["name"] = "invented"
    elif change == "schema":
        candidate["tools"][0]["function"]["parameters"]["required"] = []
    elif change == "skills":
        candidate["skills"] = [{"name": "new", "description": "new", "body": "new"}]
    elif change == "temperature":
        candidate["temperature"] = 0.7
    raw = json.dumps(candidate)
    if change == "malformed":
        raw = "{"
    elif change == "duplicate":
        raw = '{"model":"gpt-6-astra","model":"gpt-6-astra"}'
    monkeypatch.setenv("OPTIMIZATION_CONFIG", raw)
    with pytest.raises(ValueError):
        configuration.load_release()


def test_unresolvable_mini_id_refuses_baseline_fallback(monkeypatch, clean_optimizer_env):
    monkeypatch.setenv("OPTIMIZATION_CANDIDATE_ID", "mini-unresolvable")
    with pytest.raises(ValueError, match="refusing baseline fallback"):
        configuration.load_release()


def test_native_resolver_rejects_legacy_or_foreign_uri(monkeypatch, clean_optimizer_env):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://offline.invalid/api/projects/offline")
    monkeypatch.setenv("OPTIMIZATION_CANDIDATE_ID", "mini-unresolvable")
    monkeypatch.setenv("OPTIMIZATION_RESOLVE_ENDPOINT", "https://foreign.invalid/candidates")
    with pytest.raises(ValueError, match="valid GA job-scoped"):
        configuration.load_release()


def test_native_resolver_uses_ga_job_route_without_local_fallback(monkeypatch, clean_optimizer_env):
    from castia.optimizing.jobs import OptimizerClient

    candidate = injected_candidate()
    project = "https://offline.invalid/api/projects/offline"
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", project)
    monkeypatch.setenv("OPTIMIZATION_CANDIDATE_ID", "candidate-1")
    monkeypatch.setenv("OPTIMIZATION_RESOLVE_ENDPOINT", project + "/agent_optimization_jobs/job-1")
    calls = []
    monkeypatch.setattr(OptimizerClient, "__init__", lambda self, endpoint: calls.append(endpoint))
    monkeypatch.setattr(OptimizerClient, "candidate_config", lambda self, job, candidate_id: (
        calls.append((job, candidate_id)) or candidate
    ))
    config = configuration.load_release()
    assert calls == [project, ("job-1", "candidate-1")]
    assert config.instructions == candidate["instructions"]
    assert config.source == "api:candidate:candidate-1"
    monkeypatch.setattr(OptimizerClient, "candidate_config", lambda *args: {})
    with pytest.raises(ValueError, match="instructions"):
        configuration.load_release()


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
