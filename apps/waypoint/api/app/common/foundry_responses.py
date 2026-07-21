"""Minimal Foundry hosted-agent Responses client."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential

AI_SCOPE = "https://ai.azure.com/.default"
FOUNDRY_FEATURES = "HostedAgents=V1Preview,AgentEndpoints=V1Preview"


@dataclass(frozen=True)
class HostedResponseStart:
    response_id: str
    status: str


class FoundryInvocationError(RuntimeError):
    """Raised when a hosted response cannot be started."""


class FoundryResponsesClient:
    def __init__(
        self,
        *,
        project_endpoint: str,
        api_version: str,
        timeout_seconds: float,
    ) -> None:
        self.project_endpoint = project_endpoint.rstrip("/")
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds

    async def start_background(self, *, agent_name: str, prompt: str) -> HostedResponseStart:
        return await asyncio.to_thread(
            self._start_background_sync,
            agent_name=agent_name,
            prompt=prompt,
        )

    def _start_background_sync(self, *, agent_name: str, prompt: str) -> HostedResponseStart:
        try:
            credential = DefaultAzureCredential()
            try:
                token = credential.get_token(AI_SCOPE).token
            finally:
                credential.close()

            endpoint = (
                f"{self.project_endpoint}/agents/{quote(agent_name, safe='')}"
                "/endpoint/protocols/openai/responses"
                f"?api-version={quote(self.api_version, safe='')}"
            )
            request = urllib.request.Request(
                endpoint,
                data=json.dumps({"input": prompt, "store": True, "background": True}).encode(
                    "utf-8"
                ),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Foundry-Features": FOUNDRY_FEATURES,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise FoundryInvocationError(
                f"Foundry rejected hosted response startup with HTTP {exc.code}."
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise FoundryInvocationError(
                "Foundry hosted response startup was unavailable."
            ) from exc
        except AzureError as exc:
            raise FoundryInvocationError(
                "The Waypoint identity could not acquire a Foundry access token."
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FoundryInvocationError(
                "Foundry returned an invalid hosted response payload."
            ) from exc

        if not isinstance(body, dict):
            raise FoundryInvocationError("Foundry returned an invalid hosted response payload.")
        response_id = body.get("id") or body.get("response_id")
        if not isinstance(response_id, str) or not response_id:
            raise FoundryInvocationError("Foundry returned no hosted response ID.")
        return HostedResponseStart(
            response_id=response_id,
            status=str(body.get("status") or "in_progress"),
        )
