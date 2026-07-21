"""Tests for OneLake corpus document resolution and the context gateway."""

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.common.database import reset_waypoint_repository_for_tests
from app.common.onelake import (
    SOURCE_ONELAKE,
    SOURCE_URI_ONLY,
    OneLakeClient,
    ResolvedBytes,
    ResolvedDocument,
    resolve_corpus_path,
)
from app.common.settings import Settings, get_settings
from app.main import app
from app.modules.records.routes import get_records_onelake_client
from app.modules.records.schemas import ContractDocument, Policy
from app.modules.records.service import build_contract_document_detail, build_policy_detail
from app.modules.work.routes import get_work_onelake_client


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    reset_waypoint_repository_for_tests()


def override_settings(settings: Settings) -> None:
    app.dependency_overrides[get_settings] = lambda: settings


class _FakeOneLake:
    """Minimal OneLake stand-in that returns canned text for resolved documents."""

    def __init__(
        self,
        text_by_category: dict[str, str],
        bytes_by_category: dict[str, bytes] | None = None,
    ) -> None:
        self._text_by_category = text_by_category
        self._bytes_by_category = bytes_by_category or {}

    def resolve_document(self, uri: str | None, category: str) -> ResolvedDocument:
        text = self._text_by_category.get(category)
        if text is None:
            return ResolvedDocument(text=None, content_source=SOURCE_URI_ONLY)
        return ResolvedDocument(text=text, content_source=SOURCE_ONELAKE, path=f"{category}/x")

    def resolve_document_bytes(self, uri: str | None, category: str) -> ResolvedBytes:
        data = self._bytes_by_category.get(category)
        if data is None:
            return ResolvedBytes(data=None, content_source=SOURCE_URI_ONLY)
        return ResolvedBytes(data=data, content_source=SOURCE_ONELAKE, path=f"{category}/x")


def test_resolve_corpus_path_maps_categories_to_corpus_layout():
    prefix = "Files/corpus"
    assert (
        resolve_corpus_path("data/contracts/source-markdown/cmo-001-msa.md", "contract", prefix)
        == "Files/corpus/contracts/cmo-001-msa.md"
    )
    assert (
        resolve_corpus_path("ledgerfield://generated/invoices/INV-1.html", "invoice-html", prefix)
        == "Files/corpus/invoices/html/INV-1.html"
    )
    assert (
        resolve_corpus_path("policy-surge-approval.md", "policy", prefix)
        == "Files/corpus/policies/policy-surge-approval.md"
    )


def test_resolve_corpus_path_passes_through_lake_native_paths():
    prefix = "Files/corpus"
    assert (
        resolve_corpus_path("onelake://Files/corpus/seed/waypoint-seed.json", "contract", prefix)
        == "Files/corpus/seed/waypoint-seed.json"
    )
    assert (
        resolve_corpus_path("Files/corpus/contracts/x.md", "contract", prefix)
        == "Files/corpus/contracts/x.md"
    )
    assert resolve_corpus_path(None, "contract", prefix) is None


def test_unconfigured_onelake_client_degrades_to_uri_only():
    client = OneLakeClient(Settings())
    assert client.configured is False
    resolved = client.resolve_document("data/contracts/x.md", "contract")
    assert resolved.text is None
    assert resolved.content_source == SOURCE_URI_ONLY


def test_document_builders_skip_content_when_not_requested():
    document = ContractDocument(id="doc-1", supplier_id="sup-1", title="MSA", uri="data/x.md")
    policy = Policy(id="policy-1", name="Surge")
    fake = _FakeOneLake({"contract": "CONTRACT TEXT", "policy": "POLICY TEXT"})

    contract_detail = build_contract_document_detail(document, fake, include_content=False)
    policy_detail = build_policy_detail(policy, fake, include_content=False)

    assert contract_detail.text is None
    assert contract_detail.content_source == SOURCE_URI_ONLY
    assert policy_detail.text is None
    assert policy_detail.content_source == SOURCE_URI_ONLY


def test_document_builders_resolve_content_from_lake():
    document = ContractDocument(id="doc-1", supplier_id="sup-1", title="MSA", uri="data/x.md")
    policy = Policy(id="policy-1", name="Surge")
    fake = _FakeOneLake({"contract": "CONTRACT TEXT", "policy": "POLICY TEXT"})

    contract_detail = build_contract_document_detail(document, fake, include_content=True)
    policy_detail = build_policy_detail(policy, fake, include_content=True)

    assert contract_detail.text == "CONTRACT TEXT"
    assert contract_detail.content_source == SOURCE_ONELAKE
    assert policy_detail.text == "POLICY TEXT"
    assert policy_detail.content_source == SOURCE_ONELAKE


