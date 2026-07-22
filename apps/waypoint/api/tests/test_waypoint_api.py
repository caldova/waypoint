"""Tests for Waypoint-owned secured invoice assurance API routes."""

import asyncio
import inspect
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

import app.common.database as database_module
import app.common.repository as repository_module
from app.common.database import (
    close_waypoint_repository,
    get_waypoint_repository_for_settings,
    reset_waypoint_repository_for_tests,
)
from app.common.settings import Settings, get_settings
from app.main import app
from app.modules.cases.schemas import AssuranceCaseCreate
from app.modules.cases.service import CasesService
from app.modules.records.schemas import FindingValidationCreate
from app.modules.records.service import WaypointService
from app.modules.runs.schemas import AgentRunCreate, AgentRunUpdate
from app.modules.runs.service import RunsService

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
async def client():
    """Create a loopback async test client."""

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    await close_waypoint_repository()
    reset_waypoint_repository_for_tests()


def override_settings(settings: Settings) -> None:
    app.dependency_overrides[get_settings] = lambda: settings


def test_postgres_repository_does_not_inherit_in_memory_repository():
    assert not issubclass(
        repository_module.PostgresWaypointRepository,
        repository_module.InMemoryWaypointRepository,
    )


def test_postgres_repository_directly_implements_repository_contract():
    contract_methods = {
        name
        for name, value in repository_module.WaypointRepository.__dict__.items()
        if inspect.iscoroutinefunction(value)
    }

    missing_methods = sorted(
        name
        for name in contract_methods
        if name not in repository_module.PostgresWaypointRepository.__dict__
    )

    assert missing_methods == []


def test_postgres_schema_includes_append_only_finding_validations():
    assert "create table if not exists finding_validations" in repository_module._SCHEMA_SQL
    assert "finding_id text generated always as" in repository_module._SCHEMA_SQL
    assert "run_id text generated always as" in repository_module._SCHEMA_SQL


def test_postgres_schema_exposes_fabriciq_typed_projection():
    """FabricIQ grounds a Direct Lake semantic model on typed, columnar data mirrored
    from the operational store. Guard the financial/transactional projection so the
    plain, replication-safe columns the semantic model depends on are not silently
    dropped, and so they never regress back to unmirrorable generated columns."""
    schema = repository_module._SCHEMA_SQL
    # Fabric mirroring cannot replicate jsonb and does not guarantee generated columns,
    # so the mirrored core's join keys must be PLAIN physical columns, populated by the
    # app on write. Out-of-scope tables (contract_documents, finding_validations, ...)
    # are not mirrored and may keep their generated helper columns.
    assert "waypoint_iso_date" not in schema

    def _create_block(table: str) -> str:
        start = schema.index(f"create table if not exists {table} (")
        return schema[start : schema.index(");", start)]

    for table in ("invoices", "invoice_lines", "reconciliation_findings"):
        assert "generated always as" not in _create_block(table)
    # Idempotent on fresh + existing databases, and normalizes any pre-existing
    # generated join keys from older deployments to plain columns.
    assert "is_generated = 'ALWAYS'" in schema
    # Non-owner-safe: the projection must not hard-require table ownership at startup.
    # ALTER TABLE / CREATE INDEX require ownership (checked before IF NOT EXISTS), so the
    # DDL is existence-guarded and any residual privilege error degrades to a NOTICE.
    assert "insufficient_privilege" in schema
    assert "information_schema.columns" in schema
    assert "raise notice" in schema
    expected = {
        "suppliers": [("name", "text"), ("status", "text"), ("category", "text")],
        "invoices": [
            ("invoice_date", "date"),
            ("due_date", "date"),
            ("status", "text"),
            ("currency", "text"),
            ("total_amount", "numeric"),
        ],
        "invoice_lines": [
            ("quantity", "numeric"),
            ("unit_price", "numeric"),
            ("amount", "numeric"),
            ("sku", "text"),
            ("purchase_order", "text"),
        ],
        "reconciliation_findings": [
            ("category", "text"),
            ("severity", "text"),
            ("status", "text"),
            ("overpayment_amount", "numeric"),
        ],
    }
    for table, columns in expected.items():
        for column, column_type in columns:
            assert f"('{table}', '{column}', '{column_type}')" in schema
    # The write path must populate the typed projection for the mirrored core tables.
    projected = repository_module._PROJECTED_COLUMNS
    assert {"suppliers", "invoices", "invoice_lines", "reconciliation_findings"} <= set(projected)
    assert ("total_amount", "numeric") in projected["invoices"]
    assert ("invoice_date", "date") in projected["invoices"]
    assert ("supplier_id", "text") in projected["invoices"]


@pytest.mark.asyncio
async def test_health_is_unauthenticated(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=False))

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.text == "Healthy"


@pytest.mark.asyncio
async def test_api_docs_are_disabled_by_default(client: AsyncClient):
    docs_response = await client.get("/docs")
    redoc_response = await client.get("/redoc")
    openapi_response = await client.get("/openapi.json")
    root_response = await client.get("/")

    assert docs_response.status_code == 404
    assert redoc_response.status_code == 404
    assert openapi_response.status_code == 404
    assert "/docs" not in root_response.text


