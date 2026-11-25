"""Model routing: MAI deployments need the account Responses route.

MAI models return an opaque 400 on the project route (``.../api/projects/<p>/openai/v1/responses``) but
work on the account route (``https://<account>.services.ai.azure.com/openai/v1/responses``); gpt-* models
work on both. ``CPA_MODEL_ROUTE=account`` (default) keeps castia's Model and tracing and swaps only the
OpenAI client. ``CPA_REASONING_EFFORT`` pins reasoning effort per version so arms are matched.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any

from castia import Model

_SCOPE = "https://cognitiveservices.azure.com/.default"


def account_openai_base(project_endpoint: str) -> str:
    match = re.match(r"^(https://[^/]+)/api/projects/[^/]+/?$", project_endpoint.strip())
    if not match:
        raise ValueError(f"not a Foundry project endpoint: {project_endpoint!r}")
    return f"{match.group(1)}/openai/v1/"


class _AccountClient:
    def __init__(self, base_url: str) -> None:
        from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider
        from openai import AsyncOpenAI

        provider = get_bearer_token_provider(DefaultAzureCredential(), _SCOPE)
        self._openai = AsyncOpenAI(base_url=base_url, api_key=provider)

    def get_openai_client(self) -> Any:
        return self._openai


def routed_model(config: Any) -> Callable[[], Model]:
    def provider() -> Model:
        effort = os.getenv("CPA_REASONING_EFFORT", "").strip().lower() or None
        if os.getenv("CPA_MODEL_ROUTE", "account").lower() != "account":
            raise ValueError("All analyst comparison arms must use the account Responses route.")
        model = Model(config.model, instructions=config.instructions, reasoning_effort=effort)
        model._client = _AccountClient(account_openai_base(os.environ["FOUNDRY_PROJECT_ENDPOINT"]))
        return model

    return provider
