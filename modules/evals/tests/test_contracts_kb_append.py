import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceExistsError

SOURCE = Path(__file__).resolve().parents[2] / "corpus" / "src" / "ledgerfield"


@pytest.fixture
def uploader():
    name = "_corpus_upload_tests"
    spec = importlib.util.spec_from_file_location(
        name, SOURCE / "__init__.py", submodule_search_locations=[str(SOURCE)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    module = importlib.import_module(f"{name}.contracts_kb_upload")
    return module


class Container:
    def __init__(self, existing=None):
        self.blobs = dict(existing or {})
        self.deleted = []

    def upload_blob(self, name, data, overwrite):
        if name in self.blobs and not overwrite:
            raise ResourceExistsError("already exists")
        self.blobs[name] = data

    def download_blob(self, name):
        return SimpleNamespace(readall=lambda: self.blobs[name])

    def list_blobs(self, name_starts_with):
        return [
            SimpleNamespace(name=name)
            for name in self.blobs if name.startswith(name_starts_with)
        ]

    def delete_blob(self, name):
        self.deleted.append(name)
        del self.blobs[name]


def test_append_preserves_other_evidence_and_reuses_identical(uploader):
    client = Container({"contracts/original.md": b"original", "contracts/new/doc.md": b"doc"})
    summary = uploader.ContractsKbSummary("storage", "knowledge", "contracts/new")
    uploader._sync_documents(
        client, "contracts/new",
        [uploader.BlobDocument("doc.md", b"doc"), uploader.BlobDocument("other.md", b"other")],
        summary, append_only=True,
    )
    assert client.blobs["contracts/original.md"] == b"original"
    assert summary.reused == ["contracts/new/doc.md"]
    assert summary.uploaded == ["contracts/new/other.md"]
    assert not client.deleted
    assert len(summary.document_sha256) == 2


def test_append_refuses_overwrite(uploader):
    client = Container({"contracts/new/doc.md": b"original"})
    summary = uploader.ContractsKbSummary("storage", "knowledge", "contracts/new")
    with pytest.raises(ValueError, match="conflicts"):
        uploader._sync_documents(
            client, "contracts/new", [uploader.BlobDocument("doc.md", b"changed")],
            summary, append_only=True,
        )
    assert client.blobs["contracts/new/doc.md"] == b"original"


def test_default_sync_still_removes_stale_docs(uploader):
    client = Container({
        "contracts/old.md": b"old",
        "contracts/policy-analyst-v1/new.md": b"separate benchmark evidence",
    })
    summary = uploader.ContractsKbSummary("storage", "knowledge", "contracts")
    uploader._sync_documents(
        client, "contracts", [uploader.BlobDocument("new.md", b"new")], summary
    )
    assert summary.deleted == ["contracts/old.md"]
    assert client.blobs["contracts/policy-analyst-v1/new.md"] == b"separate benchmark evidence"


def test_operational_upload_never_reads_scenario_answers(uploader, tmp_path):
    for folder in ("contracts", "policies", "operational", "invoices"):
        directory = tmp_path / folder / "source-markdown"
        directory.mkdir(parents=True)
        (directory / f"{folder}.md").write_text(folder)
    (tmp_path / "answers.json").write_text('{"expected_action": "recover"}')
    documents = uploader._collect_documents(
        tmp_path, include_policies=True, include_operational=True
    )
    assert {document.name for document in documents} == {
        "contracts.md", "policies.md", "operational.md", "invoices.md"
    }


def test_custom_root_requires_append_only(uploader, tmp_path):
    with pytest.raises(ValueError, match="append-only"):
        uploader.upload_contracts_kb(storage_account="storage", source_root=tmp_path)
