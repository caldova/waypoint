from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

import observability


@pytest.mark.parametrize("existing", [False, True])
def test_native_export_preserves_offline_or_existing_configuration(monkeypatch, existing):
    monkeypatch.setenv("CPA_NATIVE_TRACE_PROJECT", "true" if existing else "false")
    monkeypatch.delenv("AZURE_MONITOR_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    if existing:
        monkeypatch.setenv("AZURE_MONITOR_CONNECTION_STRING", "existing-test-binding")
    monkeypatch.setattr(
        observability, "DefaultAzureCredential",
        lambda: pytest.fail("Must not perform redundant or offline discovery."),
    )
    observability.configure_project_export()


def test_project_binding_is_process_local_and_reports_discovery_failures(monkeypatch, caplog):
    monkeypatch.setenv("CPA_NATIVE_TRACE_PROJECT", "true")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.invalid/project")
    monkeypatch.delenv("AZURE_MONITOR_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    class Credential:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Project(Credential):
        def __init__(self, **kwargs):
            self.telemetry = SimpleNamespace(
                get_application_insights_connection_string=lambda: "synthetic-test-binding",
            )

    monkeypatch.setattr(observability, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(observability, "AIProjectClient", Project)
    observability.configure_project_export()
    assert observability.os.environ["AZURE_MONITOR_CONNECTION_STRING"] == "synthetic-test-binding"
    monkeypatch.delenv("AZURE_MONITOR_CONNECTION_STRING")

    def failed_project(**kwargs):
        raise ResourceNotFoundError("Sensitive diagnostic text must not be logged.")

    monkeypatch.setattr(observability, "AIProjectClient", failed_project)
    observability.configure_project_export()
    assert "AZURE_MONITOR_CONNECTION_STRING" not in observability.os.environ
    assert "ResourceNotFoundError" in caplog.text
    assert "Sensitive diagnostic" not in caplog.text
