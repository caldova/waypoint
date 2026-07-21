"""Tests for tenant-authenticated invoice assurance triggers."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.common.foundry_responses import (
    FoundryInvocationError,
    FoundryResponsesClient,
    HostedResponseStart,
)
from app.common.repository import InMemoryWaypointRepository
from app.common.settings import Settings, get_settings
from app.main import app
from app.modules.assurance_runs.routes import get_assurance_runs_service
from app.modules.assurance_runs.service import AssuranceRunsService


class FakeFoundryClient:
    def __init__(
        self,
        *,
        response_id: str = "caresp-test",
        error: FoundryInvocationError | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.response_id = response_id
        self.error = error
        self.release = release
        self.calls: list[tuple[str, str]] = []

    async def start_background(self, *, agent_name: str, prompt: str) -> HostedResponseStart:
        self.calls.append((agent_name, prompt))
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return HostedResponseStart(response_id=self.response_id, status="in_progress")


@pytest.mark.asyncio
async def test_foundry_client_sends_managed_identity_bearer_token(monkeypatch):
    class Token:
        token = "managed-identity-token"

    class Credential:
        def get_token(self, _scope):
            return Token()

        def close(self):
            pass

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return json.dumps({"id": "caresp-live", "status": "in_progress"}).encode()

    captured_headers: dict[str, str] = {}

    def fake_urlopen(request, *, timeout):
        assert timeout == 10
        captured_headers.update(dict(request.header_items()))
        return Response()

    monkeypatch.setattr(
        "app.common.foundry_responses.DefaultAzureCredential",
        lambda: Credential(),
    )
    monkeypatch.setattr("app.common.foundry_responses.urllib.request.urlopen", fake_urlopen)
    client = FoundryResponsesClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/test",
        api_version="2025-11-15-preview",
        timeout_seconds=10,
    )

    result = await client.start_background(agent_name="assurance-orchestrator", prompt="Run it.")

    assert result.response_id == "caresp-live"
    assert captured_headers["Authorization"] == "Bearer managed-identity-token"


@pytest.fixture
async def trigger_client():
    settings = Settings(
        api_key_auth_enabled=True,
        api_keys="reader:test-reader-key:reader",
        foundry_endpoint="https://example.services.ai.azure.com/api/projects/test",
        default_seed_enabled=True,
    )
    repository = InMemoryWaypointRepository()
    await repository.initialize(load_default_seed=True)
    foundry = FakeFoundryClient()
    service = AssuranceRunsService(repository, settings, foundry)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_assurance_runs_service] = lambda: service

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("10.0.0.2", 12345)),
        base_url="http://test",
    ) as client:
        yield client, repository, foundry, service

    app.dependency_overrides.clear()


def _headers() -> dict[str, str]:
    return {"X-API-Key": "test-reader-key"}


def _invoice_id(repository: InMemoryWaypointRepository) -> str:
    return next(iter(repository.invoices))


@pytest.mark.asyncio
async def test_trigger_requires_authentication(trigger_client):
    client, repository, _foundry, _service = trigger_client

    response = await client.post(f"/api/invoices/{_invoice_id(repository)}/assurance-runs")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_trigger_rejects_unknown_invoice_without_calling_foundry(trigger_client):
    client, _repository, foundry, _service = trigger_client

    response = await client.post(
        "/api/invoices/invoice-does-not-exist/assurance-runs",
        headers=_headers(),
    )

    assert response.status_code == 404
    assert foundry.calls == []


@pytest.mark.asyncio
async def test_reader_can_start_background_assurance(trigger_client):
    client, repository, foundry, _service = trigger_client
    invoice_id = _invoice_id(repository)

    response = await client.post(
        f"/api/invoices/{invoice_id}/assurance-runs",
        headers=_headers(),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["reused"] is False
    assert body["foundry_response_id"] == "caresp-test"
    assert body["run"]["status"] == "running"
    assert body["run"]["name"] == f"assurance:{invoice_id}"
    assert body["run"]["foundry_agent_name"] == "assurance-orchestrator"
    assert foundry.calls == [
        (
            "assurance-orchestrator",
            f"Run the full invoice-assurance review for invoice {invoice_id}.",
        )
    ]


@pytest.mark.asyncio
async def test_second_trigger_reuses_active_run_without_second_foundry_call(trigger_client):
    client, repository, foundry, _service = trigger_client
    invoice_id = _invoice_id(repository)

    first = await client.post(
        f"/api/invoices/{invoice_id}/assurance-runs",
        headers=_headers(),
    )
    second = await client.post(
        f"/api/invoices/{invoice_id}/assurance-runs",
        headers=_headers(),
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["reused"] is True
    assert second.json()["run"]["id"] == first.json()["run"]["id"]
    assert len(foundry.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_trigger_reuses_pending_reservation(trigger_client):
    client, repository, _foundry, service = trigger_client
    invoice_id = _invoice_id(repository)
    release = asyncio.Event()
    foundry = FakeFoundryClient(release=release)
    service.foundry_client = foundry

    first_task = asyncio.create_task(
        client.post(
            f"/api/invoices/{invoice_id}/assurance-runs",
            headers=_headers(),
        )
    )
    while not foundry.calls:
        await asyncio.sleep(0)

    second = await client.post(
        f"/api/invoices/{invoice_id}/assurance-runs",
        headers=_headers(),
    )
    release.set()
    first = await first_task

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["reused"] is True
    assert second.json()["run"]["status"] == "pending"
    assert second.json()["run"]["id"] == first.json()["run"]["id"]
    assert len(foundry.calls) == 1


@pytest.mark.asyncio
async def test_foundry_start_failure_marks_reserved_run_failed(trigger_client):
    client, repository, _foundry, service = trigger_client
    invoice_id = _invoice_id(repository)
    foundry = FakeFoundryClient(
        error=FoundryInvocationError("Foundry hosted response startup was unavailable.")
    )
    service.foundry_client = foundry

    response = await client.post(
        f"/api/invoices/{invoice_id}/assurance-runs",
        headers=_headers(),
    )

    assert response.status_code == 503
    runs = await repository.list_agent_runs()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].metadata["trigger_error"] == ("Foundry hosted response startup was unavailable.")


@pytest.mark.asyncio
async def test_slow_foundry_start_does_not_block_health(trigger_client):
    client, repository, _foundry, service = trigger_client
    release = asyncio.Event()
    foundry = FakeFoundryClient(release=release)
    service.foundry_client = foundry
    invoice_id = _invoice_id(repository)

    trigger_task = asyncio.create_task(
        client.post(
            f"/api/invoices/{invoice_id}/assurance-runs",
            headers=_headers(),
        )
    )
    while not foundry.calls:
        await asyncio.sleep(0)

    health = await asyncio.wait_for(client.get("/health"), timeout=0.5)
    release.set()
    trigger = await trigger_task

    assert health.status_code == 200
    assert trigger.status_code == 202
