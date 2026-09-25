"""Tests for the Waypoint Contracts API (email intake, artifacts, evidence, reports)."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import app.common.repository as repository_module
from app.common.database import close_waypoint_repository, reset_waypoint_repository_for_tests
from app.common.settings import Settings, get_settings
from app.main import app
from app.modules.contracts.schemas import (
    ArtifactExtractionCreate,
    IntakeAttachment,
    IntakeMessageUpsert,
)
from app.modules.contracts.service import ContractsService, intake_key

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

SHA_A = "a" * 64
SHA_B = "b" * 64
USER = "alex@caldova.example"
DEV_HEADERS = {"x-dev-user-email": USER}


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_settings] = lambda: Settings(local_auth_enabled=True)
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://test",
    ) as client:
        yield client
    app.dependency_overrides.clear()
    await close_waypoint_repository()
    reset_waypoint_repository_for_tests()


def _message(
    *,
    message_id: str = "msg-1",
    sender: str = "Alex@Caldova.example",
    received_at: str = "2026-09-01T10:00:00Z",
    attachments: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "mailbox_id": "contracts@caldova.example",
        "message_id": message_id,
        "sender": sender,
        "subject": "Signed MSA",
        "received_at": received_at,
        "attachments": attachments
        or [
            {
                "attachment_id": "att-1",
                "sha256": SHA_A,
                "file_name": "msa.pdf",
                "content_type": "application/pdf",
                "original_file_uri": "https://caldova.sharepoint.com/contracts/msa.pdf",
            }
        ],
        **extra,
    }


async def _register(client: AsyncClient, **kwargs: Any) -> dict[str, Any]:
    response = await client.post(
        "/api/contracts/intake/messages/upsert", json=_message(**kwargs), headers=DEV_HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- intake idempotency -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intake_registers_artifact_and_is_idempotent(client: AsyncClient):
    first = await _register(client)
    second = await _register(client)

    first_result = first["results"][0]
    second_result = second["results"][0]
    assert first_result["created"] is True
    assert second_result["created"] is False
    assert second_result["artifact"]["id"] == first_result["artifact"]["id"]

    artifact = first_result["artifact"]
    assert artifact["type"] == "contract"
    assert artifact["owner_user_id"] == USER  # normalized from the sender
    assert artifact["source"] == "email"
    assert artifact["source_attachment_sha256"] == SHA_A
    assert artifact["original_file_uri"] == "https://caldova.sharepoint.com/contracts/msa.pdf"
    assert artifact["extracted_json"] is None
    assert artifact["processing_status"] == "received"
    assert artifact["extraction_status"] == "pending"


@pytest.mark.asyncio
async def test_intake_identity_includes_attachment_hash(client: AsyncClient):
    """Same attachment id with different bytes (a re-sent revision) is a new artifact."""

    first = await _register(client)
    revised = await _register(
        client,
        attachments=[
            {
                "attachment_id": "att-1",
                "sha256": SHA_B,
                "original_file_uri": "https://caldova.sharepoint.com/contracts/msa-v2.pdf",
            }
        ],
    )

    assert revised["results"][0]["created"] is True
    assert revised["results"][0]["artifact"]["id"] != first["results"][0]["artifact"]["id"]


@pytest.mark.asyncio
async def test_intake_registers_each_attachment_and_dedupes_partial_replays(client: AsyncClient):
    two = [
        {"attachment_id": "att-1", "sha256": SHA_A, "original_file_uri": "https://f/1.pdf"},
        {
            "attachment_id": "att-2",
            "sha256": SHA_B,
            "original_file_uri": "https://f/2.pdf",
            "artifact_type": "invoice",
        },
    ]
    first = await _register(client, attachments=two[:1])
    both = await _register(client, attachments=two)

    assert [r["created"] for r in both["results"]] == [False, True]
    assert both["results"][0]["artifact"]["id"] == first["results"][0]["artifact"]["id"]
    assert both["results"][1]["artifact"]["type"] == "invoice"


@pytest.mark.asyncio
async def test_concurrent_intake_of_the_same_attachment_creates_one_artifact():
    service = ContractsService(repository_module.InMemoryWaypointRepository())
    message = IntakeMessageUpsert(**_message())

    results = await asyncio.gather(
        *(service.upsert_intake_message(message, actor="poller@test") for _ in range(8))
    )

    ids = {result.results[0].artifact.id for result in results}
    created = [result.results[0].created for result in results]
    assert len(ids) == 1
    assert created.count(True) == 1


def test_intake_key_is_unambiguous_across_separator_characters():
    assert intake_key("m|a", "b", "c", SHA_A) != intake_key("m", "a|b", "c", SHA_A)
    assert intake_key("m", "b", "c", SHA_A.upper()) == intake_key("m", "b", "c", SHA_A)


@pytest.mark.asyncio
async def test_intake_rejects_invalid_hash_and_empty_attachments(client: AsyncClient):
    bad_hash = _message(
        attachments=[{"attachment_id": "a", "sha256": "abc", "original_file_uri": "https://f"}]
    )
    no_attachments = {**_message(), "attachments": []}

    for body in (bad_hash, no_attachments):
        response = await client.post(
            "/api/contracts/intake/messages/upsert", json=body, headers=DEV_HEADERS
        )
        assert response.status_code == 422


# --- latest artifact resolution ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_resolves_by_owner_type_and_received_time(client: AsyncClient):
    older = await _register(client, message_id="m-old", received_at="2026-09-01T10:00:00Z")
    newer = await _register(
        client,
        message_id="m-new",
        received_at="2026-09-02T10:00:00Z",
        attachments=[{"attachment_id": "x", "sha256": SHA_B, "original_file_uri": "https://f/n"}],
    )
    # Registered last but received earliest: must not win.
    await _register(
        client,
        message_id="m-backfill",
        received_at="2026-08-01T10:00:00Z",
        attachments=[{"attachment_id": "y", "sha256": SHA_A, "original_file_uri": "https://f/b"}],
    )
    # Newer, but someone else's contract, and an invoice of ours: both excluded.
    await _register(
        client,
        message_id="m-other",
        sender="sam@caldova.example",
        received_at="2026-09-03T10:00:00Z",
    )
    await _register(
        client,
        message_id="m-invoice",
        received_at="2026-09-04T10:00:00Z",
        attachments=[
            {
                "attachment_id": "i",
                "sha256": SHA_A,
                "original_file_uri": "https://f/i",
                "artifact_type": "invoice",
            }
        ],
    )

    response = await client.get("/api/contracts/artifacts/latest", headers=DEV_HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == newer["results"][0]["artifact"]["id"]
    assert response.json()["id"] != older["results"][0]["artifact"]["id"]

    invoice = await client.get(
        "/api/contracts/artifacts/latest",
        params={"artifact_type": "invoice"},
        headers=DEV_HEADERS,
    )
    assert invoice.json()["source_message_id"] == "m-invoice"


@pytest.mark.asyncio
async def test_latest_supports_explicit_owner_and_is_case_insensitive(client: AsyncClient):
    await _register(client, sender="sam@caldova.example")

    response = await client.get(
        "/api/contracts/artifacts/latest",
        params={"owner_user_id": "SAM@caldova.example"},
        headers=DEV_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["owner_user_id"] == "sam@caldova.example"


@pytest.mark.asyncio
async def test_latest_breaks_received_time_ties_deterministically():
    repository = repository_module.InMemoryWaypointRepository()
    service = ContractsService(repository)
    same_time = "2026-09-01T10:00:00Z"
    for index, sha in enumerate((SHA_A, SHA_B)):
        await service.upsert_intake_message(
            IntakeMessageUpsert(
                **_message(
                    message_id=f"m-{index}",
                    received_at=same_time,
                    attachments=[
                        {"attachment_id": "a", "sha256": sha, "original_file_uri": "https://f"}
                    ],
                )
            ),
            actor="poller@test",
        )

    picks = {(await service.get_latest_artifact(USER, "contract")).id for _ in range(5)}  # type: ignore[union-attr]
    assert len(picks) == 1


@pytest.mark.asyncio
async def test_latest_returns_404_when_owner_has_no_artifacts(client: AsyncClient):
    response = await client.get("/api/contracts/artifacts/latest", headers=DEV_HEADERS)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_latest_requires_owner_for_app_only_callers(client: AsyncClient):
    app.dependency_overrides[get_settings] = lambda: Settings(
        api_key_auth_enabled=True, api_keys="contracts-agent:agent-secret:writer"
    )
    headers = {"x-api-key": "agent-secret"}
    await client.post("/api/contracts/intake/messages/upsert", json=_message(), headers=headers)

    without_owner = await client.get("/api/contracts/artifacts/latest", headers=headers)
    with_owner = await client.get(
        "/api/contracts/artifacts/latest", params={"owner_user_id": USER}, headers=headers
    )

    assert without_owner.status_code == 422
    assert with_owner.status_code == 200


# --- extraction / evidence / report writes ----------------------------------------------------


async def _artifact_id(client: AsyncClient) -> str:
    return (await _register(client))["results"][0]["artifact"]["id"]


@pytest.mark.asyncio
async def test_extractions_are_append_only_and_failures_keep_good_values(client: AsyncClient):
    artifact_id = await _artifact_id(client)
    base = f"/api/contracts/artifacts/{artifact_id}"

    good = await client.post(
        f"{base}/extractions",
        json={
            "extractor": "content_understanding",
            "schema_version": "contract-v1",
            "values": {"counterparty": "Northwind", "term_months": 24},
            "confidence": {"counterparty": 0.98},
            "source_spans": {"counterparty": [{"page": 1, "offset": 120, "length": 9}]},
        },
        headers=DEV_HEADERS,
    )
    failed = await client.post(
        f"{base}/extractions",
        json={"status": "failed", "error": "Content Understanding timed out"},
        headers=DEV_HEADERS,
    )
    detail = (await client.get(base, headers=DEV_HEADERS)).json()

    assert good.status_code == 201 and failed.status_code == 201
    assert [e["status"] for e in detail["extractions"]] == ["succeeded", "failed"]
    artifact = detail["artifact"]
    assert artifact["extracted_json"] == {"counterparty": "Northwind", "term_months": 24}
    assert artifact["extraction_status"] == "failed"
    assert artifact["latest_extraction_id"] == failed.json()["id"]
    assert artifact["original_file_uri"].endswith("msa.pdf")  # stored separately from values


@pytest.mark.asyncio
async def test_evidence_is_recorded_and_validated(client: AsyncClient):
    artifact_id = await _artifact_id(client)
    url = f"/api/contracts/artifacts/{artifact_id}/evidence"

    created = await client.post(
        url,
        json={
            "source_type": "foundryiq",
            "claim": "Payment terms are net 60.",
            "citation": "contracts-kb://msa-northwind#section-4.2",
            "confidence": 0.9,
        },
        headers=DEV_HEADERS,
    )
    bad_source = await client.post(
        url,
        json={"source_type": "rumor", "claim": "x", "citation": "y"},
        headers=DEV_HEADERS,
    )
    detail = (
        await client.get(f"/api/contracts/artifacts/{artifact_id}", headers=DEV_HEADERS)
    ).json()

    assert created.status_code == 201
    assert created.json()["created_by"] == USER
    assert bad_source.status_code == 422
    assert [e["claim"] for e in detail["evidence"]] == ["Payment terms are net 60."]


@pytest.mark.asyncio
async def test_report_requires_a_concrete_file_and_records_share_history(client: AsyncClient):
    artifact_id = await _artifact_id(client)
    base = f"/api/contracts/artifacts/{artifact_id}/reports"

    missing_file = await client.post(
        base, json={"report_type": "contract_brief"}, headers=DEV_HEADERS
    )
    created = await client.post(
        base,
        json={
            "report_type": "contract_brief",
            "title": "Northwind MSA brief",
            "file_url": "https://caldova.sharepoint.com/reports/northwind-brief.docx",
            "share_status": "pending_approval",
        },
        headers=DEV_HEADERS,
    )
    report_id = created.json()["id"]
    shared = await client.post(
        f"{base}/{report_id}/shares",
        json={
            "share_status": "shared",
            "shared_with": ["legal@caldova.example"],
            "share_url": "https://caldova.sharepoint.com/:w:/r/northwind-brief",
            "approved_by": USER,
        },
        headers=DEV_HEADERS,
    )

    assert missing_file.status_code == 422
    assert created.status_code == 201
    assert created.json()["share_status"] == "pending_approval"
    assert shared.status_code == 200
    report = shared.json()
    assert report["share_status"] == "shared"
    assert report["shared_with"] == ["legal@caldova.example"]
    assert [e["share_status"] for e in report["share_events"]] == ["pending_approval", "shared"]
    assert report["share_events"][-1]["approved_by"] == USER


@pytest.mark.asyncio
async def test_report_share_for_a_different_artifact_is_404(client: AsyncClient):
    artifact_id = await _artifact_id(client)
    other = await _register(
        client,
        message_id="m-2",
        attachments=[{"attachment_id": "z", "sha256": SHA_B, "original_file_uri": "https://f"}],
    )
    other_id = other["results"][0]["artifact"]["id"]
    report = await client.post(
        f"/api/contracts/artifacts/{artifact_id}/reports",
        json={"report_type": "brief", "file_url": "https://f/r.docx"},
        headers=DEV_HEADERS,
    )

    response = await client.post(
        f"/api/contracts/artifacts/{other_id}/reports/{report.json()['id']}/shares",
        json={"share_status": "shared"},
        headers=DEV_HEADERS,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_runs_reuse_the_active_run_and_link_to_the_artifact(client: AsyncClient):
    artifact_id = await _artifact_id(client)
    url = f"/api/contracts/artifacts/{artifact_id}/runs"

    first = await client.post(url, json={"foundry_agent_name": "contracts"}, headers=DEV_HEADERS)
    second = await client.post(url, json={}, headers=DEV_HEADERS)
    detail = (
        await client.get(f"/api/contracts/artifacts/{artifact_id}", headers=DEV_HEADERS)
    ).json()

    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["name"] == f"contracts:{artifact_id}"
    assert first.json()["metadata"]["artifact_id"] == artifact_id
    assert detail["artifact"]["run_ids"] == [first.json()["id"]]


@pytest.mark.asyncio
async def test_patch_updates_processing_status_and_merges_metadata(client: AsyncClient):
    artifact_id = await _register(client, metadata={"routine": "hourly"})
    artifact_id = artifact_id["results"][0]["artifact"]["id"]

    response = await client.patch(
        f"/api/contracts/artifacts/{artifact_id}",
        json={"processing_status": "processed", "metadata": {"pages": 12}},
        headers=DEV_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["processing_status"] == "processed"
    assert response.json()["metadata"] == {"routine": "hourly", "pages": 12}


@pytest.mark.asyncio
async def test_unknown_artifact_is_404_for_every_route(client: AsyncClient):
    base = "/api/contracts/artifacts/artifact-missing"
    responses = [
        await client.get(base, headers=DEV_HEADERS),
        await client.patch(base, json={}, headers=DEV_HEADERS),
        await client.post(f"{base}/extractions", json={}, headers=DEV_HEADERS),
        await client.post(
            f"{base}/evidence",
            json={"source_type": "waypoint", "claim": "c", "citation": "x"},
            headers=DEV_HEADERS,
        ),
        await client.post(f"{base}/runs", json={}, headers=DEV_HEADERS),
        await client.post(
            f"{base}/reports",
            json={"report_type": "brief", "file_url": "https://f/r.docx"},
            headers=DEV_HEADERS,
        ),
    ]

    assert [r.status_code for r in responses] == [404] * len(responses)


# --- auth -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contracts_routes_use_reader_and_writer_roles(client: AsyncClient):
    app.dependency_overrides[get_settings] = lambda: Settings(
        api_key_auth_enabled=True,
        api_keys="reader:reader-secret:reader;writer:writer-secret:writer",
    )
    reader = {"x-api-key": "reader-secret"}
    writer = {"x-api-key": "writer-secret"}

    anonymous = await client.post("/api/contracts/intake/messages/upsert", json=_message())
    reader_write = await client.post(
        "/api/contracts/intake/messages/upsert", json=_message(), headers=reader
    )
    writer_write = await client.post(
        "/api/contracts/intake/messages/upsert", json=_message(), headers=writer
    )
    artifact_id = writer_write.json()["results"][0]["artifact"]["id"]
    reader_read = await client.get(f"/api/contracts/artifacts/{artifact_id}", headers=reader)

    assert anonymous.status_code == 401
    assert reader_write.status_code == 403
    assert writer_write.status_code == 200
    assert (
        writer_write.json()["results"][0]["artifact"]["created_by"]
        == "writer@api-key.waypoint.local"
    )
    assert reader_read.status_code == 200


# --- persistence contract ---------------------------------------------------------------------


def test_postgres_schema_declares_contracts_tables():
    for table in (
        "contract_artifacts",
        "contract_intake_checkpoints",
        "contract_artifact_extractions",
        "contract_artifact_evidence",
        "contract_artifact_reports",
    ):
        assert f"create table if not exists {table}" in repository_module._SCHEMA_SQL


@pytest.mark.asyncio
async def test_postgres_contracts_repository_round_trip():
    connection_string = os.environ.get("WAYPOINT_TEST_DATABASE_CONNECTION")
    if not connection_string:
        pytest.skip("WAYPOINT_TEST_DATABASE_CONNECTION is required for PostgreSQL coverage")

    repository = repository_module.PostgresWaypointRepository(connection_string)
    try:
        await repository.initialize(load_default_seed=False)
        service = ContractsService(repository)
        run_id = uuid4().hex
        owner = f"pg-{run_id}@caldova.example"
        base_time = datetime(2026, 9, 1, tzinfo=UTC)

        def message(message_id: str, sha: str, offset_days: int) -> IntakeMessageUpsert:
            return IntakeMessageUpsert(
                mailbox_id="contracts@caldova.example",
                message_id=f"{run_id}-{message_id}",
                sender=owner,
                received_at=base_time + timedelta(days=offset_days),
                attachments=[
                    IntakeAttachment(
                        attachment_id="att", sha256=sha, original_file_uri="https://f/x.pdf"
                    )
                ],
            )

        concurrent = await asyncio.gather(
            *(service.upsert_intake_message(message("m-1", SHA_A, 0), actor="pg") for _ in range(6))
        )
        assert len({r.results[0].artifact.id for r in concurrent}) == 1
        assert [r.results[0].created for r in concurrent].count(True) == 1

        newer = await service.upsert_intake_message(message("m-2", SHA_B, 1), actor="pg")
        latest = await service.get_latest_artifact(owner, "contract")
        assert latest is not None
        assert latest.id == newer.results[0].artifact.id

        await service.add_extraction(
            latest.id, ArtifactExtractionCreate(values={"term_months": 12}), actor="pg"
        )
        detail = await service.get_artifact_detail(latest.id)
        assert detail.artifact.extracted_json == {"term_months": 12}
        assert len(detail.extractions) == 1
    finally:
        await repository.close()