@pytest.mark.asyncio
async def test_protected_data_route_requires_auth(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=False))

    response = await client.get("/api/suppliers")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_loopback_local_fallback_can_read_data(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get("/api/suppliers")

    assert response.status_code == 200
    assert response.json()[0]["id"]


@pytest.mark.asyncio
async def test_invoice_lookup_supports_exact_supplier_invoice_number(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get(
        "/api/invoices",
        params={"supplier_id": "sup-009", "invoice_number": "INV-2026-08034"},
    )
    missing_response = await client.get(
        "/api/invoices",
        params={"supplier_id": "sup-009", "invoice_number": "INV-DOES-NOT-EXIST"},
    )

    assert response.status_code == 200
    invoices = response.json()
    assert [invoice["id"] for invoice in invoices] == ["inv-2026-08034"]
    assert missing_response.status_code == 200
    assert missing_response.json() == []


@pytest.mark.asyncio
async def test_finding_validation_endpoint_appends_records(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    run_response = await client.post("/api/runs", json={"name": "invoice-assurance"})
    case_response = await client.post(
        "/api/cases",
        json={
            "invoice_id": "inv-2026-08034",
            "finding_id": "finding-08034-investigation",
            "summary": "Investigate rerun validation.",
        },
    )
    finding_before = (
        await client.get("/api/findings", params={"invoice_id": "inv-2026-08034"})
    ).json()[0]

    validation_payload = {
        "run_id": run_response.json()["id"],
        "case_id": case_response.json()["id"],
        "validator": "pacioli",
        "source": "pacioli",
        "outcome": "validated_existing_finding",
        "confidence": "0.97",
        "evidence_ids": ["evidence-08034-deviation"],
        "basis_summary": "Rerun observed the same missing approval evidence.",
        "evidence_snapshot": {"purchase_order": "PO-CMO-009-2026-Q4"},
        "metadata": {"rerun": 1},
    }
    first_response = await client.post(
        "/api/findings/finding-08034-investigation/validations",
        json=validation_payload,
    )
    second_response = await client.post(
        "/api/findings/finding-08034-investigation/validations",
        json={**validation_payload, "metadata": {"rerun": 2}},
    )
    list_response = await client.get("/api/findings/finding-08034-investigation/validations")
    finding_after = (
        await client.get("/api/findings", params={"invoice_id": "inv-2026-08034"})
    ).json()[0]

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert list_response.status_code == 200
    validations = list_response.json()
    validation_ids = {validation["id"] for validation in validations}
    assert first_response.json()["id"] in validation_ids
    assert second_response.json()["id"] in validation_ids
    assert first_response.json()["id"] != second_response.json()["id"]
    assert len(validations) == 2
    assert {validation["invoice_id"] for validation in validations} == {"inv-2026-08034"}
    assert {validation["outcome"] for validation in validations} == {"validated_existing_finding"}
    assert finding_after == finding_before


@pytest.mark.asyncio
async def test_postgres_finding_validations_are_append_only():
    connection_string = os.environ.get("WAYPOINT_TEST_DATABASE_CONNECTION")
    if not connection_string:
        pytest.skip("WAYPOINT_TEST_DATABASE_CONNECTION is required for PostgreSQL coverage")

    repository = repository_module.PostgresWaypointRepository(connection_string)
    try:
        await repository.initialize(load_default_seed=True)
        runs_service = RunsService(repository)
        cases_service = CasesService(repository)
        waypoint_service = WaypointService(repository)
        before_count = len(
            await waypoint_service.list_finding_validations("finding-08034-investigation")
        )

        run = await runs_service.create_agent_run(
            AgentRunCreate(name="invoice-assurance"),
            actor="postgres-test@example.com",
        )
        assurance_case = await cases_service.create_case(
            AssuranceCaseCreate(
                invoice_id="inv-2026-08034",
                finding_id="finding-08034-investigation",
                summary="PostgreSQL rerun validation.",
            ),
            actor="postgres-test@example.com",
            auth_source="test",
        )
        first = await waypoint_service.create_finding_validation(
            "finding-08034-investigation",
            FindingValidationCreate(
                run_id=run.id,
                case_id=assurance_case.id,
                source="pacioli",
                outcome="validated_existing_finding",
                confidence="0.91",
                evidence_ids=["evidence-08034-deviation"],
                basis_summary="First PostgreSQL rerun observation.",
            ),
            actor="postgres-test@example.com",
            auth_source="test",
        )
        second = await waypoint_service.create_finding_validation(
            "finding-08034-investigation",
            FindingValidationCreate(
                run_id=run.id,
                case_id=assurance_case.id,
                source="pacioli",
                outcome="validated_existing_finding",
                confidence="0.93",
                evidence_ids=["evidence-08034-contract"],
                basis_summary="Second PostgreSQL rerun observation.",
            ),
            actor="postgres-test@example.com",
            auth_source="test",
        )

        validations = await waypoint_service.list_finding_validations("finding-08034-investigation")
        validation_ids = {validation.id for validation in validations}

        assert first.id in validation_ids
        assert second.id in validation_ids
        assert first.id != second.id
        assert len(validations) == before_count + 2
        assert validations[-2].id == first.id
        assert validations[-1].id == second.id
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_invoice_decision_feed_includes_run_less_invoices_without_expected_outcomes(
    client: AsyncClient,
):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get("/api/invoice-decisions")

    assert response.status_code == 200
    decisions = response.json()
    assert len(decisions) == 1
    row = decisions[0]
    assert row["invoice_id"] == "inv-2026-08034"
    assert row["decision"] == "Not run"
    assert row["reasoning"] == "Ready for assurance."
    assert row["status"] == "not_started"
    assert row["has_agent_decision"] is False
    assert row["has_active_run"] is False
    assert row["category"] == ""
    assert row["severity"] == ""
    assert row["overpayment_amount"] == "0"
    assert row["evidence_count"] == 0
    assert row["contract_document_ids"] == []
    assert row["policy_ids"] == []

    run_response = await client.post(
        "/api/runs",
        json={
            "name": "assurance:INV-2026-08034",
            "status": "running",
            "metadata": {
                "invoice_id": "inv-2026-08034",
                "invoice_number": "INV-2026-08034",
            },
        },
    )
    assert run_response.status_code == 201

    pending = (await client.get("/api/invoice-decisions")).json()[0]
    assert pending["decision"] == "Pending"
    assert pending["reasoning"] == "Assurance review is in progress."
    assert pending["status"] == "pending"
    assert pending["has_active_run"] is True
    assert pending["category"] == ""
    assert pending["overpayment_amount"] == "0"
    assert pending["evidence_count"] == 0


@pytest.mark.asyncio
async def test_reader_can_preview_contract_and_policy_documents(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    contract_response = await client.get("/api/contract-documents/doc-cap-bluepeak-2026")
    policy_response = await client.get("/api/policies/policy-supplier-caused-cost")
    missing_contract_response = await client.get("/api/contract-documents/missing-contract")
    missing_policy_response = await client.get("/api/policies/missing-policy")

    assert contract_response.status_code == 200
    assert contract_response.json()["title"] == "BluePeak Biologics Capacity Agreement"
    assert policy_response.status_code == 200
    assert policy_response.json()["name"] == "Supplier-caused deviation cost recovery"
    assert missing_contract_response.status_code == 404
    assert missing_policy_response.status_code == 404


@pytest.mark.asyncio
async def test_non_loopback_local_fallback_denied():
    override_settings(Settings(local_auth_enabled=True))

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("198.51.100.5", 12345)),
        base_url="http://test",
    ) as remote_client:
        response = await remote_client.get("/api/suppliers")

    assert response.status_code == 401
    app.dependency_overrides.clear()
    reset_waypoint_repository_for_tests()


@pytest.mark.asyncio
async def test_reader_api_key_cannot_import_seed(client: AsyncClient):
    override_settings(
        Settings(
            api_key_auth_enabled=True,
            api_keys="reader-key:reader-secret:reader;admin-key:admin-secret:admin",
        )
    )

    read_response = await client.get("/api/invoices", headers={"x-api-key": "reader-secret"})
    write_response = await client.post(
        "/api/admin/seed/ledgerfield",
        headers={"x-api-key": "reader-secret"},
        json={"source": "ledgerfield-test"},
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403


@pytest.mark.asyncio
async def test_configured_api_key_fallback_can_read_when_msal_enabled(client: AsyncClient):
    override_settings(
        Settings(
            msal_bearer_validation_enabled=True,
            msal_tenant_id="tenant-id",
            msal_client_id="client-id",
            api_key_auth_enabled=True,
            api_keys="reader-key:reader-secret:reader",
            local_auth_enabled=True,
        )
    )

    response = await client.get("/api/suppliers", headers={"x-api-key": "reader-secret"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_api_key_imports_ledgerfield_seed(client: AsyncClient):
    override_settings(
        Settings(
            api_key_auth_enabled=True,
            api_keys="reader-key:reader-secret:reader;admin-key:admin-secret:admin",
        )
    )

    response = await client.post(
        "/api/admin/seed/ledgerfield",
        headers={"x-api-key": "admin-secret"},
        json={
            "source": "ledgerfield-test",
            "suppliers": [
                {
                    "id": "supplier-test",
                    "name": "Test Supplier",
                }
            ],
            "contract_documents": [
                {
                    "id": "contract-test",
                    "supplier_id": "supplier-test",
                    "title": "Test Supplier MSA",
                }
            ],
            "policies": [
                {
                    "id": "policy-test",
                    "name": "Test approval policy",
                }
            ],
            "scenarios": [
                {
                    "id": "scenario-test",
                    "name": "Test Scenario",
                }
            ],
            "invoices": [
                {
                    "id": "invoice-test",
                    "supplier_id": "supplier-test",
                    "scenario_id": "scenario-test",
                    "invoice_number": "INV-TEST",
                    "total_amount": "42.50",
                    "lines": [
                        {
                            "id": "line-test",
                            "invoice_id": "invoice-test",
                            "description": "Test line",
                            "amount": "42.50",
                        }
                    ],
                    "findings": [
                        {
                            "id": "finding-test",
                            "invoice_id": "invoice-test",
                            "scenario_id": "scenario-test",
                            "category": "Duplicate invoice",
                            "summary": "Duplicate invoice detected.",
                            "contract_document_ids": ["contract-test"],
                            "policy_ids": ["policy-test"],
                            "basis_summary": "Test Supplier MSA plus approval policy",
                        }
                    ],
                    "evidence": [
                        {
                            "id": "evidence-test",
                            "invoice_id": "invoice-test",
                            "finding_id": "finding-test",
                            "title": "Generated invoice PDF",
                            "uri": "ledgerfield://generated/invoices/INV-TEST.pdf",
                        }
                    ],
                }
            ],
        },
    )
    detail_response = await client.get(
        "/api/invoices/invoice-test",
        headers={"x-api-key": "reader-secret"},
    )

    assert response.status_code == 200
    assert response.json()["invoices"] == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["pdf_uri"] is None
    assert detail_response.json()["lines"][0]["id"] == "line-test"
    assert detail_response.json()["findings"][0]["contract_document_ids"] == ["contract-test"]
    assert detail_response.json()["findings"][0]["policy_ids"] == ["policy-test"]


@pytest.mark.asyncio
async def test_seed_import_rejects_unknown_references(client: AsyncClient):
    override_settings(
        Settings(
            api_key_auth_enabled=True,
            api_keys="admin-key:admin-secret:admin",
        )
    )

    response = await client.post(
        "/api/admin/seed/ledgerfield",
        headers={"x-api-key": "admin-secret"},
        json={
            "source": "bad-ledgerfield-test",
            "invoices": [
                {
                    "id": "invoice-bad",
                    "supplier_id": "missing-supplier",
                    "invoice_number": "INV-BAD",
                }
            ],
        },
    )

    assert response.status_code == 422
    assert "unknown supplier" in response.json()["detail"]


@pytest.mark.asyncio
async def test_seed_import_rejects_unknown_contract_and_policy_refs(client: AsyncClient):
    override_settings(
        Settings(
            api_key_auth_enabled=True,
            api_keys="admin-key:admin-secret:admin",
        )
    )

    response = await client.post(
        "/api/admin/seed/ledgerfield",
        headers={"x-api-key": "admin-secret"},
        json={
            "source": "bad-basis-test",
            "suppliers": [{"id": "supplier-basis", "name": "Basis Supplier"}],
            "invoices": [
                {
                    "id": "invoice-basis",
                    "supplier_id": "supplier-basis",
                    "invoice_number": "INV-BASIS",
                    "findings": [
                        {
                            "id": "finding-basis",
                            "invoice_id": "invoice-basis",
                            "category": "Rate card",
                            "summary": "Finding references missing basis records.",
                            "contract_document_ids": ["missing-contract"],
                            "policy_ids": ["missing-policy"],
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 422
    assert "unknown contract document" in response.json()["detail"]
    assert "unknown policy" in response.json()["detail"]


@pytest.mark.asyncio
async def test_configured_ledgerfield_seed_path_imports_on_startup(tmp_path):
    seed_path = tmp_path / "waypoint-seed.json"
    seed_path.write_text(
        json.dumps(
            {
                "source": "configured-ledgerfield-test",
                "suppliers": [{"id": "supplier-configured", "name": "Configured Supplier"}],
                "contract_documents": [
                    {
                        "id": "contract-configured",
                        "supplier_id": "supplier-configured",
                        "title": "Configured Supplier MSA",
                    }
                ],
                "policies": [{"id": "policy-configured", "name": "Configured Policy"}],
                "invoices": [
                    {
                        "id": "invoice-configured",
                        "supplier_id": "supplier-configured",
                        "invoice_number": "INV-CONFIGURED",
                        "findings": [
                            {
                                "id": "finding-configured",
                                "invoice_id": "invoice-configured",
                                "category": "Rate card",
                                "summary": "Configured import finding.",
                                "contract_document_ids": ["contract-configured"],
                                "policy_ids": ["policy-configured"],
                            }
                        ],
                    }
                ],
            }
        )
    )

    repository = await get_waypoint_repository_for_settings(
        Settings(ledgerfield_seed_path=str(seed_path))
    )
    invoices = await WaypointService(repository).list_invoices()

    # The configured seed replaces the default seed on startup.
    assert any(invoice.invoice_number == "INV-CONFIGURED" for invoice in invoices)
    assert not any(invoice.invoice_number == "INV-2026-08034" for invoice in invoices)
    reset_waypoint_repository_for_tests()


@pytest.mark.asyncio
async def test_no_implicit_seed_when_default_seed_disabled():
    repository = await get_waypoint_repository_for_settings(Settings(default_seed_enabled=False))
    decisions = await WaypointService(repository).list_invoice_decisions()

    assert decisions == []
    reset_waypoint_repository_for_tests()


@pytest.mark.asyncio
async def test_bootstrap_connection_requires_complete_application_connection():
    with pytest.raises(ValueError, match="dbname, user, and password"):
        await database_module._bootstrap_postgres_application_role(
            "host=db.example.com dbname=postgres user=admin password=adminpass sslmode=require",
            "host=db.example.com dbname=waypoint user=waypoint_app sslmode=require",
        )


@pytest.mark.asyncio
async def test_fabric_mirror_bootstrap_skips_without_password():
    # With no password configured the bootstrap must no-op (never open a connection) so an
    # enabled-but-unconfigured deploy is safe rather than fatal.
    await database_module._bootstrap_fabric_mirroring_role(
        "host=db.example.com dbname=postgres user=admin password=adminpass sslmode=require",
        "host=db.example.com dbname=waypoint user=waypoint_app password=apppass sslmode=require",
        Settings(fabric_mirror_enabled=True, fabric_mirror_password=""),
    )


@pytest.mark.asyncio
async def test_fabric_mirror_bootstrap_requires_dbname_and_user():
    with pytest.raises(ValueError, match="dbname and user"):
        await database_module._bootstrap_fabric_mirroring_role(
            "host=db.example.com dbname=postgres user=admin password=adminpass sslmode=require",
            "host=db.example.com sslmode=require",
            Settings(fabric_mirror_enabled=True, fabric_mirror_password="mirrorpass"),
        )


@pytest.mark.asyncio
async def test_admin_can_query_audit_events(client: AsyncClient):
    override_settings(
        Settings(
            api_key_auth_enabled=True,
            api_keys="admin-key:admin-secret:admin",
        )
    )

    await client.get("/api/suppliers", headers={"x-api-key": "admin-secret"})
    response = await client.get("/api/audit/events", headers={"x-api-key": "admin-secret"})

    assert response.status_code == 200
    assert any(event["route"] == "/api/suppliers" for event in response.json())


@pytest.mark.asyncio
async def test_invoice_context_and_work_queue_include_control_plane_data(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    case_response = await client.post(
        "/api/cases",
        json={
            "invoice_id": "inv-2026-08034",
            "finding_id": "finding-08034-investigation",
            "summary": "Investigate supplier-caused investigation charge.",
        },
    )
    context_response = await client.get("/api/invoices/inv-2026-08034/context")
    queue_response = await client.get("/api/work")

    assert case_response.status_code == 201
    case_id = case_response.json()["id"]
    assert context_response.status_code == 200
    context = context_response.json()
    assert context["invoice"]["id"] == "inv-2026-08034"
    assert context["contract_documents"][0]["id"] == "doc-cap-bluepeak-2026"
    assert context["policies"][0]["id"] == "policy-supplier-caused-cost"
    assert context["cases"][0]["id"] == case_id
    assert {action["id"] for action in context["allowed_actions"]} >= {
        "recommend_recover",
        "draft_supplier_dispute",
    }
    assert queue_response.status_code == 200
    assert any(item["case_id"] == case_id for item in queue_response.json())


@pytest.mark.asyncio
async def test_case_lifecycle_hash_bound_approval_and_authorized_intent(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    case = (
        await client.post(
            "/api/cases",
            json={
                "invoice_id": "inv-2026-08034",
                "finding_id": "finding-08034-investigation",
                "classification": "confidential",
            },
        )
    ).json()
    recommendation_response = await client.post(
        f"/api/cases/{case['id']}/recommendations",
        json={
            "decision": "recover",
            "reasoning": "The investigation charge is supplier-caused per the deviation record.",
            "confidence": "0.91",
            "money_at_risk": "25000",
            "evidence_ids": ["evidence-08034-deviation", "evidence-08034-contract"],
            "proposed_next_actions": ["draft_supplier_dispute"],
            "foundry_response_id": "resp-test-1",
        },
    )
    draft_response = await client.post(
        f"/api/cases/{case['id']}/drafts",
        json={
            "draft_type": "supplier_dispute",
            "title": "Dispute supplier-caused investigation charge",
            "body": (
                "Please provide the deviation disposition for the "
                "supplier-caused investigation charge."
            ),
            "source_recommendation_id": recommendation_response.json()["id"],
            "classification": "confidential",
        },
    )
    draft = draft_response.json()
    action_response = await client.post(
        f"/api/cases/{case['id']}/actions",
        json={
            "action_type_id": "draft_supplier_dispute",
            "title": "Stage dispute note",
            "description": "Prepare dispute for procurement approval.",
            "draft_id": draft["id"],
            "recommendation_id": recommendation_response.json()["id"],
        },
    )
    approval_payload = {
        "proposed_action_id": action_response.json()["id"],
        "decision": "approved",
        "justification": "Evidence supports recovery.",
        "artifact_id": draft["id"],
        "artifact_version": draft["version"],
        "artifact_content_hash": draft["content_hash"],
        "idempotency_key": "approval-test-1",
    }
    approval_response = await client.post(
        f"/api/cases/{case['id']}/approvals",
        json=approval_payload,
    )
    duplicate_approval_response = await client.post(
        f"/api/cases/{case['id']}/approvals",
        json=approval_payload,
    )
    intent_response = await client.post(
        f"/api/actions/{action_response.json()['id']}/authorize",
        json={
            "approval_id": approval_response.json()["id"],
            "idempotency_key": "intent-test-1",
            "foundry_snapshot": {
                "foundry_response_id": "resp-test-1",
                "groundedness": 0.94,
            },
        },
    )
    duplicate_intent_response = await client.post(
        f"/api/actions/{action_response.json()['id']}/authorize",
        json={
            "approval_id": approval_response.json()["id"],
            "idempotency_key": "intent-test-1",
        },
    )
    audit_response = await client.get("/api/audit/decisions")

    assert recommendation_response.status_code == 201
    assert draft_response.status_code == 201
    assert action_response.status_code == 201
    assert approval_response.status_code == 201
    assert duplicate_approval_response.json()["id"] == approval_response.json()["id"]
    assert intent_response.status_code == 200
    intent = intent_response.json()
    assert intent["status"] == "authorized"
    assert intent["foundry_snapshot"]["groundedness"] == 0.94
    assert duplicate_intent_response.status_code == 200
    assert duplicate_intent_response.json()["id"] == intent["id"]
    assert audit_response.status_code == 200
    assert {event["event_type"] for event in audit_response.json()} >= {
        "case_created",
        "recommendation_created",
        "draft_created",
        "action_proposed",
        "approval_recorded",
        "intent_authorized",
    }


@pytest.mark.asyncio
async def test_reader_api_key_cannot_create_control_plane_case(client: AsyncClient):
    override_settings(
        Settings(
            api_key_auth_enabled=True,
            api_keys="reader-key:reader-secret:reader",
            default_seed_enabled=True,
        )
    )

    read_response = await client.get(
        "/api/work",
        headers={"x-api-key": "reader-secret"},
    )
    write_response = await client.post(
        "/api/cases",
        headers={"x-api-key": "reader-secret"},
        json={
            "invoice_id": "inv-2026-08034",
            "finding_id": "finding-08034-investigation",
        },
    )

    assert read_response.status_code == 200
    assert write_response.status_code == 403


@pytest.mark.asyncio
async def test_authorization_requires_current_approval_and_matching_draft_hash(
    client: AsyncClient,
):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    case = (
        await client.post(
            "/api/cases",
            json={
                "invoice_id": "inv-2026-08034",
                "finding_id": "finding-08034-investigation",
            },
        )
    ).json()
    draft_a = (
        await client.post(
            f"/api/cases/{case['id']}/drafts",
            json={
                "draft_type": "supplier_dispute",
                "title": "Draft A",
                "body": "First dispute draft.",
            },
        )
    ).json()
    draft_b = (
        await client.post(
            f"/api/cases/{case['id']}/drafts",
            json={
                "draft_type": "supplier_dispute",
                "title": "Draft B",
                "body": "Second dispute draft.",
            },
        )
    ).json()
    action = (
        await client.post(
            f"/api/cases/{case['id']}/actions",
            json={
                "action_type_id": "draft_supplier_dispute",
                "title": "Approve Draft A",
                "draft_id": draft_a["id"],
            },
        )
    ).json()

    mismatched_approval_response = await client.post(
        f"/api/cases/{case['id']}/approvals",
        json={
            "proposed_action_id": action["id"],
            "decision": "approved",
            "artifact_id": draft_b["id"],
            "artifact_version": draft_b["version"],
            "artifact_content_hash": draft_b["content_hash"],
        },
    )
    empty_hash_approval_response = await client.post(
        f"/api/cases/{case['id']}/approvals",
        json={
            "proposed_action_id": action["id"],
            "decision": "approved",
            "artifact_id": draft_a["id"],
            "artifact_version": 0,
            "artifact_content_hash": "",
        },
    )
    approved_response = await client.post(
        f"/api/cases/{case['id']}/approvals",
        json={
            "proposed_action_id": action["id"],
            "decision": "approved",
            "artifact_id": draft_a["id"],
            "artifact_version": draft_a["version"],
            "artifact_content_hash": draft_a["content_hash"],
        },
    )
    rejected_response = await client.post(
        f"/api/cases/{case['id']}/approvals",
        json={
            "proposed_action_id": action["id"],
            "decision": "rejected",
            "artifact_id": draft_a["id"],
            "artifact_version": draft_a["version"],
            "artifact_content_hash": draft_a["content_hash"],
        },
    )
    authorize_response = await client.post(
        f"/api/actions/{action['id']}/authorize",
        json={"approval_id": approved_response.json()["id"]},
    )

    assert mismatched_approval_response.status_code == 422
    assert "must match" in mismatched_approval_response.json()["detail"]
    assert empty_hash_approval_response.status_code == 422
    assert "version must be positive" in empty_hash_approval_response.json()["detail"]
    assert approved_response.status_code == 201
    assert rejected_response.status_code == 201
    assert authorize_response.status_code == 422
    assert "currently approved" in authorize_response.json()["detail"]


@pytest.mark.asyncio
async def test_invoice_assurance_surfaces_agent_decision_and_draft(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    case = (
        await client.post(
            "/api/cases",
            json={
                "invoice_id": "inv-2026-08034",
                "finding_id": "finding-08034-investigation",
                "summary": "Review supplier-caused investigation charge.",
            },
        )
    ).json()
    await client.post(
        f"/api/cases/{case['id']}/recommendations",
        json={
            "decision": "review",
            "reasoning": "Only the web/regulatory lane is available for this run.",
            "confidence": "0.55",
            "money_at_risk": "25000",
            "evidence_ids": ["evidence-08034-deviation", "evidence-08034-contract"],
            "proposed_next_actions": [
                "Obtain and reconcile PO, invoice line detail, and receipt.",
                "Review governing capacity contract for approval and credit provisions.",
            ],
            "metadata": {
                "expert_evidence": [
                    {
                        "agent": "webiq-expert",
                        "plane": "webiq",
                        "summary": "External CMO agreements support review.",
                        "evidence": [
                            {
                                "claim": "FDA quality-agreement guidance.",
                                "supports": "review",
                                "confidence": 0.86,
                                "source_ref": "https://www.fda.gov/regulatory-information",
                                "classification": "standard",
                            },
                            {
                                "claim": "Public Lonza/SutroVax agreement on mitigation.",
                                "supports": "recover",
                                "confidence": 0.82,
                                "source_ref": "https://www.sec.gov/Archives/edgar/data/1649094",
                                "classification": "standard",
                            },
                        ],
                    }
                ]
            },
        },
    )
    await client.post(
        f"/api/cases/{case['id']}/drafts",
        json={
            "draft_type": "approval_summary",
            "title": "Review hold summary for INV-2026-08034",
            "body": "Hold invoice INV-2026-08034 for review pending corroboration.",
        },
    )

    response = await client.get("/api/invoices/inv-2026-08034/assurance")

    assert response.status_code == 200
    assurance = response.json()
    assert assurance["invoice_id"] == "inv-2026-08034"
    assert assurance["has_agent_decision"] is True
    assert len(assurance["cases"]) == 1
    view = assurance["cases"][0]
    assert view["case"]["id"] == case["id"]

    recommendation = view["latest_recommendation"]
    assert recommendation["decision"] == "review"
    assert recommendation["proposed_next_actions"]

    drafts = view["drafts"]
    assert len(drafts) == 1
    assert drafts[0]["draft_type"] == "approval_summary"

    evidence_ids = {item["id"] for item in view["evidence"]}
    assert evidence_ids == {"evidence-08034-deviation", "evidence-08034-contract"}

    source_refs = {source["source_ref"] for source in view["sources"]}
    assert "https://www.fda.gov/regulatory-information" in source_refs
    assert "https://www.sec.gov/Archives/edgar/data/1649094" in source_refs


@pytest.mark.asyncio
async def test_invoice_assurance_empty_state_when_no_agent_case(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get("/api/invoices/inv-2026-08034/assurance")

    assert response.status_code == 200
    assurance = response.json()
    assert assurance["invoice_id"] == "inv-2026-08034"
    assert assurance["has_agent_decision"] is False
    assert assurance["cases"] == []


@pytest.mark.asyncio
async def test_invoice_assurance_requires_auth(client: AsyncClient):
    override_settings(Settings(default_seed_enabled=True))

    response = await client.get("/api/invoices/inv-2026-08034/assurance")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invoice_decision_feed_reflects_newest_agent_run(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    # Seed two disagreeing agent runs for the same invoice. The decision-graph list row
    # must follow the NEWEST run (so the list and the drawer agree) and expose attribution.
    older = (
        await client.post(
            "/api/cases",
            json={"invoice_id": "inv-2026-08034", "summary": "Older run."},
        )
    ).json()
    await client.post(
        f"/api/cases/{older['id']}/recommendations",
        json={
            "decision": "escalate",
            "reasoning": "Supplier-caused investigation charge.",
            "money_at_risk": "25000",
        },
    )
    newer = (
        await client.post(
            "/api/cases",
            json={"invoice_id": "inv-2026-08034", "summary": "Newer run."},
        )
    ).json()
    await client.post(
        f"/api/cases/{newer['id']}/recommendations",
        json={
            "decision": "recover",
            "reasoning": "Recover supplier-caused investigation charge.",
            "confidence": "0.86",
            "money_at_risk": "18750",
            "metadata": {
                "expert_evidence": [
                    {
                        "agent": "contract",
                        "plane": "contract",
                        "evidence": [
                            {"claim": "capacity agreement cap", "source_ref": "doc-cap#1"},
                            {"claim": "deviation cost table", "source_ref": "doc-cap#2"},
                        ],
                    },
                    {
                        "agent": "policy",
                        "plane": "policy",
                        "evidence": [{"claim": "supplier-caused cost", "source_ref": "policy#3"}],
                    },
                ]
            },
        },
    )

    response = await client.get("/api/invoice-decisions")
    assert response.status_code == 200
    decisions = response.json()

    row = next(d for d in decisions if d["invoice_id"] == "inv-2026-08034")
    assert row["decision"] == "Recover"
    assert row["agent_decision"] == "Recover"
    assert row["has_agent_decision"] is True
    assert row["agent_run_count"] == 2
    assert row["agent_run_index"] == 2
    assert row["agent_case_id"] == newer["id"]
    assert row["agent_run_at"] is not None
    # The list money follows the newest run's money_at_risk, not the seed finding amount.
    assert row["overpayment_amount"] == "18750"
    assert row["overpayment_display"] == "$18,750"
    # The row is sourced from the newest agent case: confidence and the per-expert
    # evidence plane/source counts come from the newest recommendation. The case was
    # opened without a title, so Waypoint fabricated the bare-invoice-number fallback;
    # the register must NOT echo that as reasoning — agent_title is None and the
    # register falls through to the descriptive finding summary.
    assert row["confidence"] == "0.86"
    assert row["agent_title"] is None
    assert row["reasoning"] == (
        "Contamination investigation charge is billed although the deviation "
        "record indicates supplier-caused contamination."
    )
    assert row["agent_plane_count"] == 2
    assert row["agent_source_count"] == 3


@pytest.mark.asyncio
async def test_invoice_decision_reasoning_prefers_title_then_summary(client: AsyncClient):
    """The register never surfaces the bare-invoice-number case title as reasoning.

    Waypoint fabricates a placeholder case title ("{invoice_number}" or
    "{invoice_number}: {category}") whenever the recorder opens a case without one —
    which is every case the orchestrator early-opens, since the descriptive title from
    the decision does not exist at fan-out time and title is set-once at create. A
    genuine, human-authored title still passes through to agent_title; the placeholder
    forms are suppressed so the row falls through to the finding summary.
    """
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    # Genuine decision-framed title -> passes through untouched (even ending in the
    # invoice number, because only a leading invoice number marks the fallback).
    titled = (
        await client.post(
            "/api/cases",
            json={
                "invoice_id": "inv-2026-08034",
                "title": "Recover supplier-caused investigation charge for INV-2026-08034",
                "summary": "Titled run.",
            },
        )
    ).json()
    await client.post(
        f"/api/cases/{titled['id']}/recommendations",
        json={"decision": "recover", "reasoning": "Recover.", "money_at_risk": "1000"},
    )

    titled_row = next(
        d
        for d in (await client.get("/api/invoice-decisions")).json()
        if d["invoice_id"] == "inv-2026-08034"
    )
    assert titled_row["agent_title"] == (
        "Recover supplier-caused investigation charge for INV-2026-08034"
    )

    # The "{invoice_number}: {category}" fallback (set when a case is opened against a
    # finding without an explicit title) is also suppressed, not echoed as reasoning.
    with_category = (
        await client.post(
            "/api/cases",
            json={
                "invoice_id": "inv-2026-08034",
                "title": "INV-2026-08034: Quality deviation",
                "summary": "Fallback-titled run.",
            },
        )
    ).json()
    await client.post(
        f"/api/cases/{with_category['id']}/recommendations",
        json={"decision": "recover", "reasoning": "Recover.", "money_at_risk": "1000"},
    )

    fallback_row = next(
        d
        for d in (await client.get("/api/invoice-decisions")).json()
        if d["invoice_id"] == "inv-2026-08034"
    )
    assert fallback_row["agent_title"] is None
    assert fallback_row["reasoning"] == (
        "Contamination investigation charge is billed although the deviation "
        "record indicates supplier-caused contamination."
    )
    """A run opened as running can be transitioned to completed via PATCH."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    open_response = await client.post(
        "/api/runs",
        json={"name": "assurance:INV-1", "status": "running"},
    )
    assert open_response.status_code == 201
    run = open_response.json()
    assert run["status"] == "running"

    patch_response = await client.patch(
        f"/api/runs/{run['id']}",
        json={
            "status": "completed",
            "summary": "RECOVER INV-1: 4 experts consulted.",
            "metadata": {"fanout": [{"agent": "workiq-expert", "summary": "done"}]},
        },
    )
    assert patch_response.status_code == 200
    updated = patch_response.json()
    assert updated["id"] == run["id"]
    assert updated["status"] == "completed"
    assert updated["summary"].startswith("RECOVER")
    assert updated["metadata"]["fanout"][0]["agent"] == "workiq-expert"
    assert updated["updated_at"] >= run["updated_at"]

    listed = (await client.get("/api/runs")).json()
    assert [r for r in listed if r["id"] == run["id"]][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_agent_run_patch_missing_returns_404(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.patch("/api/runs/run-does-not-exist", json={"status": "failed"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_open_is_idempotent_by_key(client: AsyncClient):
    """Opening a run twice with the same idempotency_key returns the same anchor."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    body = {"name": "assurance:INV-2", "status": "running", "idempotency_key": "open-inv-2"}
    first = await client.post("/api/runs", json=body)
    second = await client.post("/api/runs", json=body)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = (await client.get("/api/runs")).json()
    assert len([r for r in listed if r.get("idempotency_key") == "open-inv-2"]) == 1


@pytest.mark.asyncio
async def test_agent_run_open_is_deduped_by_invoice_name(client: AsyncClient):
    """A same-invoice second open (same name, no exact key) reuses the active run (W2)."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    body = {"name": "assurance:INV-DUP", "status": "running"}
    first = await client.post("/api/runs", json=body)
    second = await client.post("/api/runs", json=body)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    # A different invoice is unaffected and gets its own anchor.
    other = await client.post(
        "/api/runs", json={"name": "assurance:INV-OTHER", "status": "running"}
    )
    assert other.json()["id"] != first.json()["id"]

    listed = (await client.get("/api/runs")).json()
    assert len([r for r in listed if r["name"] == "assurance:INV-DUP"]) == 1


@pytest.mark.asyncio
async def test_concurrent_agent_run_opens_reuse_one_active_anchor():
    repository = repository_module.InMemoryWaypointRepository()
    service = RunsService(repository)
    create = AgentRunCreate(
        name="assurance:INV-CONCURRENT",
        status="running",
        idempotency_key="open-inv-concurrent",
    )

    runs = await asyncio.gather(
        *(service.create_agent_run(create, actor="agent") for _ in range(20))
    )

    assert len({run.id for run in runs}) == 1
    assert len(await repository.list_agent_runs()) == 1


@pytest.mark.asyncio
async def test_agent_run_open_after_terminal_creates_new_run(client: AsyncClient):
    """A finalized (non-active) run does not get reused; a new open creates a fresh anchor."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    first = await client.post(
        "/api/runs", json={"name": "assurance:INV-REOPEN", "status": "running"}
    )
    first_id = first.json()["id"]
    finalized = await client.patch(f"/api/runs/{first_id}", json={"status": "completed"})
    assert finalized.json()["status"] == "completed"

    second = await client.post(
        "/api/runs", json={"name": "assurance:INV-REOPEN", "status": "running"}
    )
    assert second.status_code == 201
    assert second.json()["id"] != first_id


@pytest.mark.asyncio
async def test_agent_run_persists_app_insights_operation_id_on_create(client: AsyncClient):
    """POST /runs accepts and stores a recorder-supplied app_insights_operation_id (W3)."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    created = await client.post(
        "/api/runs",
        json={
            "name": "assurance:INV-OP",
            "status": "running",
            "app_insights_operation_id": "op-abc123",
        },
    )
    assert created.status_code == 201
    assert created.json()["app_insights_operation_id"] == "op-abc123"

    listed = (await client.get("/api/runs")).json()
    stored = next(r for r in listed if r["id"] == created.json()["id"])
    assert stored["app_insights_operation_id"] == "op-abc123"


@pytest.mark.asyncio
async def test_agent_run_patch_sets_operation_id(client: AsyncClient):
    """A later PATCH can set app_insights_operation_id once the operation id is known (W3)."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    created = await client.post(
        "/api/runs", json={"name": "assurance:INV-OP2", "status": "running"}
    )
    assert created.json()["app_insights_operation_id"] is None

    patched = await client.patch(
        f"/api/runs/{created.json()['id']}",
        json={"app_insights_operation_id": "op-late-xyz"},
    )
    assert patched.status_code == 200
    assert patched.json()["app_insights_operation_id"] == "op-late-xyz"


@pytest.mark.asyncio
async def test_agent_run_reuse_backfills_operation_id(client: AsyncClient):
    """Reusing an active anchor backfills a correlation id the early-open lacked (W2 + W3)."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    first = await client.post("/api/runs", json={"name": "assurance:INV-BF", "status": "running"})
    first_id = first.json()["id"]
    assert first.json()["app_insights_operation_id"] is None

    second = await client.post(
        "/api/runs",
        json={
            "name": "assurance:INV-BF",
            "status": "running",
            "app_insights_operation_id": "op-enriched",
        },
    )
    assert second.json()["id"] == first_id
    assert second.json()["app_insights_operation_id"] == "op-enriched"


@pytest.mark.asyncio
async def test_agent_run_backfill_does_not_overwrite_concurrent_finalize():
    """A terminal finalize racing W3 backfill wins while the correlation id is still enriched."""

    class _FinalizeDuringBackfillRepo(repository_module.InMemoryWaypointRepository):
        def __init__(self) -> None:
            super().__init__()
            self._finalized = False

        async def compare_and_swap_agent_run(self, run, expected):
            if not self._finalized:
                self._finalized = True
                current = self.agent_runs[run.id]
                self.agent_runs[run.id] = current.model_copy(
                    update={"status": "completed", "updated_at": datetime.now(UTC)}
                )
            return await super().compare_and_swap_agent_run(run, expected)

    repository = _FinalizeDuringBackfillRepo()
    await repository.initialize(load_default_seed=False)
    service = RunsService(repository)
    first = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-BACKFILL-RACE"),
        actor="backfill-test@example.com",
    )

    reused = await service.create_agent_run(
        AgentRunCreate(
            name=first.name,
            app_insights_operation_id="op-concurrent-finalize",
        ),
        actor="backfill-test@example.com",
    )

    assert reused.status == "completed"
    assert reused.app_insights_operation_id == "op-concurrent-finalize"
    stored = await repository.get_agent_run(first.id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.app_insights_operation_id == "op-concurrent-finalize"


@pytest.mark.asyncio
async def test_agent_run_finalize_preserves_concurrent_backfill():
    """A terminal finalize retries against and preserves W3 enrichment."""

    class _BackfillDuringFinalizeRepo(repository_module.InMemoryWaypointRepository):
        def __init__(self) -> None:
            super().__init__()
            self._enriched = False

        async def compare_and_swap_agent_run(self, run, expected):
            if not self._enriched:
                self._enriched = True
                current = self.agent_runs[run.id]
                self.agent_runs[run.id] = current.model_copy(
                    update={
                        "app_insights_operation_id": "op-raced-backfill",
                        "updated_at": datetime.now(UTC),
                    }
                )
            return await super().compare_and_swap_agent_run(run, expected)

    repository = _BackfillDuringFinalizeRepo()
    await repository.initialize(load_default_seed=False)
    service = RunsService(repository)
    opened = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-FINALIZE-RACE"),
        actor="finalize-test@example.com",
    )

    finalized = await service.update_agent_run(opened.id, AgentRunUpdate(status="completed"))

    assert finalized is not None
    assert finalized.status == "completed"
    assert finalized.app_insights_operation_id == "op-raced-backfill"


def test_run_reaper_ttl_defaults_above_orchestrator_bound():
    """The reaper defaults to running-only with a 35m backstop TTL above the orchestrator (W1)."""
    settings = Settings()
    assert settings.run_reaper_enabled is True
    # 2100s = 35m > the orchestrator's 30m max_runtime_minutes self-bound, so the reaper is a
    # pure process-death backstop and never false-positives a live, non-heartbeating run.
    assert settings.run_reaper_ttl_seconds == 2100
    assert settings.run_reaper_ttl_seconds > 30 * 60
    # Pending runs are queued batch placeholders; reaping them is opt-in (0 = disabled) so a long
    # queue wait never kills legitimately-queued work.
    assert settings.run_reaper_pending_ttl_seconds == 0


@pytest.mark.asyncio
async def test_reap_stale_runs_targets_running_only_by_default():
    """The reaper fails a stale running run but never a pending, fresh, or terminal run (W1)."""
    repository = repository_module.InMemoryWaypointRepository()
    await repository.initialize(load_default_seed=False)
    service = RunsService(repository)

    stale = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-STALE"), actor="reaper-test@example.com"
    )
    fresh = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-FRESH"), actor="reaper-test@example.com"
    )
    pending = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-QUEUED", status="pending"),
        actor="reaper-test@example.com",
    )
    terminal = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-DONE", status="completed"),
        actor="reaper-test@example.com",
    )

    # Force the stale running run, the queued pending run, and an old terminal run all beyond
    # any short TTL, to prove pending/terminal are excluded by scope, not just by age.
    for run in (stale, pending, terminal):
        await repository.update_agent_run(
            run.model_copy(update={"updated_at": run.updated_at - timedelta(hours=1)})
        )

    reaped = await service.reap_stale_runs(running_ttl_seconds=600)

    assert [run.id for run in reaped] == [stale.id]
    reaped_run = await repository.get_agent_run(stale.id)
    assert reaped_run is not None
    assert reaped_run.status == "failed"
    assert reaped_run.metadata["reaped"] is True
    assert "running" in reaped_run.metadata["reap_reason"]
    assert reaped_run.metadata["reaped_at"]

    # A queued pending run, a fresh running run, and a terminal run are never touched by default.
    pending_after = await repository.get_agent_run(pending.id)
    fresh_after = await repository.get_agent_run(fresh.id)
    terminal_after = await repository.get_agent_run(terminal.id)
    assert pending_after is not None and pending_after.status == "pending"
    assert fresh_after is not None and fresh_after.status == "running"
    assert terminal_after is not None and terminal_after.status == "completed"

    # Reaping is idempotent: a second sweep finds nothing left to fail.
    assert await service.reap_stale_runs(running_ttl_seconds=600) == []


@pytest.mark.asyncio
async def test_reap_stale_runs_reaps_pending_only_when_opted_in():
    """A stale pending run is reaped only when a pending TTL is provided (opt-in, W1)."""
    repository = repository_module.InMemoryWaypointRepository()
    await repository.initialize(load_default_seed=False)
    service = RunsService(repository)

    pending = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-ORPHANED", status="pending"),
        actor="reaper-test@example.com",
    )
    await repository.update_agent_run(
        pending.model_copy(update={"updated_at": pending.updated_at - timedelta(hours=3)})
    )

    # Default (pending reaping disabled) leaves it queued.
    assert await service.reap_stale_runs(running_ttl_seconds=600) == []
    still_pending = await repository.get_agent_run(pending.id)
    assert still_pending is not None and still_pending.status == "pending"

    # Opting in with a long pending TTL reaps the orphaned queue placeholder.
    reaped = await service.reap_stale_runs(running_ttl_seconds=600, pending_ttl_seconds=7200)
    assert [run.id for run in reaped] == [pending.id]
    reaped_run = await repository.get_agent_run(pending.id)
    assert reaped_run is not None
    assert reaped_run.status == "failed"
    assert "pending" in reaped_run.metadata["reap_reason"]


@pytest.mark.asyncio
async def test_reap_stale_runs_is_safe_under_concurrent_sweeps():
    """Two sweepers racing the same stale row converge on failed with no error (multi-replica)."""
    repository = repository_module.InMemoryWaypointRepository()
    await repository.initialize(load_default_seed=False)
    service = RunsService(repository)

    stale = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-RACE"), actor="reaper-test@example.com"
    )
    await repository.update_agent_run(
        stale.model_copy(update={"updated_at": stale.updated_at - timedelta(hours=1)})
    )

    # Simulate two container replicas sweeping simultaneously. Reaping only ever moves a
    # running run to a terminal state, so racing UPDATEs converge instead of raising.
    results = await asyncio.gather(
        service.reap_stale_runs(running_ttl_seconds=600),
        service.reap_stale_runs(running_ttl_seconds=600),
    )

    assert stale.id in [run.id for batch in results for run in batch]
    final = await repository.get_agent_run(stale.id)
    assert final is not None
    assert final.status == "failed"
    assert final.metadata["reaped"] is True


@pytest.mark.asyncio
async def test_reap_does_not_overwrite_a_run_finalized_during_the_sweep_window():
    """A finalize landing between the stale read and the reap write is not clobbered (W1 CAS)."""

    class _FinalizeDuringSweepRepo(repository_module.InMemoryWaypointRepository):
        """Simulate a real finalize landing in the window between list and the CAS reap write."""

        def __init__(self) -> None:
            super().__init__()
            self._finalized_during_sweep = False

        async def list_stale_active_runs(self, cutoff, active_statuses):
            stale = await super().list_stale_active_runs(cutoff, active_statuses)
            # The orchestrator finalizes the run right after the sweeper read it as stale but
            # before the sweeper's compare-and-swap write lands.
            if stale and not self._finalized_during_sweep:
                self._finalized_during_sweep = True
                for run in stale:
                    current = self.agent_runs[run.id]
                    self.agent_runs[run.id] = current.model_copy(
                        update={"status": "completed", "updated_at": datetime.now(UTC)}
                    )
            return stale

    repository = _FinalizeDuringSweepRepo()
    await repository.initialize(load_default_seed=False)
    service = RunsService(repository)

    run = await service.create_agent_run(
        AgentRunCreate(name="assurance:INV-FINALIZE-RACE"), actor="reaper-test@example.com"
    )
    await repository.update_agent_run(
        run.model_copy(update={"updated_at": run.updated_at - timedelta(hours=1)})
    )

    reaped = await service.reap_stale_runs(running_ttl_seconds=600)

    # The concurrent finalize wins: nothing is reaped and the run stays completed, not failed.
    assert reaped == []
    final = await repository.get_agent_run(run.id)
    assert final is not None
    assert final.status == "completed"
    assert "reaped" not in final.metadata


@pytest.mark.asyncio
async def test_case_create_is_idempotent_by_key(client: AsyncClient):
    """Creating a case twice with the same idempotency_key returns the same case."""
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    body = {
        "invoice_id": "inv-2026-08034",
        "finding_id": "finding-08034-investigation",
        "summary": "Investigate supplier-caused investigation charge.",
        "idempotency_key": "assurance-case:inv-2026-08034",
    }
    first = await client.post("/api/cases", json=body)
    second = await client.post("/api/cases", json=body)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = (await client.get("/api/cases", params={"invoice_id": "inv-2026-08034"})).json()
    matches = [c for c in listed if c.get("idempotency_key") == "assurance-case:inv-2026-08034"]
    assert len(matches) == 1