@pytest.mark.asyncio
async def test_document_endpoints_are_lean_by_default(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    contract = await client.get("/api/contract-documents/doc-cap-bluepeak-2026")
    policy = await client.get("/api/policies/policy-supplier-caused-cost")

    assert contract.status_code == 200
    assert contract.json()["text"] is None
    assert contract.json()["content_source"] == SOURCE_URI_ONLY
    assert policy.status_code == 200
    assert policy.json()["text"] is None
    assert policy.json()["content_source"] == SOURCE_URI_ONLY


@pytest.mark.asyncio
async def test_document_endpoints_resolve_text_when_requested(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))
    app.dependency_overrides[get_records_onelake_client] = lambda: _FakeOneLake(
        {
            "contract": "BLUEPEAK CAPACITY AGREEMENT BODY",
            "policy": "SUPPLIER-CAUSED COST POLICY BODY",
        }
    )

    contract = await client.get(
        "/api/contract-documents/doc-cap-bluepeak-2026?include_content=true"
    )
    policy = await client.get("/api/policies/policy-supplier-caused-cost?include_content=true")

    assert contract.json()["text"] == "BLUEPEAK CAPACITY AGREEMENT BODY"
    assert contract.json()["content_source"] == SOURCE_ONELAKE
    assert policy.json()["text"] == "SUPPLIER-CAUSED COST POLICY BODY"
    assert policy.json()["content_source"] == SOURCE_ONELAKE


@pytest.mark.asyncio
async def test_invoice_pdf_streams_bytes_from_lake(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))
    pdf_bytes = b"%PDF-1.7 fake invoice body"
    app.dependency_overrides[get_records_onelake_client] = lambda: _FakeOneLake(
        {}, bytes_by_category={"invoice-pdf": pdf_bytes}
    )

    response = await client.get("/api/invoices/inv-2026-08034/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content == pdf_bytes


@pytest.mark.asyncio
async def test_invoice_pdf_returns_409_when_lake_unavailable(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get("/api/invoices/inv-2026-08034/pdf")

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_invoice_pdf_returns_404_for_unknown_invoice(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get("/api/invoices/inv-does-not-exist/pdf")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_context_bundle_includes_document_text_from_lake(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))
    app.dependency_overrides[get_work_onelake_client] = lambda: _FakeOneLake(
        {
            "contract": "BLUEPEAK CAPACITY AGREEMENT BODY",
            "policy": "SUPPLIER-CAUSED COST POLICY BODY",
        }
    )

    response = await client.get("/api/invoices/inv-2026-08034/context")

    assert response.status_code == 200
    bundle = response.json()
    assert bundle["contract_documents"][0]["text"] == "BLUEPEAK CAPACITY AGREEMENT BODY"
    assert bundle["contract_documents"][0]["content_source"] == SOURCE_ONELAKE
    assert bundle["policies"][0]["text"] == "SUPPLIER-CAUSED COST POLICY BODY"
    assert bundle["policies"][0]["content_source"] == SOURCE_ONELAKE


@pytest.mark.asyncio
async def test_context_bundle_degrades_without_lake(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    response = await client.get("/api/invoices/inv-2026-08034/context")

    assert response.status_code == 200
    bundle = response.json()
    assert bundle["contract_documents"][0]["text"] is None
    assert bundle["contract_documents"][0]["content_source"] == SOURCE_URI_ONLY


@pytest.mark.asyncio
async def test_slow_onelake_read_does_not_block_other_requests(client: AsyncClient):
    override_settings(Settings(local_auth_enabled=True, default_seed_enabled=True))

    class _SlowOneLake(_FakeOneLake):
        def resolve_document(self, uri: str | None, category: str) -> ResolvedDocument:
            time.sleep(0.1)
            return super().resolve_document(uri, category)

    app.dependency_overrides[get_work_onelake_client] = lambda: _SlowOneLake(
        {"contract": "CONTRACT", "policy": "POLICY"}
    )

    context_request = asyncio.create_task(client.get("/api/invoices/inv-2026-08034/context"))
    await asyncio.sleep(0.02)

    assert not context_request.done()
    health = await client.get("/health")
    assert health.status_code == 200
    assert (await context_request).status_code == 200
