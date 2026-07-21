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
from app.modules.assurance_runs import service as service_module
from app.modules.assurance_runs.routes import get_assurance_runs_service
from app.modules.assurance_runs.service import AssuranceRunsService


class FakeFoundryClient:
    def __init__(
        self,
        *,
        response_id: str = "caresp-test",
        error: FoundryInvocationError | None = None,
        errors_by_invoice: dict[str, FoundryInvocationError] | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.response_id = response_id
        self.error = error
        self.errors_by_invoice = errors_by_invoice or {}
        self.release = release
        self.calls: list[tuple[str, str]] = []

    async def start_background(self, *, agent_name: str, prompt: str) -> HostedResponseStart:
        self.calls.append((agent_name, prompt))
        if self.release is not None:
            await self.release.wait()
        for invoice_id, error in self.errors_by_invoice.items():
            if prompt.endswith(f"invoice {invoice_id}."):
                raise error
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


def _add_invoice(repository: InMemoryWaypointRepository, invoice_id: str) -> str:
    source = next(iter(repository.invoices.values()))
    repository.invoices[invoice_id] = source.model_copy(
        update={
            "id": invoice_id,
            "invoice_number": invoice_id.upper(),
        }
    )
    return invoice_id


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


@pytest.mark.asyncio
async def test_batch_trigger_requires_authentication(trigger_client):
    client, repository, _foundry, _service = trigger_client

    response = await client.post(
        "/api/invoices/assurance-runs/batch",
        json={"invoice_ids": [_invoice_id(repository)]},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invoice_ids",
    [
        [],
        [""],
        ["   "],
        [f"invoice-{index}" for index in range(26)],
    ],
)
async def test_batch_trigger_rejects_empty_and_over_limit_batches(
    trigger_client,
    invoice_ids,
):
    client, _repository, foundry, _service = trigger_client

    response = await client.post(
        "/api/invoices/assurance-runs/batch",
        headers=_headers(),
        json={"invoice_ids": invoice_ids},
    )

    assert response.status_code == 422
    assert foundry.calls == []


@pytest.mark.asyncio
async def test_batch_trigger_deduplicates_ids_preserving_first_seen_order(trigger_client):
    client, repository, foundry, _service = trigger_client
    first = _invoice_id(repository)
    second = _add_invoice(repository, "invoice-second")

    response = await client.post(
        "/api/invoices/assurance-runs/batch",
        headers=_headers(),
        json={"invoice_ids": [f" {second} ", first, second, first]},
    )

    assert response.status_code == 202
    body = response.json()
    assert [item["invoice_id"] for item in body["items"]] == [second, first]
    assert [item["outcome"] for item in body["items"]] == ["accepted", "accepted"]
    assert body["total"] == 2
    assert body["accepted"] == 2
    assert len(foundry.calls) == 2


@pytest.mark.asyncio
async def test_batch_trigger_limits_startup_concurrency_to_four(trigger_client, monkeypatch):
    client, _repository, _foundry, service = trigger_client
    active = 0
    maximum_active = 0

    async def slow_not_found(*, invoice_id: str, actor: str):
        nonlocal active, maximum_active
        assert actor
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        raise service_module.InvoiceNotFoundError(invoice_id)

    monkeypatch.setattr(service, "trigger", slow_not_found)
    invoice_ids = [f"invoice-{index}" for index in range(9)]

    response = await client.post(
        "/api/invoices/assurance-runs/batch",
        headers=_headers(),
        json={"invoice_ids": invoice_ids},
    )

    assert response.status_code == 202
    assert maximum_active == 4
    assert response.json()["not_found"] == len(invoice_ids)


@pytest.mark.asyncio
async def test_batch_trigger_returns_mixed_outcomes_without_rollback_or_detail_leak(
    trigger_client,
):
    client, repository, foundry, service = trigger_client
    reused_invoice = _invoice_id(repository)
    accepted_invoice = _add_invoice(repository, "invoice-accepted")
    failed_invoice = _add_invoice(repository, "invoice-failed")
    missing_invoice = "invoice-missing"

    initial = await client.post(
        f"/api/invoices/{reused_invoice}/assurance-runs",
        headers=_headers(),
    )
    assert initial.status_code == 202

    failure_detail = "internal upstream detail must not reach the caller"
    batch_foundry = FakeFoundryClient(
        errors_by_invoice={
            failed_invoice: FoundryInvocationError(failure_detail),
        }
    )
    service.foundry_client = batch_foundry

    response = await client.post(
        "/api/invoices/assurance-runs/batch",
        headers=_headers(),
        json={
            "invoice_ids": [
                reused_invoice,
                missing_invoice,
                failed_invoice,
                accepted_invoice,
            ]
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert [item["outcome"] for item in body["items"]] == [
        "reused",
        "not_found",
        "start_failed",
        "accepted",
    ]
    assert body == {
        "items": body["items"],
        "total": 4,
        "accepted": 1,
        "reused": 1,
        "not_found": 1,
        "start_failed": 1,
    }
    assert body["items"][0]["run_id"] == initial.json()["run"]["id"]
    assert body["items"][3]["run_id"]
    assert body["items"][3]["invoice_number"] == accepted_invoice.upper()
    assert failure_detail not in response.text
    assert len(foundry.calls) == 1
    assert len(batch_foundry.calls) == 2

    runs = await repository.list_agent_runs()
    statuses_by_invoice = {
        run.metadata["invoice_id"]: run.status for run in runs if "invoice_id" in run.metadata
    }
    assert statuses_by_invoice[reused_invoice] == "running"
    assert statuses_by_invoice[accepted_invoice] == "running"
    assert statuses_by_invoice[failed_invoice] == "failed"


@pytest.mark.asyncio
async def test_batch_trigger_does_not_cancel_remaining_items_after_unexpected_failure(
    trigger_client,
    monkeypatch,
):
    client, _repository, _foundry, service = trigger_client
    calls: list[str] = []
    invoice_ids = [f"invoice-{index}" for index in range(6)]

    async def mixed_failure(*, invoice_id: str, actor: str):
        assert actor
        calls.append(invoice_id)
        await asyncio.sleep(0)
        if invoice_id == invoice_ids[0]:
            raise RuntimeError("unexpected internal detail")
        raise service_module.InvoiceNotFoundError(invoice_id)

    monkeypatch.setattr(service, "trigger", mixed_failure)

    response = await client.post(
        "/api/invoices/assurance-runs/batch",
        headers=_headers(),
        json={"invoice_ids": invoice_ids},
    )

    assert response.status_code == 202
    assert calls == invoice_ids
    assert response.json()["start_failed"] == 1
    assert response.json()["not_found"] == len(invoice_ids) - 1
    assert "unexpected internal detail" not in response.text
