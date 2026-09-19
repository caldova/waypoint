"""Prompt-grounded Contract Expert demo agent."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from castia import Agent, Depends, Model, configured_model, load_agent_config
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

app = Agent(name="contract-expert")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("<") or "example.invalid" in value:
        raise RuntimeError(f"Set {name} before starting contract-expert.")
    return value


def model_provider() -> Model:
    _require_env("FOUNDRY_PROJECT_ENDPOINT")
    _require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    config = load_agent_config(Path(__file__).resolve().parent / ".agent_configs")
    if not (config.instructions or "").strip():
        raise RuntimeError("No baseline instructions loaded from .agent_configs.")
    return configured_model(config)()


_MODEL_DEPENDENCY = Depends(model_provider)


@app.responses()
async def reply(text: str, model: Model = _MODEL_DEPENDENCY) -> str:
    return await model.respond(text)


@app.responses_stream()
async def stream_reply(
    text: str, model: Model = _MODEL_DEPENDENCY
) -> AsyncIterator[str]:
    return model.stream(text)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088)
