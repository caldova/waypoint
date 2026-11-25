import pytest

import agent_config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OPTIMIZATION_CONFIG", "OPTIMIZATION_CANDIDATE_ID", "OPTIMIZATION_RESOLVE_ENDPOINT",
                 "OPTIMIZATION_LOCAL_DIR", "AZURE_AI_MODEL_DEPLOYMENT_NAME"):
        monkeypatch.delenv(name, raising=False)


def test_baseline_loads_declared_model(monkeypatch):
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-6-astra")
    config = agent_config.load()
    assert config.model == "gpt-6-astra"
    assert config.source.startswith("local:")
    assert "JSON" in config.instructions


def test_model_mismatch_fails_at_startup(monkeypatch):
    monkeypatch.setenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "mai-code-2-flash-base")
    with pytest.raises(agent_config.ConfigError, match="metadata.yaml runs"):
        agent_config.load()


def test_missing_candidate_does_not_fall_back_to_baseline(monkeypatch):
    monkeypatch.setenv("OPTIMIZATION_CANDIDATE_ID", "does-not-exist")
    with pytest.raises(agent_config.ConfigError, match="no agent config"):
        agent_config.load()
